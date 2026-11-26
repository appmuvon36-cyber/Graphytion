from dataclasses import dataclass
@dataclass(frozen=True)
class IdempotencyRequest:
    key: str
    workspace_id: str
    operation: str
def validate_idempotency_key(value: str | None) -> str:
    if not value or len(value)<16 or len(value)>128:
        raise ValueError("Idempotency-Key must contain 16-128 characters")
    return value
