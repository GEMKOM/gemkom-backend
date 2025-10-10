from rest_framework import serializers
from .models import CncTask

class CncTaskSerializer(serializers.ModelSerializer):
    """
    Serializer for the CncTask model.
    Handles creation, retrieval, and updates for CNC tasks,
    including the 'nesting_pdf' file upload.
    """
    # nesting_pdf is a FileField, which DRF handles for multipart uploads.
    # We make it read-only when retrieving a list, but writeable on create/update.
    nesting_pdf_url = serializers.URLField(source='nesting_pdf.url', read_only=True)

    class Meta:
        model = CncTask
        # Inherited fields from BaseTask like 'key', 'name', 'job_no' are included automatically.
        fields = [
            'key', 'name', 'nesting_id', 'material',
            'dimensions', 'thickness_mm', 'nesting_pdf', 'nesting_pdf_url'
        ]
        read_only_fields = ['key', 'nesting_pdf_url']
        extra_kwargs = {
            'nesting_pdf': {'write_only': True, 'required': False}
        }