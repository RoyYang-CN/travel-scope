"""Deterministic domestic itinerary planner.

The caller supplies route destination plans and structured POI rows. The planner
selects 2-3 attractions, one restaurant and one hotel per day, using quality,
spatial proximity and route-local de-duplication. Opening hours and driving
duration remain advisory inputs and never become silent hard filters here.
"""
from __future__ import annotations

import math
from collections.abc import Iterable
from typing import Any


def _score(row: list[Any], category: str) -> float:
    rating = str(row[12] if len(row) > 12 else "")
    try:
        value = float(rating)
    except (TypeError, ValueError):
        value = 3.2
    completeness = sum(bool(row[i]) for i in range(min(len(row), 11))) / 11
    image = sum(bool(row[i]) for i in (8, 9) if i < len(row)) / 2
    category_bonus = {"attraction": 0.10, "restaurant": 0.05, "hotel": 0.0}.get(category, 0.0)
    return value * 10 + completeness * 2 + image + category_bonus


def _distance(left: str | None, right: str | None) -> float:
    try:
        la, loa = [float(x) for x in str(left).split(",")[:2]]
        lb, lob = [float(x) for x in str(right).split(",")[:2]]
    except (TypeError, ValueError):
        return 999.0
    return math.hypot((la - lb) * 111, (loa - lob) * 102)


def _pick_many(rows: list[list[Any]], destination: str, used: set[str], count: int, coord_index: int, category: str, anchor: str | None = None) -> list[list[Any]]:
    selected: list[list[Any]] = []
    current = anchor
    for _ in range(count):
        candidates = [r for r in rows if str(r[0]) == destination and str(r[1]) not in used]
        if not candidates:
            break
        candidates.sort(key=lambda r: _score(r, category) - (_distance(current, r[coord_index]) * 0.03 if current else 0), reverse=True)
        chosen = candidates[0]
        used.add(str(chosen[1]))
        selected.append(chosen)
        current = str(chosen[coord_index])
    return selected


def build_domestic_itinerary(routes: Iterable[Iterable[Any]], route_plans: dict[str, list[str]], hotels: list[list[Any]], restaurants: list[list[Any]], attractions: list[list[Any]], transport_edges: dict[str, list[list[Any]]] | None = None) -> list[list[Any]]:
    """Return rows: route, day, sequence, category, name, coordinates."""
    output: list[list[Any]] = []
    for route_row in routes:
        route_name = str(list(route_row)[0])
        used_a: set[str] = set()
        used_r: set[str] = set()
        used_h: set[str] = set()
        destinations = route_plans.get(route_name, [])
        for day_number, destination in enumerate(destinations, 1):
            available = sum(1 for row in attractions if str(row[0]) == destination)
            attraction_count = 3 if available >= 3 else 2
            selected = _pick_many(attractions, destination, used_a, attraction_count, 6, "attraction")
            if not selected:
                raise ValueError(f"no attraction candidates for {destination}")
            sequence = 1
            for row in selected:
                output.append([route_name, f"Day {day_number}", sequence, "景点", row[1], row[6]])
                sequence += 1
            restaurant = _pick_many(restaurants, destination, used_r, 1, 7, "restaurant", str(selected[-1][6]))
            hotel = _pick_many(hotels, destination, used_h, 1, 7, "hotel", str(restaurant[0][7] if restaurant else selected[-1][6]))
            if not restaurant or not hotel:
                raise ValueError(f"missing restaurant or hotel candidates for {destination}")
            output.append([route_name, f"Day {day_number}", sequence, "餐厅", restaurant[0][1], restaurant[0][7]])
            output.append([route_name, f"Day {day_number}", sequence + 1, "酒店", hotel[0][1], hotel[0][7]])
            if transport_edges and day_number < len(destinations):
                edge_key = f"{destination}→{destinations[day_number]}"
                edge_rows = transport_edges.get(edge_key, [])
                if edge_rows:
                    edge = edge_rows[0]
                    output.append([route_name, f"Day {day_number}", sequence + 2, "交通", edge[0], edge[6]])
    return output
