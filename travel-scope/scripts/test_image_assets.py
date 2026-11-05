"""Offline regression tests for local image decoding and asset identity."""

from __future__ import annotations

import tempfile
from pathlib import Path

from image_assets import asset_name, inspect_image


def main() -> None:
    with tempfile.TemporaryDirectory() as temp:
        valid = Path(temp) / "valid.jpg"
        valid.write_bytes(b"\xff\xd8\xff" + b"demo-image")
        mime, digest, size = inspect_image(valid)
        assert mime == "image/jpeg"
        assert len(digest) == 64 and size > 0
        invalid = Path(temp) / "invalid.jpg"
        invalid.write_bytes(b"not-an-image")
        try:
            inspect_image(invalid)
        except ValueError:
            pass
        else:
            raise AssertionError("invalid image was accepted")
        assert asset_name("https://example.com/photo/abc?key=secret") == asset_name("https://example.com/photo/abc?key=other")
    print("image asset tests passed")


if __name__ == "__main__":
    main()
