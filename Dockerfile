FROM python:3.11-slim

# Install git
RUN apt-get update && \
    apt-get install -y git && \
    rm -rf /var/lib/apt/lists/*

# Set up working directory
WORKDIR /app

# Copy requirements first to leverage Docker cache
COPY requirements.txt .
RUN pip install -r requirements.txt

# Copy other files
COPY src/download.py .
COPY src/models.txt .

# Set environment variables
ENV MODEL_CACHE_PATH=/workspace/models

# Run the download script
CMD ["python", "download.py"]