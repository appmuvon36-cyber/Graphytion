FROM python:3.12-slim
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg && rm -rf /var/lib/apt/lists/*
COPY services/media-worker/pyproject.toml ./pyproject.toml
COPY services/media-worker/app ./app
RUN pip install --no-cache-dir . \
    && python -m compileall -q app
ENV PYTHONUNBUFFERED=1
CMD ["python","-m","app.main"]
