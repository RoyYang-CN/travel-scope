"""International Google Places classification and price semantics."""
from __future__ import annotations

LODGING_TOKENS = (
    "hotel", "resort", "villa", "hostel", "homestay", "guesthouse",
    "guest house", "lodge", "inn", "retreat", "bungalow", "apartment"
)
FOOD_TOKENS = ("restaurant", "cafe", "bar", "warung", "kitchen", "bakery", "grill", "food")
FACILITY_TOKENS = ("harbor", "port", "station", "terminal", "parking", "management", "visitor center")
ACTIVITY_TOKENS = ("snorkel", "diving", "dive", "tour", "trip", "watching", "cruise", "boat")

def _text(place: dict) -> str:
    return str(place.get("displayName", {}).get("text", "")).strip().lower()

def _types(place: dict) -> set[str]:
    return {str(x).lower() for x in (place.get("types") or [])}

def is_valid_poi_kind(place: dict, kind: str) -> bool:
    text = _text(place)
    types = _types(place)
    lodging = bool(types & {"lodging", "hotel", "resort_hotel", "guest_house", "hostel"}) or any(t in text for t in LODGING_TOKENS)
    food = bool(types & {"restaurant", "cafe", "bar", "meal_takeaway", "meal_delivery"}) or any(t in text for t in FOOD_TOKENS)
    facility = any(t in text for t in FACILITY_TOKENS)
    if kind == "hotel":
        return lodging and not facility
    if kind == "restaurant":
        return food and not lodging and not facility
    if kind == "attraction":
        return not lodging and not food and not facility
    return True

def attraction_price(place: dict) -> str:
    """Do not invent a universal ticket range from a Google rating result."""
    text = _text(place)
    if any(t in text for t in ACTIVITY_TOKENS):
        return "活动价格待出发前核验"
    if any(t in text for t in ("temple", "park", "waterfall", "beach", "forest", "market", "ridge", "terrace", "island", "cliff", "cave", "museum", "palace", "point")):
        return "门票/现场规则待出发前核验"
    return "价格待出发前核验"
