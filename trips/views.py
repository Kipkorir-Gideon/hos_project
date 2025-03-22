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