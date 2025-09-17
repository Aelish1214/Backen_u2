
FROM python:3.10-slim
WORKDIR /app
COPY . .
RUN apt-get update && apt-get install -y ffmpeg libsndfile1 && \
    pip install --upgrade pip && \
CMD ["python", "main.py"]

# Base image
FROM python:3.11-slim

# Working directory
WORKDIR /app

# Dependencies copy
COPY requirements.txt .

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy app code
COPY . .

# Command to run your serve.py
CMD ["python", "serve.py"]

FROM python:3.10-slim
WORKDIR /app
COPY . .
RUN apt-get update && apt-get install -y ffmpeg libsndfile1 && \
    pip install --upgrade pip && \
CMD ["python", "main.py"]

