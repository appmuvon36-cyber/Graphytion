from typing import Annotated, Any
from fastapi import Depends, Header, HTTPException, status
from app.core.security import verify_access_token
async def current_claims(authorization: Annotated[str | None, Header()] = None) -> dict[str, Any]:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Bearer token required")
    return verify_access_token(authorization.removeprefix("Bearer ").strip())
AuthenticatedClaims = Annotated[dict[str, Any], Depends(current_claims)]
def require_workspace_role(*allowed_roles: str):
    async def dependency(claims: AuthenticatedClaims) -> dict[str, Any]:
        if not claims.get("sub"):
            raise HTTPException(status_code=401, detail="Authenticated subject required")
        # Role decisions must use persisted membership; never trust user_metadata claims.
        claims["_required_workspace_roles"] = list(allowed_roles)
        return claims
    return dependency
