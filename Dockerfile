FROM python:3.12-slim

# Avoid Python writing .pyc files and enable unbuffered logging
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Install dependencies first to leverage Docker layer caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the application source
COPY . .

# Run as a non-root user
# data/errors: the errors file (a volume in docker-compose.yml, so it survives deploys)
RUN useradd --create-home appuser \
    && mkdir -p /app/data/errors \
    && chown -R appuser:appuser /app
USER appuser

CMD ["python", "bot.py"]
