"""Regression tests for Live scope and corridor evidence interlock."""

import json
import tempfile
from pathlib import Path

from delivery_gate import _check_scope_evidence


def main() -> None:
    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder)
        scope = root / "scope.json"
        corridors = root / "route_corridors.json"
        manifest = root / "manifest.json"
        scope.write_text(json.dumps({"selected_destinations": [{"name": "A", "status": "正式纳入"}]}), encoding="utf-8")
        corridors.write_text(json.dumps({"corridors": [{"corridor_id": "A"}], "coverage": {"uncovered": []}, "classic_coverage": {"uncovered": []}}), encoding="utf-8")
        manifest.write_text(json.dumps({"completed_stages": ["destination_discovery", "route_exploration", "source_search", "source_audit", "section_media_collection", "section_media_contact_sheet_review", "artifact_generation", "visual_qa", "qa"]}), encoding="utf-8")
        errors = []
        _check_scope_evidence(str(manifest), str(scope), str(corridors), errors)
        assert not errors, errors
        broken = []
        _check_scope_evidence(str(manifest), str(scope), str(root / "missing.json"), broken)
        assert any("路线走廊" in error for error in broken)
    print("delivery evidence tests passed")


if __name__ == "__main__":
    main()
