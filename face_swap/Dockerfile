FROM python:3.13-slim

RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg fonts-dejavu-core curl \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
# OpenCV Model Zoo face models (YuNet: MIT, SFace: Apache 2.0)
RUN FACE_MODELS_DIR=/srv/models bash scripts/fetch_models.sh

ENV FACE_MODELS_DIR=/srv/models \
    WATERMARK_FONT=/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf \
    PYTHONUNBUFFERED=1

CMD ["sh", "-c", "gunicorn wsgi:app --bind 0.0.0.0:${PORT:-8000} --workers 2 --timeout 120"]
