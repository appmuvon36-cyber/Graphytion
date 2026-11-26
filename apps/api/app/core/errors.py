from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

async def http_error_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    message = str(exc.detail) if exc.status_code < 500 else "Request could not be completed."
    return JSONResponse(status_code=exc.status_code, content={"error":{"code":"HTTP_ERROR","message":message,"request_id":getattr(request.state,"request_id","unknown")}})

async def validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    issues = [{"location": [str(part) for part in item.get("loc", [])], "type": item.get("type", "invalid")} for item in exc.errors()]
    return JSONResponse(status_code=422, content={"error":{"code":"VALIDATION_ERROR","message":"Request validation failed.","request_id":getattr(request.state,"request_id","unknown"),"details":{"issues":issues}}})

async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(status_code=500, content={"error":{"code":"INTERNAL_ERROR","message":"An unexpected error occurred.","request_id":getattr(request.state,"request_id","unknown")}})
