FROM python:3.12.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Build context must be the repository root. Reuse the exact FastAPI domain
# package, contracts, settings, DB access and PostgreSQL claim/lease logic.
COPY apps/api/pyproject.toml ./pyproject.toml
COPY apps/api/app ./app

RUN pip install --no-cache-dir .

CMD ["graphytion-creative-worker"]
