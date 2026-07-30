"""HTTP API and production SPA host for the exchange-rates application."""

from __future__ import annotations

import asyncio
import logging
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal, Optional

from fastapi import Depends, FastAPI, File, HTTPException, Query, Request, Response, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from telegram import Bot, InlineQueryResultArticle, InputTextMessageContent
from telegram.constants import ParseMode

from api.auth import (
    OIDC_COOKIE,
    AuthUser,
    current_user,
    establish_session,
    issue_access_token,
    oidc_callback_response,
    oidc_login_response,
    validate_mini_app_data,
)
from config import (
    TELEGRAM_APP_SHORT_NAME,
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_BOT_USERNAME,
)
from db.supabase_client import (
    add_subscription,
    clear_subscriptions,
    create_formula_definition,
    create_share_bundle,
    get_branding,
    get_formula_definitions,
    get_share_bundle,
    get_subscriptions,
    reorder_formula_definitions,
    remove_subscription_by_id,
    soft_delete_formula_definition,
    update_formula_definition,
)
from providers.base import all_providers, get_provider
from providers.registry import register_all_providers
from services.branding import BrandingError, remove_logo, replace_logo
from services.calculator import CalculationError, evaluate_tokens, format_hundredths
from services.rates import (
    FIELD_LABELS,
    RateSnapshot,
    allowed_rate_keys,
    formula_definition_to_dict,
    get_formula_snapshots,
    get_rate_snapshot,
    normalize_formula_definition,
    render_share_html,
    resolve_user_rate_keys,
)

log = logging.getLogger(__name__)
register_all_providers()

app = FastAPI(title="Oyuns Rates", version="1.0.0")
bot = Bot(TELEGRAM_BOT_TOKEN)


class MiniAppLogin(BaseModel):
    init_data: str = Field(alias="initData")


class SubscriptionInput(BaseModel):
    provider: str
    symbol: str


class RefreshInput(BaseModel):
    keys: list[str] = Field(default_factory=list)


class CalculationInput(BaseModel):
    tokens: list[Any]


class ShareInput(BaseModel):
    rate_keys: list[str] = Field(default_factory=list, alias="rateKeys")
    calculation_tokens: Optional[list[Any]] = Field(default=None, alias="calculationTokens")
    calculation_result_mode: Literal["full", "hundredths"] = Field(
        default="full", alias="calculationResultMode"
    )


class FormulaInput(BaseModel):
    title: str
    left: dict[str, Any]
    operator: str
    right: dict[str, Any]
    adjustment_percent: Optional[str] = Field(default=None, alias="adjustmentPercent")
    precision: int = 2
    enabled: bool = True


class FormulaOrderInput(BaseModel):
    ids: list[str]


@app.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/auth/mini-app")
async def mini_app_login(payload: MiniAppLogin, response: Response) -> dict[str, Any]:
    user = await asyncio.to_thread(validate_mini_app_data, payload.init_data)
    user = await asyncio.to_thread(establish_session, response, user)
    return {"user": user.to_dict(), "accessToken": issue_access_token(user)}


@app.get("/api/auth/telegram/start")
async def telegram_login() -> Response:
    return oidc_login_response()


@app.get("/api/auth/telegram/callback")
async def telegram_callback(
    request: Request,
    code: str = Query(...),
    state: str = Query(...),
) -> Response:
    return await oidc_callback_response(
        code, state, request.cookies.get(OIDC_COOKIE)
    )


@app.post("/api/auth/logout")
async def logout(response: Response) -> dict[str, bool]:
    response.delete_cookie("rates_session", path="/")
    return {"ok": True}


@app.get("/api/me")
async def me(user: AuthUser = Depends(current_user)) -> dict[str, Any]:
    return {"user": user.to_dict()}


