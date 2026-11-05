"""Offline regression tests for the paid-request cache and safety limit."""

from __future__ import annotations

import tempfile
import sqlite3
from pathlib import Path

from api_cache import ApiCache, default_cache_path
from collect_google_images import places_search


class _Response:
    def raise_for_status(self):
        return None

    def json(self):
        return {"places": [{"id": "places/demo"}]}


def main() -> None:
    import os
    configured = os.environ.pop("TRAVEL_SCOPE_CACHE_DB", None)
    try:
        assert default_cache_path("D:/runs/demo/payload.json").name == "travel_scope_cache.sqlite3"
        assert ".travel-scope" in str(default_cache_path("D:/runs/demo/payload.json"))
    finally:
        if configured is not None:
            os.environ["TRAVEL_SCOPE_CACHE_DB"] = configured
    with tempfile.TemporaryDirectory() as temp:
        cache = ApiCache(Path(temp) / "cache.sqlite3")
        calls = {"count": 0}

        import collect_google_images as module

        def fake_post(*_args, **_kwargs):
            calls["count"] += 1
            return _Response()

        original = module.requests.post
        module.requests.post = fake_post
        try:
            first = places_search({}, {"textQuery": "demo"}, cache, '{"textQuery":"demo"}', 1, 1)
            second = places_search({}, {"textQuery": "demo"}, cache, '{"textQuery":"demo"}', 1, 1)
            assert first == second
            assert calls["count"] == 1, "cache miss unexpectedly repeated the paid request"
            try:
                places_search({}, {"textQuery": "other"}, cache, '{"textQuery":"other"}', 1, 1)
            except RuntimeError as exc:
                assert "daily quota safety limit" in str(exc)
            else:
                raise AssertionError("daily safety limit did not stop a second paid request")
            day, month = cache.usage_counts("google_places", "searchText")
            assert day == 1 and month == 1
            cache.record_estimate("run-1", "google_places", "photoMedia", 2)
            cache.put_translation("天气", "Weather")
            assert cache.get_translation("天气") == "Weather"
            connection = sqlite3.connect(Path(temp) / "cache.sqlite3")
            try:
                assert connection.execute("SELECT estimated_calls FROM usage_estimates WHERE run_id='run-1'").fetchone()[0] == 2
            finally:
                connection.close()
            cache.register_asset("assets/demo.jpg", "identity", "demo", "Demo POI", "attractions", "/v1/photos/demo", "verified", "image/jpeg", 3, "hash")
            connection = sqlite3.connect(Path(temp) / "cache.sqlite3")
            try:
                assert connection.execute("SELECT COUNT(*) FROM asset_manifest").fetchone()[0] == 1
                assert connection.execute("SELECT COUNT(*) FROM asset_usage").fetchone()[0] == 1
            finally:
                connection.close()
        finally:
            module.requests.post = original
            cache.close()
    print("api cache tests passed")


if __name__ == "__main__":
    main()
