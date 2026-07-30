"""API-key-gated Telegram Mini App and browser OIDC authentication."""

from __future__ import annotations

import base64
import asyncio
import hashlib
import hmac
import json
import secrets
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from urllib.parse import parse_qsl, urlencode

import httpx
import jwt
from fastapi import Cookie, Header, HTTPException, Response
from fastapi.responses import RedirectResponse
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from config import (
    APP_BASE_URL,
    APP_API_KEY,
    API_KEY_ALIAS,
    AUTH_MAX_AGE,
    SESSION_COOKIE_SECURE,
    SESSION_SECRET,
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_OIDC_CLIENT_ID,
    TELEGRAM_OIDC_CLIENT_SECRET,
)
from db.supabase_client import ensure_user

SESSION_COOKIE = "rates_session"
OIDC_COOKIE = "rates_oidc"
API_KEY_COOKIE = "rates_api_key"
ACCESS_TOKEN_TTL = timedelta(hours=12)
OIDC_ISSUER = "https://oauth.telegram.org"
OIDC_AUTH_URL = f"{OIDC_ISSUER}/auth"
OIDC_TOKEN_URL = f"{OIDC_ISSUER}/token"
OIDC_JWKS_URL = f"{OIDC_ISSUER}/.well-known/jwks.json"

serializer = URLSafeTimedSerializer(SESSION_SECRET, salt="rates-session")
oidc_serializer = URLSafeTimedSerializer(SESSION_SECRET, salt="rates-oidc")
api_key_serializer = URLSafeTimedSerializer(SESSION_SECRET, salt="rates-api-key")


@dataclass(frozen=True)
class AuthUser:
    telegram_id: int
    username: str = ""
    first_name: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "telegramId": self.telegram_id,
            "username": self.username,
            "firstName": self.first_name,
        }


def validate_mini_app_data(init_data: str, max_age: int = AUTH_MAX_AGE) -> AuthUser:
    """Validate Telegram initData using the documented HMAC construction."""
    pairs = dict(parse_qsl(init_data, keep_blank_values=True))
    received_hash = pairs.pop("hash", "")
    if not received_hash:
        raise HTTPException(status_code=401, detail="Telegram гарын үсэг байхгүй")

    data_check = "\n".join(f"{key}={pairs[key]}" for key in sorted(pairs))
    secret = hmac.new(
        b"WebAppData", TELEGRAM_BOT_TOKEN.encode(), hashlib.sha256
    ).digest()
    expected = hmac.new(secret, data_check.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, received_hash):
        raise HTTPException(status_code=401, detail="Telegram гарын үсэг буруу")

    try:
        auth_date = int(pairs["auth_date"])
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=401, detail="Нэвтрэх хугацаа буруу") from exc
    now = int(time.time())
    if auth_date > now + 30 or now - auth_date > max_age:
        raise HTTPException(status_code=401, detail="Нэвтрэх хүсэлтийн хугацаа дууссан")

    try:
        user_data = json.loads(pairs["user"])
        telegram_id = int(user_data["id"])
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=401, detail="Telegram хэрэглэгч олдсонгүй") from exc
    return AuthUser(
        telegram_id=telegram_id,
        username=str(user_data.get("username") or ""),
        first_name=str(user_data.get("first_name") or ""),
    )


def _set_session(response: Response, user: AuthUser) -> None:
    token = serializer.dumps(
        {
            "auth": "api-key",
            "telegram_id": user.telegram_id,
            "username": user.username,
            "first_name": user.first_name,
        }
    )
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=60 * 60 * 12,
        httponly=True,
        secure=SESSION_COOKIE_SECURE,
        samesite="lax",
        path="/",
    )


def validate_api_key(api_key: str) -> None:
    """Validate the shared app key without leaking it in logs or responses."""
    configured_keys = tuple(key for key in (APP_API_KEY, API_KEY_ALIAS) if key)
    if not configured_keys:
        raise HTTPException(status_code=503, detail="APP_API_KEY тохируулаагүй")
    submitted_key = api_key.strip() if api_key else ""
    if not submitted_key or not any(
        hmac.compare_digest(submitted_key, configured_key)
        for configured_key in configured_keys
    ):
        raise HTTPException(status_code=401, detail="API key буруу")


def establish_session(response: Response, user: AuthUser) -> AuthUser:
    ensure_user(user.telegram_id, user.username)
    _set_session(response, user)
    return user


def establish_api_key_login(response: Response, api_key: str) -> None:
    """Authorize the browser for the subsequent Telegram OIDC redirect."""
    validate_api_key(api_key)
    response.set_cookie(
        API_KEY_COOKIE,
        api_key_serializer.dumps({"authorized": True}),
        max_age=600,
        httponly=True,
        secure=SESSION_COOKIE_SECURE,
        samesite="lax",
        path="/",
    )


def _has_api_key_login(cookie: Optional[str]) -> bool:
    if not cookie:
        return False
    try:
        return bool(api_key_serializer.loads(cookie, max_age=600).get("authorized"))
    except (BadSignature, SignatureExpired, AttributeError):
        return False


def issue_access_token(user: AuthUser) -> str:
    """Issue a short-lived bearer token after Telegram initData validation.

    Mini App webviews do not always retain first-party cookies consistently.
    The frontend keeps this token in memory only; it is never put in local
    storage or a query string.
    """
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {
            "sub": str(user.telegram_id),
            "auth": "api-key",
            "username": user.username,
            "first_name": user.first_name,
            "iss": "oyuns-rates",
            "iat": now,
            "exp": now + ACCESS_TOKEN_TTL,
        },
        SESSION_SECRET,
        algorithm="HS256",
    )


