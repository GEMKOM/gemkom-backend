from storages.backends.s3boto3 import S3Boto3Storage
from django.conf import settings

class PrivateMediaStorage(S3Boto3Storage):
    """
    Custom storage for private media files.
    Uploads to the private bucket defined in settings.
    Generates presigned URLs for access.
    """
    bucket_name = settings.SUPABASE_BUCKET_NAME
    default_acl = 'private'
    file_overwrite = False
    custom_domain = False  # Must be False to generate presigned URLs