from datetime import datetime
from typing import Generic, TypeVar
from pydantic import BaseModel, ConfigDict, Field
T = TypeVar("T")
class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
class ResponseMeta(StrictModel):
    request_id: str
    contract_version: str = "1"
    timestamp: datetime
class ApiResponse(BaseModel, Generic[T]):
    data: T
    meta: ResponseMeta
class ApiErrorDetail(StrictModel):
    code: str
    message: str
    request_id: str
    details: dict[str, object] = Field(default_factory=dict)
