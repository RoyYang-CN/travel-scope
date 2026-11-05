"""Materialize provider media into local, delivery-safe image assets."""

from __future__ import annotations

import hashlib
from pathlib import Path
from urllib.parse import urlsplit

import requests


def asset_name(url: str) -> str:
    identity = f"{urlsplit(str(url)).netloc}{urlsplit(str(url)).path}"
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24]
    return f"{digest}.jpg"


def inspect_image(path: str | Path) -> tuple[str, str, int]:
    """Return (mime type, content sha256, byte size) for a real image file."""
    target = Path(path)
    data = target.read_bytes()
    mime = ""
    if data.startswith(b"\xff\xd8\xff"):
        mime = "image/jpeg"
    elif data.startswith(b"\x89PNG\r\n\x1a\n"):
        mime = "image/png"
    elif data.startswith((b"RIFF",)) and data[8:12] == b"WEBP":
        mime = "image/webp"
    elif data.startswith(b"GIF87a") or data.startswith(b"GIF89a"):
        mime = "image/gif"
    if not mime:
        raise ValueError(f"local asset is not a supported image: {target}")
    return mime, hashlib.sha256(data).hexdigest(), len(data)


def materialize(url: str, assets_dir: str | Path, timeout: int = 45) -> str:
    """Download one verified image once and return a relative asset path."""
    target_dir = Path(assets_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    filename = asset_name(url)
    target = target_dir / filename
    if target.exists() and target.stat().st_size > 0:
        return f"assets/{filename}"
    response = requests.get(url, timeout=timeout, stream=True)
    response.raise_for_status()
    content_type = (response.headers.get("content-type") or "").lower()
    if not content_type.startswith("image/"):
        raise ValueError(f"provider media is not an image: {content_type}")
    with target.open("wb") as handle:
        for chunk in response.iter_content(chunk_size=1024 * 64):
            if chunk:
                handle.write(chunk)
    if target.stat().st_size == 0:
        target.unlink(missing_ok=True)
        raise ValueError("provider media returned an empty file")
    inspect_image(target)
    return f"assets/{filename}"