def _user_from_access_token(token: str) -> AuthUser:
    try:
        payload = jwt.decode(
            token,
            SESSION_SECRET,
            algorithms=["HS256"],
            issuer="oyuns-rates",
        )
        if payload.get("auth") != "api-key":
            raise jwt.InvalidTokenError("API key authentication required")
        return AuthUser(
            telegram_id=int(payload["sub"]),
            username=str(payload.get("username") or ""),
            first_name=str(payload.get("first_name") or ""),
        )
    except (jwt.InvalidTokenError, KeyError, TypeError, ValueError) as exc:
        raise HTTPException(status_code=401, detail="Нэвтрэх токен буруу") from exc


def current_user(
    rates_session: Optional[str] = Cookie(default=None, alias=SESSION_COOKIE),
    authorization: Optional[str] = Header(default=None),
) -> AuthUser:
    if authorization:
        scheme, _, token = authorization.partition(" ")
        if scheme.lower() != "bearer" or not token:
            raise HTTPException(status_code=401, detail="Нэвтрэх токен буруу")
        user = _user_from_access_token(token)
    else:
        if not rates_session:
            raise HTTPException(status_code=401, detail="Нэвтэрнэ үү")
        try:
            payload = serializer.loads(rates_session, max_age=60 * 60 * 12)
            if payload.get("auth") != "api-key":
                raise BadSignature("API key authentication required")
            user = AuthUser(
                telegram_id=int(payload["telegram_id"]),
                username=str(payload.get("username") or ""),
                first_name=str(payload.get("first_name") or ""),
            )
        except (BadSignature, SignatureExpired, KeyError, ValueError) as exc:
            raise HTTPException(status_code=401, detail="Нэвтрэх хугацаа дууссан") from exc
    return user


def oidc_login_response(api_key_cookie: Optional[str]) -> RedirectResponse:
    if not _has_api_key_login(api_key_cookie):
        raise HTTPException(status_code=401, detail="Эхлээд API key оруулна уу")
    if not TELEGRAM_OIDC_CLIENT_SECRET:
        raise HTTPException(status_code=503, detail="Telegram web login тохируулаагүй")
    if not APP_BASE_URL.startswith("https://"):
        raise HTTPException(
            status_code=503,
            detail="APP_BASE_URL нь production HTTPS URL байх ёстой",
        )
    state = secrets.token_urlsafe(24)
    verifier = secrets.token_urlsafe(48)
    nonce = secrets.token_urlsafe(24)
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()
    ).rstrip(b"=").decode()
    redirect_uri = f"{APP_BASE_URL}/api/auth/telegram/callback"
    query = urlencode(
        {
            "client_id": TELEGRAM_OIDC_CLIENT_ID,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": "openid profile",
            "state": state,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "nonce": nonce,
        }
    )
    response = RedirectResponse(f"{OIDC_AUTH_URL}?{query}", status_code=302)
    response.set_cookie(
        OIDC_COOKIE,
        oidc_serializer.dumps(
            {"state": state, "verifier": verifier, "nonce": nonce}
        ),
        max_age=600,
        httponly=True,
        secure=SESSION_COOKIE_SECURE,
        samesite="lax",
        path="/api/auth/telegram/callback",
    )
    return response


async def oidc_callback_response(
    code: str,
    state_value: str,
    oidc_cookie: Optional[str],
    api_key_cookie: Optional[str],
) -> RedirectResponse:
    if not _has_api_key_login(api_key_cookie):
        raise HTTPException(status_code=401, detail="API key хугацаа дууссан")
    if not oidc_cookie:
        raise HTTPException(status_code=401, detail="OIDC төлөв олдсонгүй")
    try:
        pending = oidc_serializer.loads(oidc_cookie, max_age=600)
    except (BadSignature, SignatureExpired) as exc:
        raise HTTPException(status_code=401, detail="OIDC хугацаа дууссан") from exc
    if not hmac.compare_digest(str(pending.get("state", "")), state_value):
        raise HTTPException(status_code=401, detail="OIDC төлөв буруу")

    redirect_uri = f"{APP_BASE_URL}/api/auth/telegram/callback"
    async with httpx.AsyncClient(timeout=15) as client:
        token_response = await client.post(
            OIDC_TOKEN_URL,
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": redirect_uri,
                "client_id": TELEGRAM_OIDC_CLIENT_ID,
                "code_verifier": pending["verifier"],
            },
            auth=(TELEGRAM_OIDC_CLIENT_ID, TELEGRAM_OIDC_CLIENT_SECRET),
        )
        token_response.raise_for_status()
        id_token = token_response.json()["id_token"]

    signing_key = await asyncio.to_thread(
        jwt.PyJWKClient(OIDC_JWKS_URL).get_signing_key_from_jwt, id_token
    )
    claims = jwt.decode(
        id_token,
        signing_key.key,
        algorithms=["RS256"],
        audience=TELEGRAM_OIDC_CLIENT_ID,
        issuer=OIDC_ISSUER,
    )
    if not hmac.compare_digest(
        str(claims.get("nonce", "")), str(pending.get("nonce", ""))
    ):
        raise HTTPException(status_code=401, detail="OIDC nonce буруу")
    telegram_id = int(claims.get("id") or claims["sub"])
    user = AuthUser(
        telegram_id=telegram_id,
        username=str(claims.get("preferred_username") or claims.get("username") or ""),
        first_name=str(claims.get("given_name") or claims.get("name") or ""),
    )
    response = RedirectResponse("/", status_code=302)
    establish_session(response, user)
    response.delete_cookie(OIDC_COOKIE, path="/api/auth/telegram/callback")
    response.delete_cookie(API_KEY_COOKIE, path="/")
    return response
