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
        distance = route_data['features'][0]['properties']['summary']['distance'] / 1609.34
        duration = route_data['features'][0]['properties']['summary']['duration'] / 3600
        logs, stops = generate_logs_and_stops(trip, distance, duration)

        return JsonResponse({
            "route": route_data['features'][0]['geometry']['coordinates'],
            "distance": distance,
            "duration": duration,
            "stops": stops,
            "logs": logs
        })
    else:
        return JsonResponse({"error": "Method not allowed. Use POST."}, status=405)
        
        
def generate_logs_and_stops(trip, distance, duration):
    # HOS Rules: 11 hour driving, 14 hour window, 70 hour/8 day
    remaining_cycle = 70 - trip.current_cycle_hours
    driving_hours_left = min(11, remaining_cycle)
    stops = []
    logs = []
    current_time = datetime.now()
    miles_driven = 0
    hours_driven = 0
    
    # Add pickup stop
    stops.append({'type': 'pickup', 'location': trip.pickup_location, 'duration': 1})
    current_time += timedelta(hours=1) # 1 hour for pickup
    
    while miles_driven < distance:
        # Fuel stop every 1,000 miles
        if miles_driven + 500 >= 1000: # Assuming 500 miles/hour avg speed
            stops.append({'type': 'fuel', 'location': 'TBD', 'duration': 1})
            current_time += timedelta(hours=1)
            miles_driven += 500
            hours_driven += 1
            
        # Check HOS limits
        if hours_driven >= driving_hours_left or hours_driven >= 11:
            stops.append({'type': 'rest', 'location': 'TBD', 'duration': 10})
            logs.append(generate_log(current_time, hours_driven, stops))
            current_time += timedelta(hours=10) # 10 hours rest
            hours_driven = 0
            driving_hours_left = min(11, remaining_cycle - sum(log['driving_hours'] for log in logs))
        else:
            miles_to_drive = min(distance - miles_driven, 500) # 500 miles per segment
            hours_to_drive = miles_to_drive / 500 # Avg 500 mph
            miles_driven += miles_to_drive
            hours_driven += hours_to_drive
            
    # Add dropoff stop
    stops.append({'type': 'dropoff', 'location': trip.dropoff_location, 'duration': 1})
    logs.append(generate_log(current_time, hours_driven, stops))
    
    return logs, stops


def generate_log(start_time, driving_hours, stops):
    # Simplified log generation
    return {
        'date': start_time.strftime('%Y-%m-%d'),
        'driving_hours': driving_hours,
        'on_duty_hours': driving_hours + sum(s['duration'] for s in stops if s['type'] != 'rest'),
        'off_duty_hours': 10 if any(s['type'] == 'rest' for s in stops) else 0,
        'stops': stops
    }