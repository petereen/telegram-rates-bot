"""Validation and durable storage for global application branding."""

from __future__ import annotations

import io
import logging
import re
import uuid
from typing import Any

from PIL import Image, UnidentifiedImageError

from db.supabase_client import (
    delete_branding_asset,
    get_branding,
    get_branding_path,
    set_branding_path,
    upload_branding_asset,
)

log = logging.getLogger(__name__)
MAX_LOGO_BYTES = 2 * 1024 * 1024
ALLOWED_TYPES = {"image/png", "image/jpeg", "image/webp"}


class BrandingError(ValueError):
    pass


def normalize_logo(content: bytes, content_type: str) -> bytes:
    if content_type not in ALLOWED_TYPES:
        raise BrandingError("PNG, JPEG эсвэл WebP зураг оруулна уу")
    if not content or len(content) > MAX_LOGO_BYTES:
        raise BrandingError("Лого 2 МБ-аас бага байна")
    try:
        with Image.open(io.BytesIO(content)) as source:
            source.verify()
        with Image.open(io.BytesIO(content)) as source:
            source.thumbnail((512, 512), Image.Resampling.LANCZOS)
            has_alpha = source.mode in ("RGBA", "LA") or (
                source.mode == "P" and "transparency" in source.info
            )
            image = source.convert("RGBA" if has_alpha else "RGB")
            output = io.BytesIO()
            image.save(output, "WEBP", quality=90, method=6)
            return output.getvalue()
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise BrandingError("Зургийн файл гэмтсэн эсвэл дэмжигдэхгүй байна") from exc


def replace_logo(
    content: bytes,
    content_type: str,
    *,
    provider: str | None = None,
) -> dict[str, Any]:
    normalized = normalize_logo(content, content_type)
    old_path = get_branding_path(provider)
    prefix = (
        f"sources/{re.sub(r'[^a-z0-9-]+', '-', provider.lower()).strip('-')}"
        if provider
        else "app"
    )
    new_path = f"{prefix}/{uuid.uuid4().hex}.webp"
    upload_branding_asset(new_path, normalized)
    try:
        set_branding_path(new_path, provider)
    except Exception:
        try:
            delete_branding_asset(new_path)
        except Exception:
            log.exception("Could not roll back branding upload %s", new_path)
        raise
    if old_path and old_path != new_path:
        try:
            delete_branding_asset(old_path)
        except Exception:
            log.warning("Could not remove superseded branding asset %s", old_path)
    return get_branding()


def remove_logo(*, provider: str | None = None) -> dict[str, Any]:
    old_path = get_branding_path(provider)
    set_branding_path(None, provider)
    if old_path:
        try:
            delete_branding_asset(old_path)
        except Exception:
            log.warning("Could not remove branding asset %s", old_path)
    return get_branding()
