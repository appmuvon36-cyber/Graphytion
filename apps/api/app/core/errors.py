from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
async def http_error_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content={"error":{"code":"HTTP_ERROR","message":str(exc.detail),"request_id":getattr(request.state,"request_id","unknown")}})
async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(status_code=500, content={"error":{"code":"INTERNAL_ERROR","message":"An unexpected error occurred.","request_id":getattr(request.state,"request_id","unknown")}})
