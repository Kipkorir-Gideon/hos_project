from rest_framework import serializers
from .models import Trip, DutyStatus

class DutyStatusSerializer(serializers.ModelSerializer):
    class Meta:
        model = DutyStatus
        fields = ['date', 'start_time', 'end_time', 'status', 'remarks']

class TripSerializer(serializers.ModelSerializer):
    duty_statuses = DutyStatusSerializer(many=True, read_only=True)

    class Meta:
        model = Trip
        fields = ['id', 'current_location', 'pickup_location', 'dropoff_location', 'cycle_used', 'duty_statuses']