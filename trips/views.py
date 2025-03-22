from rest_framework import generics
from .models import Trip
from serializers import TripSerializer
import requests
from django.http import JsonResponse
from datetime import datetime, timedelta


class TripCreateView(generics.CreateAPIView):
    queryset = Trip.objects.all()
    serializer_class = TripSerializer
    


