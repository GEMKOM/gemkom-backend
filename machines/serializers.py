from machines.models import Machine, MachineFault
from rest_framework import serializers

class MachineSerializer(serializers.ModelSerializer):
    class Meta:
        model = Machine
        fields = '__all__'  # Includes all fields, including JSON and label

class MachineListSerializer(serializers.ModelSerializer):
    machine_type_label = serializers.SerializerMethodField()
    is_under_maintenance = serializers.SerializerMethodField()

    class Meta:
        model = Machine
        fields = ['id', 'name', 'machine_type', 'used_in', 'machine_type_label', 'is_active', 'is_under_maintenance', 'jira_id', 'properties']

    def get_machine_type_label(self, obj):
        return obj.get_machine_type_display()
    
    def get_is_under_maintenance(self, obj):
        return MachineFault.objects.filter(machine=obj, resolved_at__isnull=True).exists()
    
class MachineFaultSerializer(serializers.ModelSerializer):
    machine_name = serializers.CharField(source='machine.name', read_only=True)
    reported_by_username = serializers.CharField(source='reported_by.username', read_only=True)

    class Meta:
        model = MachineFault
        fields = ['id', 'machine', 'machine_name', 'description', 'reported_by', 'reported_by_username',
                  'reported_at', 'resolved_at']
        read_only_fields = ['id', 'reported_by', 'reported_at']