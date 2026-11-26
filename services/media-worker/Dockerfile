FROM python:3.12-slim
WORKDIR /app
COPY services/media-worker/pyproject.toml ./pyproject.toml
COPY services/media-worker/app ./app
RUN pip install --no-cache-dir .
ENV PYTHONUNBUFFERED=1
CMD ["python","-m","app.main"]
