import os
import re
import unicodedata

from storages.backends.s3boto3 import S3Boto3Storage
from django.conf import settings


def sanitize_filename(filename):
    """
    Sanitize a filename for S3 compatibility.
    Transliterates Turkish/Unicode characters to ASCII equivalents,
    then replaces any remaining non-safe characters with underscores.
    """
    name, ext = os.path.splitext(filename)
    # Transliterate Unicode (e.g. Turkish Ç→C, İ→I, Ş→S, Ğ→G, Ü→U, Ö→O)
    name = unicodedata.normalize('NFKD', name)
    name = name.encode('ascii', 'ignore').decode('ascii')
    # Strip leading special characters
    name = re.sub(r'^[@#$%^&*]+', '', name)
    # Replace anything other than letters, digits, space, dash, underscore, dot
    name = re.sub(r'[^a-zA-Z0-9\s\-._]', '_', name)
    # Collapse whitespace/underscores
    name = re.sub(r'[\s_]+', '_', name)
    name = name.strip('_')
    return f"{name}{ext}"


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