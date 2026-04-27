FROM python:3.13-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    libportaudio2 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /code

COPY pyproject.toml .
RUN pip install --no-cache-dir .

COPY app/ app/
COPY static/ static/
COPY audio_client/ audio_client/

ENV PYTHONUNBUFFERED=1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
