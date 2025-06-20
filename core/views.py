from django.http import JsonResponse
from django.db import connection

def db_test(request):
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT version();")
            row = cursor.fetchone()
        return JsonResponse({"status": "success", "version": row[0]})
    except Exception as e:
        return JsonResponse({"status": "error", "message": str(e)})