"""Offline regression for transport edge/node field alignment."""

from __future__ import annotations

import gen_travel_scope as module


def main() -> None:
    module.TRANSPORT_NODES = [
        {"place": "演示海岸", "name": "演示汽车站", "name_en": "Demo Bus Station", "type": "汽车站", "coords": "39.95,116.40", "source_status": "verified"},
        {"place": "演示海岸", "name": "演示港口", "name_en": "Demo Port", "type": "港口", "coords": "39.94,116.39", "source_status": "verified"},
        {"place": "演示岛", "name": "演示岛港口", "name_en": "Demo Island Port", "type": "港口", "coords": "39.64,116.85", "source_status": "verified"},
    ]
    module.TRANSPORT = [[
        "演示海岸→演示岛", "渡轮", "Demo Operator", "100-200", "2h", "每天2班",
        "39.95,116.40", "39.64,116.85", "提前确认海况", "80km", "是", "verified",
        "演示港口", "演示岛港口", "否", "夜间不建议出发",
        "published_reference", "2026年9月", "September 2026", "2026-09-11",
        "https://operator.example/timetable", "https://operator.example/book", "08:00|14:00", "10:00|16:00",
    ]]
    nodes = module.transport_nodes_for_edge("演示海岸→演示岛")
    assert [node["name"] for node in nodes] == ["演示港口", "演示岛港口"]
    assert len(module.TRANSPORT[0]) == 24
    assert not module.validate_transport_mode_contract(domestic=False, travel_mode="非自驾")
    print("transport contract tests passed")


if __name__ == "__main__":
    main()
