from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
import requests
from django.conf import settings
from .models import Trip, DutyStatus
from .serializers import TripSerializer
from django.db import transaction
from datetime import datetime, timedelta
from math import radians, sin, cos, sqrt, atan2

def convert_keys(data):
    """Convert snake_case keys to camelCase recursively."""
    if isinstance(data, dict):
        return {to_camel_case(key): convert_keys(value) for key, value in data.items()}
    elif isinstance(data, list):
        return [convert_keys(item) for item in data]
    return data

def to_camel_case(snake_str):
    components = snake_str.split('_')
    return components[0] + ''.join(x.capitalize() for x in components[1:])

def geocode(location):
    response = requests.get(
        f"https://api.openrouteservice.org/geocode/search?api_key={settings.OPENROUTESERVICE_API_KEY}&text={location}"
    )
    if response.status_code != 200 or not response.json().get('features'):
        raise Exception(f"Geocoding failed for {location}: {response.text}")
    coords = response.json()['features'][0]['geometry']['coordinates']
    return [coords[1], coords[0]]  # [lat, lon]

def calculate_distance(coords1, coords2):
    R = 3958.8  # Earth's radius in miles
    lat1, lon1 = radians(coords1[0]), radians(coords1[1])
    lat2, lon2 = radians(coords2[0]), radians(coords2[1])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = sin(dlat/2)**2 + cos(lat1) * cos(lat2) * sin(dlon/2)**2
    c = 2 * atan2(sqrt(a), sqrt(1-a))
    return R * c

def get_route(start, waypoints, end):
    coordinates = [start] + waypoints + [end]
    response = requests.post(
        "https://api.openrouteservice.org/v2/directions/driving-car/geojson",
        json={"coordinates": [[coord[1], coord[0]] for coord in coordinates]},
        headers={
            "Authorization": f"Bearer {settings.OPENROUTESERVICE_API_KEY}",
            "Content-Type": "application/json",
        },
    )
    if response.status_code != 200:
        raise Exception(f"Route API failed: {response.text}")
    route_data = response.json()
    route_coords = route_data['features'][0]['geometry']['coordinates']
    return [[coord[1], coord[0]] for coord in route_coords]

def calculate_distance_along_route(route_coords, target_distance):
    """Interpolate a point along the route at the target distance (in miles)."""
    total_distance = 0.0
    for i in range(len(route_coords) - 1):
        point1 = route_coords[i]
        point2 = route_coords[i + 1]
        R = 3958.8
        lat1, lon1 = radians(point1[0]), radians(point1[1])
        lat2, lon2 = radians(point2[0]), radians(point2[1])
        dlat = lat2 - lat1
        dlon = lon2 - lon1
        a = sin(dlat/2)**2 + cos(lat1) * cos(lat2) * sin(dlon/2)**2
        c = 2 * atan2(sqrt(a), sqrt(1-a))
        segment_distance = R * c
        total_distance += segment_distance

        if total_distance >= target_distance:
            overshoot = total_distance - target_distance
            fraction = overshoot / segment_distance
            lat = point2[0] - fraction * (point2[0] - point1[0])
            lon = point2[1] - fraction * (point2[1] - point1[1])
            return [lat, lon]
    return route_coords[-1]

def add_time(current_time, hours_to_add):
    """Add hours to a time string (HH:MM) and handle day overflow."""
    if not current_time:
        return "00:00", 0
    current_hours, current_minutes = map(int, current_time.split(":"))
    total_minutes = current_hours * 60 + current_minutes + int(hours_to_add * 60)
    days_added = total_minutes // (24 * 60)
    remaining_minutes = total_minutes % (24 * 60)
    new_hours = remaining_minutes // 60
    new_minutes = remaining_minutes % 60
    return f"{new_hours:02d}:{new_minutes:02d}", days_added

