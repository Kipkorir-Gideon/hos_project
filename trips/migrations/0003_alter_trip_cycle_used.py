# Generated by Django 5.1.7 on 2025-03-27 11:41

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('trips', '0002_rename_current_cycle_hours_trip_cycle_used_and_more'),
    ]

    operations = [
        migrations.AlterField(
            model_name='trip',
            name='cycle_used',
            field=models.FloatField(default=0.0),
        ),
    ]
