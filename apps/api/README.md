# Graphytion FastAPI

Install with Python 3.12: `pip install .`. Start with `uvicorn app.main:app --reload --port 8000`. OpenAPI: `/openapi.json`; docs: `/docs`; liveness: `/api/v1/health`.

The API owns business rules and privileged provider access. PostgreSQL is the durable job queue; workers claim jobs through FastAPI using leases and recovery. Database credentials remain server-side. This phase adds migration tooling but does not apply migrations or create production schema. Workspace membership persistence and domain CRUD are later phases.
