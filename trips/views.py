from rest_framework import generics
from .models import Trip
from serializers import TripSerializer
import requests
from django.http import JsonResponse
from datetime import datetime, timedelta


class TripCreateView(generics.CreateAPIView):
    queryset = Trip.objects.all()
    serializer_class = TripSerializer
    


def calculate_route(request):
    if request.method =='POST':
        trip_id = request.POST.get('trip_id')
        trip = Trip.objects.get(id=trip_id)
        
        # Get route data from openrouteservice
        api_key = ""
        url = "https://api.openrouteservice.org/v2/directions/driving-car"
        params = {
            'api_key': api_key,
            'start': trip.current_location,
            'end': trip.dropoff_location,
            'waypoints': f'{trip.pickup_location}'
        }
        response = requests.get(url, params=params)
        route_data = response.json()
        
        # Extract distance (in meters) and duration (in seconds) from route data
        distance = route_data['features'][0]['properties']['summary']['distance'] / 1609.34 # Convert meters to miles
        duration = route_data['features'][0]['properties']['summary']['duration'] / 3600 # Convert hours
        
        # Calculate stops and logs
        logs, stops = generate_logs_and_stops(trip, distance, duration)
        
        return JsonResponse({
            'route': route_data['features'][0]['geometry']['coordinates'],
            'distance': distance,
            'duration': duration,
            'stops': stops,
            'logs': logs
        })
        
        
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