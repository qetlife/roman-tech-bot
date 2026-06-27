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
RUN useradd --create-home appuser \
    && chown -R appuser:appuser /app
USER appuser

CMD ["python", "bot.py"]
