FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg fonts-dejavu \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY config.py brain.py finder.py editor.py delivery.py bot.py ./

ENV DATA_DIR=/data PYTHONUNBUFFERED=1
VOLUME ["/data"]

CMD ["python", "bot.py"]
