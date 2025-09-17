# --------- Build layer ---------
FROM python:3.11-slim AS build
WORKDIR /app
COPY requirements.txt ./
RUN pip install --upgrade pip && pip wheel --no-cache-dir --no-deps -r requirements.txt -w /wheels


# --------- Runtime layer ---------
FROM python:3.11-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
PYTHONUNBUFFERED=1


# OS deps (ffmpeg/rtc/openssl as needed by aiortc etc.)
RUN apt-get update && apt-get install -y --no-install-recommends \
libgl1 libffi8 libssl3 ffmpeg nginx ca-certificates \
&& rm -rf /var/lib/apt/lists/*


WORKDIR /app
COPY --from=build /wheels /wheels
RUN pip install --no-cache-dir /wheels/*


# Copy your backend
COPY . /app


# Nginx will read this conf from ConfigMap at runtime. Keep a default for local runs.
COPY docker/nginx.conf /etc/nginx/nginx.conf


# Uvicorn listens on 8000; Nginx listens on 80
EXPOSE 80


# Start both processes in the container (only used for local docker run). In k8s we run Nginx as sidecar.
CMD ["bash", "-lc", "uvicorn serve:app --host 0.0.0.0 --port 8000 & nginx -g 'daemon off;' "]