import asyncio
from typing import Annotated, Any

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db_session, set_rls_subject
from app.core.security import verify_access_token
from app.services.supabase_auth import supabase_auth


async def current_claims(
    authorization: Annotated[str | None, Header()] = None,
    db: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Bearer token required"
        )
    token = authorization.removeprefix("Bearer ").strip()
    claims = await asyncio.to_thread(verify_access_token, token)
    # Check the live Supabase session as well as JWT claims.
    # This also rejects sessions revoked after token issuance.
    user = await supabase_auth.verify_user(token)
    if str(user.get("id")) != str(claims.get("sub")):
        raise HTTPException(status_code=401, detail="Authenticated identity mismatch")
    await set_rls_subject(db, str(claims["sub"]))
    claims["_access_token"] = token
    return claims


AuthenticatedClaims = Annotated[dict[str, Any], Depends(current_claims)]


def require_workspace_role(*allowed_roles: str):
    async def dependency(claims: AuthenticatedClaims) -> dict[str, Any]:
        if not claims.get("sub"):
            raise HTTPException(status_code=401, detail="Authenticated subject required")
        claims["_required_workspace_roles"] = list(allowed_roles)
        return claims

    return dependency