class PlanTripView(APIView):
    @transaction.atomic
    def post(self, request):
        current_location = request.data.get('current_location')
        pickup_location = request.data.get('pickup_location')
        dropoff_location = request.data.get('dropoff_location')
        cycle_used = float(request.data.get('cycle_used', 0))

        if not all([current_location, pickup_location, dropoff_location]):
            return Response({"error": "Missing required fields"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            start_coords = geocode(current_location)
            pickup_coords = geocode(pickup_location)
            dropoff_coords = geocode(dropoff_location)
        except Exception as e:
            return Response({"error": f"Geocoding failed: {str(e)}"}, status=status.HTTP_400_BAD_REQUEST)

        distance_to_pickup = calculate_distance(start_coords, pickup_coords)
        distance_to_dropoff = calculate_distance(pickup_coords, dropoff_coords)
        total_distance = distance_to_pickup + distance_to_dropoff

        try:
            route_coordinates = get_route(start_coords, [], dropoff_coords)
        except Exception as e:
            return Response({"error": f"Route calculation failed: {str(e)}"}, status=status.HTTP_400_BAD_REQUEST)

        num_fueling_stops = int(total_distance / 1000)
        stops = []
        stop_coordinates = []
        distance_per_stop = total_distance / (num_fueling_stops + 1) if num_fueling_stops > 0 else total_distance
        for i in range(num_fueling_stops):
            target_distance = (i + 1) * distance_per_stop
            stop_coords = calculate_distance_along_route(route_coords=route_coordinates, target_distance=target_distance)
            stops.append({
                "location": f"Mile {target_distance:.1f} (approx)",
                "type": "Fueling Stop",
            })
            stop_coordinates.append(stop_coords)

        trip = Trip.objects.create(
            current_location=current_location,
            pickup_location=pickup_location,
            dropoff_location=dropoff_location,
            cycle_used=cycle_used,
        )

        driving_time_to_pickup = distance_to_pickup / 60
        driving_time_to_dropoff = distance_to_dropoff / 60
        total_driving_time = driving_time_to_pickup + driving_time_to_dropoff
        total_on_duty_time = total_driving_time + 3  # 1h pickup + 1h dropoff + 1h fueling stops
        remaining_cycle = 70 - cycle_used - total_on_duty_time

        duty_statuses = []
        start_date = datetime(2025, 3, 25).date()
        current_date = start_date
        day_offset = 0
        current_location = current_location

        # Start of the trip
        start_time = "00:00"
        end_time, days_added = add_time(start_time, driving_time_to_pickup)
        day_offset += days_added
        current_date = start_date + timedelta(days=day_offset)
        duty_statuses.append({
            "date": str(current_date),
            "start": start_time,
            "end": end_time,
            "status": "Driving",
            "remarks": f"Driving from {current_location} to {pickup_location}",
        })
        current_location = pickup_location

        # Pickup
        start_time = end_time
        end_time, days_added = add_time(start_time, 1)
        day_offset += days_added
        current_date = start_date + timedelta(days=day_offset)
        duty_statuses.append({
            "date": str(current_date),
            "start": start_time,
            "end": end_time,
            "status": "On Duty (Not Driving)",
            "remarks": f"Pickup at {pickup_location}",
        })

        # Mandatory 30-minute break
        start_time = end_time
        end_time, days_added = add_time(start_time, 0.5)
        day_offset += days_added
        current_date = start_date + timedelta(days=day_offset)
        duty_statuses.append({
            "date": str(current_date),
            "start": start_time,
            "end": end_time,
            "status": "Off Duty",
            "remarks": "Mandatory 30-minute break",
        })

        # Drive to dropoff with fueling stops
        remaining_distance = distance_to_dropoff
        distance_covered = 0
        start_time = end_time
        for i in range(num_fueling_stops + 1):
            leg_distance = min(remaining_distance, 1000)
            driving_time = leg_distance / 60
            distance_covered += leg_distance
            remaining_distance -= leg_distance

            # Split driving time across days if it crosses midnight
            current_time = start_time
            remaining_driving_time = driving_time
            while remaining_driving_time > 0:
                current_minutes = int(current_time.split(":")[0]) * 60 + int(current_time.split(":")[1])
                minutes_to_midnight = (24 * 60) - current_minutes
                hours_to_midnight = minutes_to_midnight / 60.0

                if remaining_driving_time <= hours_to_midnight:
                    end_time, days_added = add_time(current_time, remaining_driving_time)
                    day_offset += days_added
                    current_date = start_date + timedelta(days=day_offset)
                    duty_statuses.append({
                        "date": str(current_date),
                        "start": current_time,
                        "end": end_time,
                        "status": "Driving",
                        "remarks": f"Driving towards {dropoff_location}",
                    })
                    remaining_driving_time = 0
                else:
                    end_time = "24:00"
                    duty_statuses.append({
                        "date": str(current_date),
                        "start": current_time,
                        "end": end_time,
                        "status": "Driving",
                        "remarks": f"Driving towards {dropoff_location}",
                    })
                    remaining_driving_time -= hours_to_midnight
                    current_time = "00:00"
                    day_offset += 1
                    current_date = start_date + timedelta(days=day_offset)

            start_time = end_time

            if i < num_fueling_stops:
                end_time, days_added = add_time(start_time, 0.5)  # 30 minutes for fueling stop
                day_offset += days_added
                current_date = start_date + timedelta(days=day_offset)
                duty_statuses.append({
                    "date": str(current_date),
                    "start": start_time,
                    "end": end_time,
                    "status": "Off Duty",
                    "remarks": f"Fueling stop at {stops[i]['location']}",
                })

                start_time = end_time
                end_time, days_added = add_time(start_time, 0.5)  # 30 minutes break
                day_offset += days_added
                current_date = start_date + timedelta(days=day_offset)
                duty_statuses.append({
                    "date": str(current_date),
                    "start": start_time,
                    "end": end_time,
                    "status": "Off Duty",
                    "remarks": "Mandatory 30-minute break",
                })
                start_time = end_time

        # Dropoff
        end_time, days_added = add_time(start_time, 1)
        day_offset += days_added
        current_date = start_date + timedelta(days=day_offset)
        duty_statuses.append({
            "date": str(current_date),
            "start": start_time,
            "end": end_time,
            "status": "On Duty (Not Driving)",
            "remarks": f"Dropoff towards {dropoff_location}",
        })

        # End of the day
        start_time = end_time
        end_time = "24:00"
        duty_statuses.append({
            "date": str(current_date),
            "start": start_time,
            "end": end_time,
            "status": "Off Duty",
            "remarks": "End of day - HOS limit reached",
        })

        # Save duty statuses
        for status_entry in duty_statuses:
            DutyStatus.objects.create(
                trip=trip,
                date=status_entry['date'],
                start_time=status_entry['start'],
                end_time=status_entry['end'],
                status=status_entry['status'],
                remarks=status_entry['remarks'],
            )

        trip.refresh_from_db()
        serializer = TripSerializer(trip)

        response_data = {
            "trip": serializer.data,
            "stops": stops,
            "total_distance": total_distance,
            "total_driving_time": total_driving_time,
            "total_on_duty_time": total_on_duty_time,
            "remaining_cycle": remaining_cycle,
            "route_coordinates": route_coordinates,
            "start_coords": start_coords,
            "pickup_coords": pickup_coords,
            "stop_coords": stop_coordinates,
            "end_coords": dropoff_coords,
        }
        camel_case_response = convert_keys(response_data)
        return Response(camel_case_response, status=status.HTTP_201_CREATED)