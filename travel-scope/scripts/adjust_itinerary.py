"""Apply explicit itinerary edits to one shared Travel-Scope payload.

The output remains the same payload shape consumed by gen_travel_scope.py, so
HTML, Excel and Markdown are regenerated from one source after an adjustment.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def _coord(value: Any) -> bool:
    try:
        lat, lng = (float(x.strip()) for x in str(value).split(",", 1))
        return -90 <= lat <= 90 and -180 <= lng <= 180
    except (TypeError, ValueError):
        return False


def _rows(payload: dict) -> list[list[Any]]:
    rows = payload.get("itinerary") or []
    if not isinstance(rows, list):
        raise ValueError("itinerary must be a list")
    return rows


def _renumber(rows: list[list[Any]], route: str, day: str) -> None:
    selected = [row for row in rows if str(row[0]) == route and str(row[1]) == day]
    for index, row in enumerate(selected, 1):
        row[2] = index


def _poi_destination_map(payload: dict) -> dict[str, str]:
    mapping = {}
    for key in ("hotels", "restaurants", "cafes", "attractions", "dive_sites"):
        for row in payload.get(key, []) or []:
            if isinstance(row, list) and len(row) > 1:
                mapping[str(row[1]).strip()] = str(row[0]).strip()
    return mapping


def _transport_edges(payload: dict) -> set[tuple[str, str]]:
    edges = set()
    for row in payload.get("transport", []) or []:
        if not isinstance(row, list) or not row:
            continue
        origin, separator, destination = str(row[0]).partition("→")
        if separator:
            edges.add((origin.strip(), destination.strip()))
    return edges


def _recheck_route_logic(payload: dict) -> list[str]:
    """Recheck scope, area transitions and transport evidence after edits."""
    rows = _rows(payload)
    poi_destinations = _poi_destination_map(payload)
    edges = _transport_edges(payload)
    errors = []
    current_scope = {str(row[0]).strip() for row in payload.get("destinations", []) or [] if isinstance(row, list) and row}
    confirmed = payload.get("scope_confirmation")
    scope_confirmed = isinstance(confirmed, dict) and confirmed.get("status") == "confirmed"
    referenced_destinations = set()
    by_route: dict[str, list[list[Any]]] = {}
    for row in rows:
        if len(row) < 6 or str(row[3]).strip() == "交通":
            continue
        name = str(row[4]).strip()
        destination = poi_destinations.get(name)
        if not destination:
            errors.append(f"调整后的点位未在 POI 数据登记: {name}")
            continue
        referenced_destinations.add(destination)
        by_route.setdefault(str(row[0]), []).append(row)
    outside_scope = sorted(referenced_destinations - current_scope) if current_scope else []
    if outside_scope and not scope_confirmed:
        errors.append(f"调整引入已确认范围外目的地，需重新确认范围: {outside_scope}")
    for route, route_rows in by_route.items():
        ordered = sorted(route_rows, key=lambda row: (str(row[1]), int(row[2]) if str(row[2]).isdigit() else 999999))
        previous_destination = None
        for row in ordered:
            destination = poi_destinations.get(str(row[4]).strip())
            if previous_destination and destination != previous_destination:
                if (previous_destination, destination) not in edges and (destination, previous_destination) not in edges:
                    errors.append(f"路线 {route} 的跨目的地调整缺少交通边: {previous_destination}→{destination}")
            previous_destination = destination
    for index, row in enumerate(payload.get("transport", []) or [], 1):
        if isinstance(row, list) and len(row) >= 10 and (not str(row[4]).strip() or not str(row[9]).strip()):
            errors.append(f"交通边 {index} 缺少耗时或距离，无法完成调整后复核")
    return errors


def apply_operation(payload: dict, operation: dict) -> None:
    rows = _rows(payload)
    action = str(operation.get("action", "")).strip().lower()
    route = str(operation.get("route", "")).strip()
    day = str(operation.get("day", "")).strip()
    if action == "add":
        name = str(operation.get("name", "")).strip()
        if not route or not day or not name or not _coord(operation.get("coords")):
            raise ValueError("add requires route, day, name and valid coords")
        rows.append([route, day, 999, operation.get("category", "景点"), name, operation["coords"]])
        _renumber(rows, route, day)
    elif action == "delete":
        name = str(operation.get("name", "")).strip()
        before = len(rows)
        rows[:] = [row for row in rows if not (str(row[0]) == route and str(row[1]) == day and str(row[4]) == name)]
        if len(rows) == before:
            raise ValueError(f"delete target not found: {route}/{day}/{name}")
        _renumber(rows, route, day)
    elif action == "replace":
        old_name = str(operation.get("old_name", "")).strip()
        target = next((row for row in rows if str(row[0]) == route and str(row[1]) == day and str(row[4]) == old_name), None)
        if target is None:
            raise ValueError(f"replace target not found: {route}/{day}/{old_name}")
        target[3] = operation.get("category", target[3])
        target[4] = operation.get("name", target[4])
        target[5] = operation.get("coords", target[5])
        if not _coord(target[5]):
            raise ValueError("replace requires valid coords")
    elif action == "move":
        name = str(operation.get("name", "")).strip()
        target = next((row for row in rows if str(row[0]) == route and str(row[1]) == day and str(row[4]) == name), None)
        target_day = str(operation.get("target_day", "")).strip()
        if target is None or not target_day:
            raise ValueError("move requires an existing name and target_day")
        target[1] = target_day
        _renumber(rows, route, day)
        _renumber(rows, route, target_day)
    elif action == "copy_day":
        source_day = str(operation.get("source_day", "")).strip()
        target_day = str(operation.get("target_day", "")).strip()
        source = [row for row in rows if str(row[0]) == route and str(row[1]) == source_day]
        if not source or not target_day:
            raise ValueError("copy_day requires source_day, target_day and existing source rows")
        rows[:] = [row for row in rows if not (str(row[0]) == route and str(row[1]) == target_day)]
        rows.extend([[row[0], target_day, row[2], row[3], row[4], row[5]] for row in source])
        _renumber(rows, route, target_day)
    else:
        raise ValueError(f"unsupported itinerary action: {action}")


def validate(payload: dict) -> None:
    seen = set()
    for index, row in enumerate(_rows(payload), 1):
        if len(row) < 6:
            raise ValueError(f"itinerary row {index} has fewer than 6 fields")
        key = (str(row[0]), str(row[1]), str(row[4]))
        if key in seen:
            raise ValueError(f"duplicate itinerary point after adjustment: {key}")
        seen.add(key)
        if not _coord(row[5]):
            raise ValueError(f"invalid itinerary coordinate after adjustment: {row[5]}")
    errors = _recheck_route_logic(payload)
    if errors:
        raise ValueError("调整后路线复核失败:\n- " + "\n- ".join(errors[:30]))


def adjustment_request_text(operations: list[dict]) -> str:
    """Create a paste-ready, explicit adjustment request for a later rerun."""
    labels = {
        "add": "增加",
        "delete": "删除",
        "replace": "替换",
        "move": "调整顺序",
        "copy_day": "复制当天行程",
    }
    lines = ["请基于当前已确认的路线范围调整每日行程，并重新检查交通、时间和区域合理性："]
    for operation in operations:
        action = str(operation.get("action", "")).strip().lower()
        route = operation.get("route", "")
        day = operation.get("day", "")
        if action == "add":
            detail = f"第 {day} 天增加 {operation.get('name', '')}（{operation.get('category', '景点')}）"
        elif action == "delete":
            detail = f"第 {day} 天删除 {operation.get('name', '')}"
        elif action == "replace":
            detail = f"第 {day} 天将 {operation.get('old_name', '')} 替换为 {operation.get('name', '')}"
        elif action == "move":
            detail = f"将第 {day} 天的 {operation.get('name', '')} 调整到第 {operation.get('target_day', '')} 天"
        elif action == "copy_day":
            detail = f"将第 {operation.get('source_day', '')} 天复制到第 {operation.get('target_day', '')} 天"
        else:
            detail = json.dumps(operation, ensure_ascii=False)
        lines.append(f"- {labels.get(action, action)}：路线 {route}；{detail}。")
    lines.append("- 保持 HTML、Excel、Markdown 的 CN/EN 输出同步。")
    lines.append("- 若调整改变了路线范围或跨区域顺序，请先提示我重新确认范围。")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Adjust a Travel-Scope itinerary payload")
    parser.add_argument("--input", required=True)
    parser.add_argument("--operations", required=True, help="JSON file containing an array of explicit operations")
    parser.add_argument("--output", required=True)
    parser.add_argument("--request-text", default=None, help="Write a paste-ready adjustment request text file")
    args = parser.parse_args()
    payload = json.loads(Path(args.input).read_text(encoding="utf-8"))
    operations = json.loads(Path(args.operations).read_text(encoding="utf-8"))
    if not isinstance(operations, list):
        raise ValueError("operations must be a JSON array")
    for operation in operations:
        apply_operation(payload, operation)
    validate(payload)
    Path(args.output).write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    request_text = adjustment_request_text(operations)
    if args.request_text:
        Path(args.request_text).write_text(request_text + "\n", encoding="utf-8")
    print(json.dumps({"status": "PASS", "operations": len(operations), "output": args.output,
                      "request_text": args.request_text, "request_preview": request_text}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
