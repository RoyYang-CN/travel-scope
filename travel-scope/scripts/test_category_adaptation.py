"""Regression tests for adaptive diving and transport classification."""

import gen_travel_scope as gen


def main() -> None:
    original_dives = gen.DIVE_SITES
    original_attractions = gen.ATTRACTIONS
    try:
        gen.DIVE_SITES = [
            ["海岛", "普通海滩", "Ordinary Beach", "海滩", "免费", "Google:4.2", "1,2", "a", "b", "1h", "游泳", "普通景点"],
            ["海岛", "珊瑚潜点", "Coral Dive Site", "水肺潜水", "100", "Google:4.7", "1,2", "a", "b", "3h", "持证", "潜水"],
        ]
        gen.ATTRACTIONS = []
        assert [row[1] for row in gen.effective_dive_sites()] == ["珊瑚潜点"]
        assert [row[1] for row in gen.effective_attractions()] == ["普通海滩"]
        gen.TRANSPORT = [["A→B", "渡轮", "Operator", "100", "2h", "daily", "1,2", "3,4", "提前确认海况", "80km", "是", "verified", "A Port", "B Port", "否", "夜间风险", "on_demand", "2026年9月", "September 2026", "2026-09-14", "https://operator.example/timetable", "https://operator.example/book", "", ""]]
        gen.TRANSPORT_NODES = [
            {"place": "A", "name": "A Port", "name_en": "A Port", "type": "港口", "coords": "1,2", "source_status": "verified"},
            {"place": "B", "name": "B Port", "name_en": "B Port", "type": "港口", "coords": "3,4", "source_status": "verified"},
        ]
        for domestic in (True, False):
            for mode in ("自驾", "非自驾"):
                assert gen.validate_transport_mode_contract(domestic, mode) == []
        print("category adaptation tests passed")
    finally:
        gen.DIVE_SITES = original_dives
        gen.ATTRACTIONS = original_attractions


if __name__ == "__main__":
    main()
