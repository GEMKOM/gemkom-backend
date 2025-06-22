from rest_framework import serializers
from .models import Timer

class TimerSerializer(serializers.ModelSerializer):
    class Meta:
        model = Timer
        fields = [
            'id',
            'user',  # required by model, but will be auto-assigned
            'issue_key',
            'start_time',
            'finish_time',
            'synced_to_jira',
            'comment',
            'machine',
            'job_no',
            'image_no',
            'position_no',
            'quantity',
            'manual_entry',
        ]
        read_only_fields = ['id', 'user']  # don't allow frontend to set user

    def create(self, validated_data):
        validated_data['user'] = self.context['request'].user
        return super().create(validated_data)