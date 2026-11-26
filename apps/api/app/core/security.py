from functools import lru_cache
from typing import Any
import jwt
from fastapi import HTTPException, status
from jwt import PyJWKClient
from app.core.config import settings

@lru_cache
def _jwks_client() -> PyJWKClient:
    return PyJWKClient(settings.supabase_jwks_url, cache_keys=True)

def verify_access_token(token: str) -> dict[str, Any]:
    try:
        header = jwt.get_unverified_header(token)
        algorithm = header.get("alg")
        options = {"require": ["exp", "iss", "sub", "aud"]}
        if algorithm == "HS256" and settings.supabase_jwt_secret:
            claims = jwt.decode(token, settings.supabase_jwt_secret, algorithms=["HS256"],
                issuer=settings.supabase_jwt_issuer, audience="authenticated", options=options)
        elif algorithm in {"ES256", "RS256"}:
            signing_key = _jwks_client().get_signing_key_from_jwt(token).key
            claims = jwt.decode(token, signing_key, algorithms=[algorithm],
                issuer=settings.supabase_jwt_issuer, audience="authenticated", options=options)
        else:
            raise ValueError("Unsupported JWT algorithm")
        if not isinstance(claims.get("sub"), str) or claims.get("role") != "authenticated":
            raise ValueError("Invalid authenticated subject or role")
        return claims
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired access token") from exc
