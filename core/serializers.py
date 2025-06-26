from core.models import Machine
from rest_framework import serializers

class MachineListSerializer(serializers.ModelSerializer):
    machine_type_label = serializers.SerializerMethodField()

    class Meta:
        model = Machine
        fields = [field.name for field in Machine._meta.fields] + ['machine_type_label']

    def get_machine_type_label(self, obj):
        return obj.get_machine_type_display()