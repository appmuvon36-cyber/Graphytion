import json
from pathlib import Path
from app.main import app
output = Path(__file__).resolve().parents[3] / "docs" / "api" / "openapi.json"
output.parent.mkdir(parents=True, exist_ok=True)
output.write_text(json.dumps(app.openapi(), indent=2) + "\n", encoding="utf-8")
print(f"OpenAPI schema written to {output}")
