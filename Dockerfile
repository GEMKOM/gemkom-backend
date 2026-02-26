# Use official Python image
FROM python:3.11-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Set work directory
WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy project
COPY . .

# Provide a dummy SECRET_KEY for collectstatic — real key is injected at runtime by Cloud Run
RUN SECRET_KEY=build-time-placeholder python manage.py collectstatic --noinput

# Set PORT for Cloud Run
ENV PORT=8080
EXPOSE 8080

# Start with Gunicorn
CMD ["gunicorn", "--bind", "0.0.0.0:8080", "config.wsgi"]
