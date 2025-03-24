from rest_framework import generics
from .models import Trip
from .serializers import TripSerializer
import requests
from django.http import JsonResponse
from datetime import datetime, timedelta
from decouple import config
from django.views.decorators.csrf import csrf_exempt
import json


class TripCreateView(generics.CreateAPIView):
    queryset = Trip.objects.all()
    serializer_class = TripSerializer
    

@csrf_exempt
def calculate_route(request):
    
    if request.method == 'POST':
        # Parse JSON body instead of using request.POST
        try:
            data = json.loads(request.body)
            trip_id = data.get('trip_id')
        except json.JSONDecodeError:
            return JsonResponse({"error": "Invalid JSON"}, status=400)
        
        if not trip_id:
            return JsonResponse({"error": "trip_id is required"}, status=400)

        try:
            trip = Trip.objects.get(id=trip_id)
        except Trip.DoesNotExist:
            return JsonResponse({"error": "Trip not found"}, status=404)

        api_key = config('OPENROUTESERVICE_API_KEY')
        url = config('OPENROUTESERVICE_URL')

        params = {
            "api_key": api_key,
            "start": trip.current_location,
            "end": trip.dropoff_location,
            "waypoints": f"{trip.pickup_location}"
        }
        response = requests.get(url, params=params)

        if response.status_code != 200:
            return JsonResponse({"error": "Failed to fetch route data", "details": response.text}, status=502)

        route_data = response.json()
        coordinates = route_data['feature'][0]['geometry']['coordinates']
        distance = route_data['features'][0]['properties']['summary']['distance'] / 1609.34
        duration = route_data['features'][0]['properties']['summary']['duration'] / 3600
        logs, stops = generate_logs_and_stops(trip, distance, duration)
        
        response_data = {
            'route': coordinates,
            'distance': distance,
            'duration': duration,
            'logs': logs,
            'stops': stops
        }

        return JsonResponse(response_data)
    else:
        return JsonResponse({"error": "Method not allowed. Use POST."}, status=405)
        
        
def generate_logs_and_stops(trip, distance, coordinates):
    AVG_SPEED = 60 # 60 mph
    FUEL_INTERVAL = 1000 # 1,000 miles
    MAX_DRIVING_HOURS = 11
    MAX_ON_DUTY_HOURS = 14
    REST_DURATION = 10 # 10 hours
    BREAK_DURATION = 0.5 # 30 minutes
    PICKUP_DROP_DURATION = 1 # 1 hour
    
    
    remaining_cycle = 70 - trip.current_cycle_hours
    driving_hours_left = min(11, remaining_cycle)
    stops = []
    logs = []
    current_time = datetime.now()
    miles_driven = 0
    hours_driven = 0
    driving_hours_today = 0
    on_duty_hours_today = 0
    total_hours_used = trip.current_cycle_hours
    coord_index = 0
    
    def get_location_at_distance(miles):
        nonlocal coord_index
        fraction = miles / distance
        target_index = int(len(coordinates) * fraction)
        coord_index = min(target_index, len(coordinates) - 1)
        return f'{coordinates[coord_index][0]},{coordinates[coord_index][1]}'
    
    # Add pickup stop
    stops.append({'type': 'pickup', 'location': trip.pickup_location, 'duration': PICKUP_DROP_DURATION, 'time': current_time.isoformat()})
    current_time += timedelta(hours=PICKUP_DROP_DURATION)
    on_duty_hours_today += PICKUP_DROP_DURATION
    
    while miles_driven < distance:
        miles_left = distance - miles_driven
        driving_time_left = min(miles_left / AVG_SPEED, MAX_DRIVING_HOURS - driving_hours_today)
        
        if driving_hours_today >= 8 and driving_time_left > 0:
            stops.append({'type': 'break', 'location': get_location_at_distance(miles_driven), 'duration': REST_DURATION, 'time': current_time.isoformat()})
            current_time += timedelta(hour=BREAK_DURATION)
            on_duty_hours_today += BREAK_DURATION
            
        if miles_driven + FUEL_INTERVAL <= distance and driving_time_left > 0:
            fuel_miles = min(FUEL_INTERVAL, miles_left)
            fuel_time = fuel_miles / AVG_SPEED
            if driving_hours_today + fuel_time <= MAX_DRIVING_HOURS and on_duty_hours_today + fuel_time <= MAX_ON_DUTY_HOURS:
                miles_driven += fuel_miles
                driving_hours_today += fuel_time
                on_duty_hours_today += fuel_time + 0.5
                current_time += timedelta(hours=fuel_time + 0.5)
                stops.append({'type': 'fuel', 'location': get_location_at_distance(miles_driven), 'duration': 0.5, 'time': current_time.isoformat()})
                total_hours_used += fuel_time
                
        if driving_time_left > 0:
            drive_miles = min(miles_left, driving_time_left * AVG_SPEED)
            drive_time = drive_miles / AVG_SPEED
            if driving_hours_today + drive_time <= MAX_DRIVING_HOURS and on_duty_hours_today + drive_time <= MAX_ON_DUTY_HOURS:
                miles_driven += drive_miles
                driving_hours_today += drive_time
                on_duty_hours_today += drive_time
                current_time += timedelta(hours=drive_time)
                total_hours_used += drive_time
                
        if driving_hours_today >= MAX_DRIVING_HOURS or on_duty_hours_today >= MAX_ON_DUTY_HOURS or miles_driven >= distance:
            logs.append({
                'date': current_time.date().isoformat(),
                'driving_hours': driving_hours_today,
                'on_duty_hours': on_duty_hours_today,
                'off_duty_hours': REST_DURATION if miles_driven < distance else 0,
                'stops': [s for s in stops if s['time'].startswith(current_time.date().isoformat())]
            })
            if miles_driven < distance:
                stops.append({'type': 'rest', 'location': get_location_at_distance(miles_driven), 'duration': REST_DURATION, 'time': current_time.isoformat()})
                current_time += timedelta(hours=REST_DURATION)
                on_duty_hours_today = 0
                driving_hours_today = 0
                if total_hours_used >= 70:
                    return logs, stops
                
    stops.append({'type': 'dropoff', 'location': trip.dropoff_location, 'duration': PICKUP_DROP_DURATION, 'time': current_time.isoformat()})
    current_time += timedelta(hours=PICKUP_DROP_DURATION)
    on_duty_hours_today += PICKUP_DROP_DURATION
    logs[-1]['on_duty_hours'] = on_duty_hours_today
    logs[-1]['stops'] = [s for s in stops if s['time'].startswith(current_time.date().isoformat())]
    
    return logs, stops

