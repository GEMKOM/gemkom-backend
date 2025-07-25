from core.models import Machine
from rest_framework import serializers

class MachineListSerializer(serializers.ModelSerializer):
    machine_type_label = serializers.SerializerMethodField()

    class Meta:
        model = Machine
        fields = ['id', 'name', 'machine_type', 'used_in', 'machine_type_label', 'is_active', 'jira_id', 'properties']

    def get_machine_type_label(self, obj):
        return obj.get_machine_type_display()