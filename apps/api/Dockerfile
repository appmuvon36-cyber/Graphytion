FROM python:3.12.11-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY pyproject.toml ./
RUN pip install --no-cache-dir .
COPY app ./app
COPY migrations ./migrations
COPY alembic.ini ./
RUN python -m compileall -q app
EXPOSE 8080
CMD ["sh","-c","exec uvicorn app.main:app --host 0.0.0.0 --port \"${PORT:-8080}\""]
