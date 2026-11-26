# Graphytion FastAPI

Install with Python 3.12: `pip install .`. Start with `uvicorn app.main:app --reload --port 8000`. OpenAPI: `/openapi.json`; docs: `/docs`; liveness: `/api/v1/health`.

The API owns business rules and privileged provider access. Database and Redis clients use server-only environment configuration. This phase adds migration tooling but does not apply migrations or create production schema. Workspace membership persistence and domain CRUD are later phases.
