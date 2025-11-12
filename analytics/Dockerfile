FROM python:3.12-slim

# Set working directory
WORKDIR /app

# Copy and install dependencies
COPY analytics/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the app
COPY analytics/ .

# Create a non-root user and set permissions
RUN useradd --create-home --shell /bin/bash app && chown -R app:app /app
USER app

EXPOSE 8000

# Run FastAPI using uvicorn
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
