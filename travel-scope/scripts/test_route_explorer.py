from __future__ import annotations

import unittest

from route_explorer import explore


def generic_payload():
    return {
        "country": "Country Z",
        "days": 8,
        "candidates": [
            {"name": "Gateway", "days": 2},
            {"name": "Coast", "days": 3},
            {"name": "Highland", "days": 3},
            {"name": "Island", "days": 3},
        ],
        "edges": [
            {"from": "Gateway", "to": "Coast", "modes": ["rail"]},
            {"from": "Coast", "to": "Highland", "modes": ["bus"]},
            {"from": "Gateway", "to": "Highland", "modes": ["rail"]},
            {"from": "Gateway", "to": "Island", "modes": ["ferry"]},
            {"from": "Island", "to": "Coast", "modes": ["ferry"]},
        ],
        "corridors": [
            {"corridor_id": "A", "nodes": ["Gateway", "Coast", "Highland"]},
            {"corridor_id": "B", "nodes": ["Gateway", "Highland"]},
            {"corridor_id": "C", "nodes": ["Gateway", "Island", "Coast"]},
        ],
    }


class RouteExplorerTests(unittest.TestCase):
    def test_generic_country_builds_three_distinct_connected_corridors(self):
        result = explore(generic_payload())
        self.assertEqual(len(result["corridors"]), 3)
        self.assertEqual(len({tuple(row["nodes"]) for row in result["corridors"]}), 3)
        self.assertTrue(all(row["continuity"] == 100 for row in result["corridors"]))
        self.assertEqual(result["coverage"]["uncovered"], [])

    def test_missing_edge_is_visible_instead_of_silently_passing(self):
        payload = generic_payload()
        payload["edges"] = [edge for edge in payload["edges"] if not (edge["from"] == "Gateway" and edge["to"] == "Island")]
        result = explore(payload)
        corridor = next(row for row in result["corridors"] if row["corridor_id"] == "C")
        self.assertLess(corridor["continuity"], 100)
        self.assertTrue(any(not edge["documented"] for edge in corridor["edge_audit"]))


if __name__ == "__main__":
    unittest.main()
