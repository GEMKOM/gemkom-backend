import os
import boto3
from botocore.exceptions import ClientError
from dotenv import load_dotenv

print("--- Supabase Storage Connection Test ---")

# --- 1. Load Environment Variables ---
# This mimics how your settings.py loads the .env file.
load_dotenv()

project_id = os.environ.get('SUPABASE_PROJECT_ID')
bucket_name = os.environ.get('SUPABASE_BUCKET_NAME')
access_key = os.environ.get('SUPABASE_S3_ACCESS_KEY_ID')
secret_key = os.environ.get('SUPABASE_S3_SECRET_ACCESS_KEY')
region = os.environ.get('SUPABASE_REGION')
endpoint_url = f'https://{project_id}.supabase.co/storage/v1/s3' # <-- Added /s3

print(f"Region: {region}")
print(f"Endpoint: {endpoint_url}")
print(f"Bucket: {bucket_name}")
print(f"Access Key ID: {'Set' if access_key else 'Not Set'}")

# --- 2. Create Boto3 S3 Client ---
# We will manually configure it exactly as django-storages should be doing.
try:
    s3_client = boto3.client(
        's3',
        endpoint_url=endpoint_url,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        region_name=region,
    )
    print("\n[SUCCESS] Boto3 client created.")
except Exception as e:
    print(f"\n[ERROR] Failed to create Boto3 client: {e}")
    exit()

# --- 3. Attempt to Upload a Test File ---
file_content = b"This is a test file from the connection script."
object_key = "connection-test/test.txt"

print(f"\nAttempting to upload to object key: '{object_key}'")

try:
    s3_client.put_object(
        Bucket=bucket_name,
        Key=object_key,
        Body=file_content,
        ContentType='text/plain'
    )
    print(f"\n[SUCCESS] File uploaded successfully to bucket '{bucket_name}'.")
    print("Please check your Supabase Storage dashboard to confirm the 'connection-test/test.txt' file exists.")

except ClientError as e:
    error_code = e.response.get("Error", {}).get("Code")
    error_message = e.response.get("Error", {}).get("Message")
    print(f"\n[ERROR] A client error occurred: {e}")
    print(f"      Error Code: {error_code}")
    print(f"      Error Message: {error_message}")
    print("\nThis indicates an issue with your credentials, bucket name, region, or permissions.")

except Exception as e:
    print(f"\n[ERROR] An unexpected error occurred: {e}")