from machines.models import Machine, MachineFault
from rest_framework import serializers
from .models import MachineCalendar
from django.contrib.auth.models import User

class SimpleUserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ["id", "username", "first_name", "last_name"]

class MachineSerializer(serializers.ModelSerializer):
    class Meta:
        model = Machine
        fields = '__all__'  # Includes all fields, including JSON and label

class MachineMinimalSerializer(serializers.ModelSerializer):
    class Meta:
        model = Machine
        fields = ["id", "name", "code", "used_in"]

class MachineGetSerializer(serializers.ModelSerializer):
    assigned_users = SimpleUserSerializer(many=True, read_only=True)
    assigned_user_ids = serializers.PrimaryKeyRelatedField(
        many=True, write_only=True, required=False, queryset=User.objects.all(), source="assigned_users"
    )
    machine_type_label = serializers.SerializerMethodField()
    used_in_label = serializers.SerializerMethodField()
    is_under_maintenance = serializers.SerializerMethodField()
    has_active_timer = serializers.SerializerMethodField()
    active_timer_ids = serializers.SerializerMethodField()

    class Meta:
        model = Machine
        fields = [
            'id', 'name', 'code', 'machine_type', 'used_in', 'used_in_label', 'machine_type_label',
            'is_active', 'has_active_timer', 'active_timer_ids',
            'is_under_maintenance', 'jira_id', 'properties', "assigned_users", "assigned_user_ids"
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
        from tasks.models import Timer
        return Timer.objects.filter(machine_fk=obj, finish_time__isnull=True).exists()

    def get_active_timer_ids(self, obj):
        from tasks.models import Timer
        return list(Timer.objects.filter(machine_fk=obj, finish_time__isnull=True).values_list('id', flat=True))

class MachineListSerializer(serializers.ModelSerializer):
    assigned_users = SimpleUserSerializer(many=True, read_only=True)
    assigned_user_ids = serializers.PrimaryKeyRelatedField(
        many=True, write_only=True, required=False, queryset=User.objects.all(), source="assigned_users"
    )
    machine_type_label = serializers.SerializerMethodField()
    used_in_label = serializers.SerializerMethodField()
    is_under_maintenance = serializers.SerializerMethodField()
    has_active_timer = serializers.SerializerMethodField()
    tasks_count = serializers.IntegerField(read_only=True)  # <-- NEW
    total_estimated_hours = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True)  # <-- NEW


    class Meta:
        model = Machine
        fields = [
            'id', 'name', 'code', 'machine_type', 'used_in', 'used_in_label', 'machine_type_label',
            'is_active', 'has_active_timer', 'is_under_maintenance', 'jira_id', 'properties',
            'tasks_count', 'total_estimated_hours', "assigned_users", "assigned_user_ids"  # <-- NEW
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
        from tasks.models import Timer
        return Timer.objects.filter(machine_fk=obj, finish_time__isnull=True).exists()

    
class MachineFaultSerializer(serializers.ModelSerializer):
    # Readable helpers
    machine_name = serializers.CharField(source='machine.name', read_only=True)
    reported_by_username = serializers.CharField(source='reported_by.username', read_only=True)
    resolved_by_username = serializers.CharField(source='resolved_by.username', read_only=True)
    assigned_to_username = serializers.CharField(source='assigned_to.username', read_only=True)
    is_resolved = serializers.SerializerMethodField()

    def get_is_resolved(self, obj):
        return bool(obj.resolved_at)

    class Meta:
        model = MachineFault
        fields = [
            'id',
            # machine can be empty; fallbacks below handle outliers
            'machine', 'machine_name',
            'asset_name', 'location',

            'description',
            'reported_by', 'reported_by_username', 'reported_at',

            'is_breaking', 'is_maintenance',

            'assigned_to', 'assigned_to_username',

            'resolved_at', 'resolved_by', 'resolved_by_username',
            'resolution_description',

            'is_resolved',
        ]
        read_only_fields = ['id', 'reported_by', 'reported_at', 'is_resolved']

    def validate(self, attrs):
        # If no machine, require at least an asset_name to avoid totally anonymous faults
        machine = attrs.get('machine', getattr(self.instance, 'machine', None) if self.instance else None)
        asset_name = attrs.get('asset_name', getattr(self.instance, 'asset_name', '') if self.instance else '')
        if not machine and not (asset_name or '').strip():
            raise serializers.ValidationError("Provide 'asset_name' when 'machine' is not selected.")
        return super().validate(attrs)

# machining/serializers_calendar.py


class MachineCalendarWindowSerializer(serializers.Serializer):
    start = serializers.RegexField(r"^\d{2}:\d{2}$")
    end   = serializers.RegexField(r"^\d{2}:\d{2}$")
    end_next_day = serializers.BooleanField(required=False)

class MachineCalendarSerializer(serializers.ModelSerializer):
    # week_template keyed "0".."6" -> list[window]
    week_template = serializers.DictField(
        child=MachineCalendarWindowSerializer(many=True),
        required=False
    )
    # exceptions: [{date:'YYYY-MM-DD', windows:[...], note?}]
    work_exceptions = serializers.ListField(
        child=serializers.DictField(), required=False
    )

    class Meta:
        model = MachineCalendar
        fields = ['timezone', 'week_template', 'work_exceptions']