@app.get("/api/catalog")
async def catalog(user: AuthUser = Depends(current_user)) -> dict[str, Any]:
    subscriptions = await asyncio.to_thread(get_subscriptions, user.telegram_id)
    selected = {(row["provider"], row["symbol"]) for row in subscriptions}
    providers = []
    for name, provider in sorted(all_providers().items()):
        providers.append(
            {
                "name": name,
                "label": provider.DISPLAY_NAME or name,
                "pairs": [
                    {
                        "symbol": symbol,
                        "label": label,
                        "subscribed": (name, symbol) in selected,
                        "formulaFields": [
                            {
                                "key": field,
                                "label": FIELD_LABELS.get(field, field),
                            }
                            for field in provider.formula_fields(symbol)
                        ],
                    }
                    for symbol, label in provider.PAIRS.items()
                ],
            }
        )
    return {"providers": providers}


@app.get("/api/subscriptions")
async def subscriptions(user: AuthUser = Depends(current_user)) -> dict[str, Any]:
    rows = await asyncio.to_thread(get_subscriptions, user.telegram_id)
    return {"subscriptions": rows}


@app.post("/api/subscriptions", status_code=201)
async def subscribe(
    payload: SubscriptionInput, user: AuthUser = Depends(current_user)
) -> dict[str, Any]:
    try:
        provider = get_provider(payload.provider)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Эх сурвалж олдсонгүй") from exc
    if payload.symbol not in provider.PAIRS:
        raise HTTPException(status_code=404, detail="Валютын хослол олдсонгүй")
    await asyncio.to_thread(
        add_subscription, user.telegram_id, payload.provider, payload.symbol
    )
    rows = await asyncio.to_thread(get_subscriptions, user.telegram_id)
    row = next(
        item
        for item in rows
        if item["provider"] == payload.provider and item["symbol"] == payload.symbol
    )
    return {"subscription": row}


@app.delete("/api/subscriptions/{subscription_id}")
async def unsubscribe(
    subscription_id: str, user: AuthUser = Depends(current_user)
) -> dict[str, bool]:
    removed = await asyncio.to_thread(
        remove_subscription_by_id, user.telegram_id, subscription_id
    )
    if not removed:
        raise HTTPException(status_code=404, detail="Хадгалсан ханш олдсонгүй")
    return {"removed": True}


@app.delete("/api/subscriptions")
async def clear_all(user: AuthUser = Depends(current_user)) -> dict[str, int]:
    count = await asyncio.to_thread(clear_subscriptions, user.telegram_id)
    return {"removed": count}


async def _subscription_snapshots(user: AuthUser, force: bool = False) -> list[RateSnapshot]:
    rows = await asyncio.to_thread(get_subscriptions, user.telegram_id)
    results = await asyncio.gather(
        *[
            asyncio.to_thread(
                get_rate_snapshot, row["provider"], row["symbol"], force
            )
            for row in rows
        ],
        return_exceptions=True,
    )
    snapshots: list[RateSnapshot] = []
    for row, result in zip(rows, results):
        if isinstance(result, Exception):
            snapshots.append(
                RateSnapshot(
                    key=f"rate:{row['provider']}:{row['symbol']}",
                    kind="subscription",
                    source=row["provider"],
                    pair=row["symbol"],
                    values=[],
                    fetched_at=datetime.now(timezone.utc).isoformat(),
                    status="error",
                    error="Ханш авахад алдаа гарлаа",
                )
            )
        else:
            snapshots.append(result)
    return snapshots


@app.get("/api/rates")
async def rates(user: AuthUser = Depends(current_user)) -> dict[str, Any]:
    snapshots = await _subscription_snapshots(user)
    return {"rates": [snapshot.to_dict() for snapshot in snapshots]}


@app.get("/api/calculated")
async def calculated(user: AuthUser = Depends(current_user)) -> dict[str, Any]:
    snapshots = await get_formula_snapshots()
    return {"rates": [snapshot.to_dict() for snapshot in snapshots]}


@app.get("/api/formulas")
async def formulas(user: AuthUser = Depends(current_user)) -> dict[str, Any]:
    rows = await asyncio.to_thread(get_formula_definitions)
    return {"formulas": [formula_definition_to_dict(row) for row in rows]}


def _formula_payload(payload: FormulaInput) -> dict[str, Any]:
    try:
        return normalize_formula_definition(payload.model_dump(by_alias=True))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/api/formulas", status_code=201)
async def create_formula(
    payload: FormulaInput, user: AuthUser = Depends(current_user)
) -> dict[str, Any]:
    row = await asyncio.to_thread(create_formula_definition, _formula_payload(payload))
    return {"formula": formula_definition_to_dict(row)}


