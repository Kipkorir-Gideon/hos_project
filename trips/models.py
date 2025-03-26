from django.db import models

class Trip(models.Model):
    current_location = models.CharField(max_length=255)
    pickup_location = models.CharField(max_length=255)
    dropoff_location = models.CharField(max_length=255)
    cycle_used = models.FloatField(default=0.0)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Trip from {self.current_location} to {self.dropoff_location}"

class DutyStatus(models.Model):
    trip = models.ForeignKey(Trip, on_delete=models.CASCADE, related_name='duty_statuses')
    date = models.DateField()
    start_time = models.CharField(max_length=5)
    end_time = models.CharField(max_length=5)
    status = models.CharField(max_length=50)
    remarks = models.TextField(blank=True)

    def __str__(self):
        return f"{self.status} on {self.date} from {self.start_time} to {self.end_time}"