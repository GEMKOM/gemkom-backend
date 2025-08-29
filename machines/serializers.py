from machines.models import Machine, MachineFault
from rest_framework import serializers

class MachineSerializer(serializers.ModelSerializer):
    class Meta:
        model = Machine
        fields = '__all__'  # Includes all fields, including JSON and label

class MachineGetSerializer(serializers.ModelSerializer):
    machine_type_label = serializers.SerializerMethodField()
    used_in_label = serializers.SerializerMethodField()
    is_under_maintenance = serializers.SerializerMethodField()
    has_active_timer = serializers.SerializerMethodField()
    active_timer_ids = serializers.SerializerMethodField()

    class Meta:
        model = Machine
        fields = [
            'id', 'name', 'machine_type', 'used_in', 'used_in_label', 'machine_type_label',
            'is_active', 'has_active_timer', 'active_timer_ids',
            'is_under_maintenance', 'jira_id', 'properties'
        ]

    def get_machine_type_label(self, obj):
        return obj.get_machine_type_display()
    
    def get_used_in_label(self, obj):
        return obj.get_used_in_display()
    
    def get_is_under_maintenance(self, obj):
        return MachineFault.objects.filter(
            machine=obj,
            resolved_at__isnull=True,
            is_breaking=True
        ).exists()

    def get_has_active_timer(self, obj):
        from machining.models import Timer
        return Timer.objects.filter(machine_fk=obj, finish_time__isnull=True).exists()

    def get_active_timer_ids(self, obj):
        from machining.models import Timer
        return list(Timer.objects.filter(machine_fk=obj, finish_time__isnull=True).values_list('id', flat=True))

class MachineListSerializer(serializers.ModelSerializer):
    machine_type_label = serializers.SerializerMethodField()
    used_in_label = serializers.SerializerMethodField()
    is_under_maintenance = serializers.SerializerMethodField()
    has_active_timer = serializers.SerializerMethodField()

    class Meta:
        model = Machine
        fields = ['id', 'name', 'machine_type', 'used_in', 'used_in_label', 'machine_type_label', 'is_active', 'has_active_timer', 'is_under_maintenance', 'jira_id', 'properties']

    def get_machine_type_label(self, obj):
        return obj.get_machine_type_display()
    
    def get_used_in_label(self, obj):
        return obj.get_used_in_display()
    
    def get_is_under_maintenance(self, obj):
        return MachineFault.objects.filter(
            machine=obj,
            resolved_at__isnull=True,
            is_breaking=True
        ).exists()

    def get_has_active_timer(self, obj):
        from machining.models import Timer  # again, for safety
        return Timer.objects.filter(machine_fk=obj, finish_time__isnull=True).exists()

    
class MachineFaultSerializer(serializers.ModelSerializer):
    machine_name = serializers.CharField(source='machine.name', read_only=True)
    reported_by_username = serializers.CharField(source='reported_by.username', read_only=True)
    resolved_by_username = serializers.CharField(source='resolved_by.username', read_only=True)

    class Meta:
        model = MachineFault
        fields = ['id', 'machine', 'machine_name', 'description', 'reported_by', 'reported_by_username',
                  'reported_at', 'resolved_at', 'is_breaking', 'is_maintenance', 'resolution_description', 'resolved_by', 'resolved_by_username']
        read_only_fields = ['id', 'reported_by', 'reported_at']