"""Regression tests for post-adjustment scope and transport rechecks."""

from adjust_itinerary import validate


def base_payload():
    return {
        "destinations": [["A", "A"] , ["B", "B"]],
        "hotels": [["A", "Hotel A", "Hotel A", "", "", "", "", "1,1", "", "", ""]],
        "restaurants": [["B", "Food B", "Food B", "", "", "", "", "2,2", "", "", ""]],
        "cafes": [], "attractions": [], "dive_sites": [],
        "transport": [["A→B", "bus", "operator", "10", "2h", "daily", "1,1", "2,2", "notes", "100km", "否", "verified", "A station", "B station", "否", ""]],
        "itinerary": [["Route", "Day 1", 1, "酒店", "Hotel A", "1,1"], ["Route", "Day 1", 2, "餐厅", "Food B", "2,2"]],
    }


def main():
    payload = base_payload()
    validate(payload)
    broken = base_payload()
    broken["transport"] = []
    try:
        validate(broken)
    except ValueError as exc:
        assert "缺少交通边" in str(exc)
    else:
        raise AssertionError("missing cross-destination transport was not blocked")
    outside = base_payload()
    outside["destinations"] = [["A", "A"]]
    try:
        validate(outside)
    except ValueError as exc:
        assert "范围外" in str(exc)
    else:
        raise AssertionError("scope expansion was not blocked")
    outside["scope_confirmation"] = {"status": "confirmed"}
    validate(outside)
    print("itinerary adjustment tests passed")


if __name__ == "__main__":
    main()
