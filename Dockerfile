FROM python:3.12-slim

RUN apt-get update \
  && apt-get install -y --no-install-recommends ffmpeg ca-certificates \
  && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY poll-position/ ./poll-position/

ENV DATA_DIR=/data \
    HOST=0.0.0.0 \
    PORT=8787 \
    SYNC_INTERVAL_SECONDS=3600 \
    PYTHONUNBUFFERED=1

VOLUME ["/data"]
EXPOSE 8787

WORKDIR /app/poll-position
CMD ["python", "server.py"]
