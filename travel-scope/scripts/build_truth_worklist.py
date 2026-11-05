#!/usr/bin/env python3
"""Create deterministic entity/map/source worklists without asserting verification."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from map_contract import target_key


def build(data: dict) -> dict:
    country = str(data.get("country") or "")
    destination_en = {str(row[0]).strip(): str(row[1]).strip() for row in data.get("destinations") or [] if isinstance(row, list) and len(row) > 1}
    targets, evidence = {}, []
    number = 0
    for module, coord_index in (("hotels", 7), ("restaurants", 7), ("cafes", 7), ("attractions", 6), ("dive_sites", 6)):
        for row in data.get(module) or []:
            if not isinstance(row, list) or len(row) < 2:
                continue
            number += 1
            destination, name = str(row[0]).strip(), str(row[1]).strip()
            targets[target_key(destination, name)] = {
                "canonical_name": name, "name_en": str(row[2]).strip() if len(row) > 2 else "",
                "destination": destination, "destination_en": destination_en.get(destination, ""), "country": country,
                "coords": str(row[coord_index]).strip() if len(row) > coord_index else "",
                "entity_type": "named_entity",
                "target_level": "search_candidate", "verification_status": "pending",
                "source_url": "", "checked_at": "", "qa_evidence": "",
            }
            evidence.append({"evidence_id": f"poi-{number:04d}", "destination": destination, "name": name,
                             "module": module, "url": "", "source_provider": "", "evidence_level": "search_candidate",
                             "verification_status": "pending", "checked_at": "", "supports": []})
    for row in data.get("transport_nodes") or []:
        if isinstance(row, dict):
            destination, name, name_en, coords = row.get("place"), row.get("name"), row.get("name_en"), row.get("coords")
        elif isinstance(row, list) and len(row) > 1:
            destination, name, name_en, coords = row[0], row[1], row[2] if len(row) > 2 else "", row[4] if len(row) > 4 else ""
        else:
            continue
        targets[target_key(destination, name)] = {"canonical_name": name, "name_en": name_en, "destination": destination,
                                                   "destination_en": destination_en.get(str(destination).strip(), ""),
                                                   "country": country, "coords": coords, "entity_type": "named_entity",
                                                   "target_level": "search_candidate",
                                                   "verification_status": "pending", "source_url": "", "checked_at": "", "qa_evidence": ""}
    schedules = []
    for index, row in enumerate(data.get("transport") or [], 1):
        if isinstance(row, list) and len(row) > 16 and str(row[16]) in {"exact_date_verified", "published_reference"}:
            schedules.append({"evidence_id": f"schedule-{index:03d}", "destination": "", "name": str(row[0]),
                              "url": str(row[20]) if len(row) > 20 else "", "source_provider": str(row[2]) if len(row) > 2 else "",
                              "evidence_level": "search_candidate", "verification_status": "pending", "checked_at": "",
                              "supports": ["departures", "effective_period"]})
    return {"schema_version": 1, "map_targets": targets, "source_evidence_meta": evidence, "schedule_evidence": schedules,
            "warning": "Templates are pending work items, not verified evidence. Formal gates must fail until reviewed."}


def main() -> int:
    parser = argparse.ArgumentParser(description="Build pending Travel-Scope entity truth worklists")
    parser.add_argument("--data", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    result = build(json.loads(Path(args.data).read_text(encoding="utf-8")))
    Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "PENDING_REVIEW", "map_targets": len(result["map_targets"]), "poi_evidence": len(result["source_evidence_meta"]), "schedules": len(result["schedule_evidence"])}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
