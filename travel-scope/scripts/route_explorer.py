"""Deterministic route-corridor discovery and coverage gate.

The script does not call web or map APIs. Search agents provide candidates,
transport edges and evidence; this module scores and audits the resulting graph.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def _names(items: list[Any]) -> set[str]:
    return {str(x).strip() for x in items if str(x).strip()}


def audit_classic_corridors(classic_corridors: list[dict[str, Any]], selected_corridors: list[dict[str, Any]]) -> dict[str, Any]:
    """Check that discovered mature multi-day corridors were not silently omitted."""
    audits = []
    uncovered = []
    for classic in classic_corridors:
        required_nodes = _names(classic.get("nodes", []))
        matched = [
            str(c.get("corridor_id", ""))
            for c in selected_corridors
            if required_nodes and required_nodes.issubset(_names(c.get("nodes", [])))
        ]
        declared_status = str(classic.get("status", "candidate")).strip().lower()
        explicitly_excluded = declared_status in {"excluded", "排除", "候选但排除"} and bool(classic.get("exclude_reason"))
        if matched:
            status = "covered"
        elif explicitly_excluded:
            status = "excluded"
        else:
            status = "uncovered"
            uncovered.append({
                "classic_corridor_id": classic.get("corridor_id"),
                "name": classic.get("name"),
                "nodes": list(required_nodes),
                "status": classic.get("status", "pending"),
                "reason": classic.get("exclude_reason") or "未被任何候选走廊完整覆盖",
            })
        audits.append({
            **classic,
            "audit_status": status,
            "covered_by": matched,
        })
    return {"audits": audits, "uncovered": uncovered}


def score_corridor(corridor: dict[str, Any], candidates: dict[str, dict[str, Any]], edges: list[dict[str, Any]], days: int) -> dict[str, Any]:
    nodes = [str(x).strip() for x in corridor.get("nodes", []) if str(x).strip()]
    node_set = set(nodes)
    linked = 0
    edge_details = []
    for left, right in zip(nodes, nodes[1:]):
        matches = [e for e in edges if str(e.get("from", "")).strip() == left and str(e.get("to", "")).strip() == right]
        if not matches:
            matches = [e for e in edges if str(e.get("from", "")).strip() == right and str(e.get("to", "")).strip() == left]
        if matches:
            linked += 1
            edge_details.append({"from": left, "to": right, "documented": True, "modes": matches[0].get("modes", [])})
        else:
            edge_details.append({"from": left, "to": right, "documented": False, "modes": []})
    continuity = 100 if len(nodes) <= 1 else round(100 * linked / (len(nodes) - 1), 1)
    gateway_fit = float(corridor.get("gateway_fit", 0.8 if corridor.get("gateway") else 0.5))
    theme_score = min(1.0, len(_names(corridor.get("themes", []))) / 3)
    required_days = float(corridor.get("days", sum(float(candidates.get(n, {}).get("days", 0)) for n in node_set)))
    days_fit = 1.0 if required_days <= days else max(0.0, days / required_days)
    season_fit = max(0.0, min(1.0, 1 - float(corridor.get("season_risk", 0.3))))
    detour_fit = max(0.0, min(1.0, 1 - float(corridor.get("detour_risk", 0.3))))
    score = round(25 * continuity / 100 + 20 * gateway_fit + 15 * theme_score + 15 * days_fit + 15 * season_fit + 10 * detour_fit, 2)
    return {**corridor, "score": score, "required_days": required_days, "edge_audit": edge_details, "continuity": continuity}


def explore(payload: dict[str, Any]) -> dict[str, Any]:
    candidates = {str(c["name"]).strip(): c for c in payload.get("candidates", []) if c.get("name")}
    edges = list(payload.get("edges", []))
    scored = [score_corridor(c, candidates, edges, int(payload.get("days", 1))) for c in payload.get("corridors", [])]
    subcorridors = [score_corridor(c, candidates, edges, int(c.get("typical_days", payload.get("days", 1)))) for c in payload.get("subcorridors", [])]
    scored.sort(key=lambda x: (-float(x["score"]), str(x.get("corridor_id", ""))))
    subcorridors.sort(key=lambda x: (-float(x["score"]), str(x.get("corridor_id", ""))))
    covered: set[str] = set()
    for corridor in scored + subcorridors:
        covered.update(_names(corridor.get("nodes", [])))
    classic_audit = audit_classic_corridors(payload.get("classic_corridors", []), scored + subcorridors)
    uncovered = []
    for name, candidate in candidates.items():
        if name not in covered:
            reason = candidate.get("exclude_reason")
            if reason and str(candidate.get("status", "")).lower() in {"excluded", "排除", "候选但排除"}:
                continue
            uncovered.append({"name": name, "reason": reason or "未进入任何候选走廊", "status": candidate.get("status", "pending")})
    return {
        "schema_version": "1.0",
        "country": payload.get("country"),
        "route_exploration": payload.get("route_exploration", "deep"),
        "corridors": scored,
        "subcorridors": subcorridors,
        "classic_corridors": classic_audit["audits"],
        "coverage": {"candidate_count": len(candidates), "covered_count": len(covered & set(candidates)), "uncovered": uncovered},
        "classic_coverage": {"classic_count": len(classic_audit["audits"]), "uncovered": classic_audit["uncovered"]},
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Score route corridors and enforce candidate coverage")
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--allow-uncovered", action="store_true")
    args = parser.parse_args()
    result = explore(json.loads(args.input.read_text(encoding="utf-8")))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    uncovered = result["coverage"]["uncovered"]
    classic_uncovered = result["classic_coverage"]["uncovered"]
    if (uncovered or classic_uncovered) and not args.allow_uncovered:
        print(json.dumps({"status": "FAIL", "uncovered": uncovered, "classic_uncovered": classic_uncovered}, ensure_ascii=False))
        return 2
    print(json.dumps({"status": "PASS", "corridors": len(result["corridors"]), "subcorridors": len(result["subcorridors"]), **result["coverage"], **result["classic_coverage"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
