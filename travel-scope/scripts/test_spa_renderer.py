import json
import tempfile
import unittest
from pathlib import Path

from spa_renderer import render_spa_document

class SpaRendererTests(unittest.TestCase):
    def test_render_spa_document_contains_contract_and_dataset(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            out = Path(tmpdir) / "test.html"
            dummy_data = {
                "country": "印度尼西亚",
                "country_en": "Indonesia",
                "routes": [["巴厘文化海岸深度线", "Bali Culture", "登巴萨→乌布", "12天11晚", "Grab", "¥9885", "简介"]],
                "destinations": [["乌布", "Ubud"]],
                "itinerary": [["巴厘文化海岸深度线", "Day 1", 1, "交通", "登巴萨→乌布", "-8.74,115.16"]],
                "hotels": [],
                "restaurants": [],
                "cafes": [],
                "attractions": [],
                "dive_sites": [],
                "transport": [],
                "transport_nodes": [],
                "budget": [["1", "2月4日", "抵达", "450", "150", "100", "30", "30", "760"]],
                "route_budgets": {"巴厘文化海岸深度线": 9885},
                "practical": [],
                "worth_it": [],
                "local_chains": [],
                "packing": [],
                "local_knowledge": [],
                "local_apps": [],
                "source_evidence": [],
                "editorial_media": [],
                "section_media": []
            }
            render_spa_document(out, dummy_data)
            self.assertTrue(out.is_file())
            content = out.read_text(encoding="utf-8")
            self.assertIn('<meta name="travel-scope-renderer" content="travel-scope-spa-v1">', content)
            self.assertIn('<script id="dataset" type="application/json">', content)
            self.assertIn('印度尼西亚', content)
            self.assertIn('smart scroll', content.lower())

if __name__ == "__main__":
    unittest.main()