@app.put("/api/formulas/order")
async def order_formulas(
    payload: FormulaOrderInput, user: AuthUser = Depends(current_user)
) -> dict[str, Any]:
    current = await asyncio.to_thread(get_formula_definitions)
    current_ids = [str(row["id"]) for row in current]
    if len(payload.ids) != len(set(payload.ids)) or set(payload.ids) != set(current_ids):
        raise HTTPException(status_code=422, detail="Томьёоны дараалал буруу")
    rows = await asyncio.to_thread(reorder_formula_definitions, payload.ids)
    return {"formulas": [formula_definition_to_dict(row) for row in rows]}


@app.put("/api/formulas/{formula_id}")
async def update_formula(
    formula_id: str,
    payload: FormulaInput,
    user: AuthUser = Depends(current_user),
) -> dict[str, Any]:
    row = await asyncio.to_thread(
        update_formula_definition, formula_id, _formula_payload(payload)
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Томьёо олдсонгүй")
    return {"formula": formula_definition_to_dict(row)}


@app.delete("/api/formulas/{formula_id}")
async def delete_formula(
    formula_id: str, user: AuthUser = Depends(current_user)
) -> dict[str, bool]:
    removed = await asyncio.to_thread(soft_delete_formula_definition, formula_id)
    if not removed:
        raise HTTPException(status_code=404, detail="Томьёо олдсонгүй")
    return {"removed": True}


@app.get("/api/branding")
async def branding(user: AuthUser = Depends(current_user)) -> dict[str, Any]:
    return await asyncio.to_thread(get_branding)


async def _uploaded_logo(file: UploadFile) -> tuple[bytes, str]:
    content = await file.read(2 * 1024 * 1024 + 1)
    return content, file.content_type or ""


@app.put("/api/branding/app-logo")
async def upload_app_logo(
    file: UploadFile = File(...), user: AuthUser = Depends(current_user)
) -> dict[str, Any]:
    content, content_type = await _uploaded_logo(file)
    try:
        return await asyncio.to_thread(replace_logo, content, content_type)
    except BrandingError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.delete("/api/branding/app-logo")
async def delete_app_logo(user: AuthUser = Depends(current_user)) -> dict[str, Any]:
    return await asyncio.to_thread(remove_logo)


@app.put("/api/branding/sources/{provider}")
async def upload_source_logo(
    provider: str,
    file: UploadFile = File(...),
    user: AuthUser = Depends(current_user),
) -> dict[str, Any]:
    if provider not in all_providers():
        raise HTTPException(status_code=404, detail="Эх сурвалж олдсонгүй")
    content, content_type = await _uploaded_logo(file)
    try:
        return await asyncio.to_thread(
            replace_logo, content, content_type, provider=provider
        )
    except BrandingError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.delete("/api/branding/sources/{provider}")
async def delete_source_logo(
    provider: str, user: AuthUser = Depends(current_user)
) -> dict[str, Any]:
    if provider not in all_providers():
        raise HTTPException(status_code=404, detail="Эх сурвалж олдсонгүй")
    return await asyncio.to_thread(remove_logo, provider=provider)


async def _allowed_keys(user: AuthUser) -> set[str]:
    return await allowed_rate_keys(user.telegram_id)


async def _resolve_keys(
    user: AuthUser, keys: list[str], force: bool = False
) -> list[RateSnapshot]:
    try:
        return await resolve_user_rate_keys(user.telegram_id, keys, force=force)
    except ValueError as exc:
        raise HTTPException(
            status_code=400, detail="Хуваалцах ханшийн сонголт буруу"
        ) from exc


@app.post("/api/rates/refresh")
async def refresh_rates(
    payload: RefreshInput, user: AuthUser = Depends(current_user)
) -> dict[str, Any]:
    keys = payload.keys
    if not keys:
        keys = sorted(await _allowed_keys(user))
    snapshots = await _resolve_keys(user, keys, force=True)
    return {"rates": [snapshot.to_dict() for snapshot in snapshots]}


@app.post("/api/calculate")
async def calculate(
    payload: CalculationInput, user: AuthUser = Depends(current_user)
) -> dict[str, str]:
    try:
        return evaluate_tokens(payload.tokens)
    except CalculationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


async def _share_payload(
    user: AuthUser, payload: dict[str, Any]
) -> tuple[str, list[RateSnapshot], Optional[dict[str, str]]]:
    keys = list(payload.get("rateKeys") or [])
    calculation_tokens = payload.get("calculationTokens")
    calculation = None
    if calculation_tokens:
        try:
            calculation = evaluate_tokens(calculation_tokens)
        except CalculationError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
    if not keys and not calculation:
        raise HTTPException(status_code=400, detail="Хуваалцах зүйл сонгоно уу")
    snapshots = await _resolve_keys(user, keys) if keys else []
    mode = payload.get("calculationResultMode", "full")
    calculation_result = None
    if calculation and mode == "hundredths":
        calculation_result = format_hundredths(calculation["result"])
    html_text = render_share_html(snapshots, calculation, calculation_result)
    if len(html_text) > 4096:
        raise HTTPException(
            status_code=413,
            detail="Сонгосон ханш Telegram мессежийн хэмжээнээс хэтэрлээ",
        )
    return html_text, snapshots, calculation


async def _prepare_message(user: AuthUser, html_text: str) -> str:
    result = InlineQueryResultArticle(
        id=secrets.token_hex(12),
        title="Ханш хуваалцах",
        description="Сонгосон ханшийн мэдээлэл",
        input_message_content=InputTextMessageContent(
            message_text=html_text,
            parse_mode=ParseMode.HTML,
        ),
    )
    prepared = await bot.save_prepared_inline_message(
        user_id=user.telegram_id,
        result=result,
        allow_user_chats=True,
        allow_group_chats=True,
        allow_channel_chats=True,
    )
    return prepared.id


@app.post("/api/shares")
async def create_share(
    payload: ShareInput, user: AuthUser = Depends(current_user)
) -> dict[str, Any]:
    raw_payload = {
        "rateKeys": payload.rate_keys,
        "calculationTokens": payload.calculation_tokens,
        "calculationResultMode": payload.calculation_result_mode,
    }
    html_text, _, _ = await _share_payload(user, raw_payload)
    token = secrets.token_urlsafe(18)
    await asyncio.to_thread(
        create_share_bundle,
        user.telegram_id,
        token,
        raw_payload,
        datetime.now(timezone.utc) + timedelta(minutes=15),
    )
    prepared_id = await _prepare_message(user, html_text)
    handoff_url = None
    if TELEGRAM_BOT_USERNAME and TELEGRAM_APP_SHORT_NAME:
        handoff_url = (
            f"https://t.me/{TELEGRAM_BOT_USERNAME}/{TELEGRAM_APP_SHORT_NAME}"
            f"?startapp=share_{token}"
        )
    return {
        "preparedMessageId": prepared_id,
        "inlineQuery": f"_b:{token}",
        "handoffUrl": handoff_url,
        "inlineFallback": (
            f"https://t.me/{TELEGRAM_BOT_USERNAME}"
            if TELEGRAM_BOT_USERNAME
            else None
        ),
    }


@app.post("/api/shares/{token}/prepare")
async def prepare_bundle(
    token: str, user: AuthUser = Depends(current_user)
) -> dict[str, str]:
    payload = await asyncio.to_thread(get_share_bundle, user.telegram_id, token)
    if payload is None:
        raise HTTPException(status_code=404, detail="Хуваалцах хүсэлтийн хугацаа дууссан")
    html_text, _, _ = await _share_payload(user, payload)
    return {"preparedMessageId": await _prepare_message(user, html_text)}


WEB_DIST = Path(__file__).resolve().parents[1] / "web" / "dist"


@app.get("/{path:path}", include_in_schema=False)
async def spa(path: str) -> Response:
    candidate = (WEB_DIST / path).resolve()
    if path and WEB_DIST in candidate.parents and candidate.is_file():
        return FileResponse(candidate)
    index = WEB_DIST / "index.html"
    if index.is_file():
        return FileResponse(index)
    raise HTTPException(status_code=404, detail="Frontend build олдсонгүй")
