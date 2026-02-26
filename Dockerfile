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

# Collect static files for Whitenoise (SECRET_KEY falls back to placeholder at build time)
RUN python manage.py collectstatic --noinput

# Set PORT for Cloud Run
ENV PORT=8080
EXPOSE 8080

# Start with Gunicorn
CMD ["gunicorn", "--bind", "0.0.0.0:8080", "config.wsgi"]
