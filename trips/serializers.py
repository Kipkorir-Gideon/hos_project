from rest_framework import serializers
from .models import Trip
from djangorestframework_camel_case.parser import CamelCaseJSONParser


class TripSerializer(serializers.ModelSerializer):
    class Meta:
        model = Trip
        fields = '__all__'
        parser_classes = (CamelCaseJSONParser,)