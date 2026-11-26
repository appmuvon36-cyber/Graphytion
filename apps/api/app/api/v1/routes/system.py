from datetime import UTC, datetime
from fastapi import APIRouter, Request
router = APIRouter()
@router.get("/contract")
async def contract_info(request: Request) -> dict[str, object]:
    return {"data":{"apiVersion":"v1","contractVersion":"1"},"meta":{"requestId":request.state.request_id,"timestamp":datetime.now(UTC).isoformat()}}
