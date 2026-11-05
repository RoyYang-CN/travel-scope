# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import re
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / 'scripts'
sys.path.insert(0, str(SCRIPTS))

from formal_data_gate import audit as audit_formal_data
from map_contract import _is_coordinate_query_url, audit_map_targets
from test_formal_data_gate import fixture


class PhilippinesRegressionTests(unittest.TestCase):
    def test_coordinate_query_url_detection(self):
        coord_urls = [
            "https://www.google.com/maps/search/?api=1&query=10.307959,124.020848",
            "https://maps.google.com/?q=10.307959,124.020848",
            "https://www.google.com/maps?ll=10.307959,124.020848",
            "https://maps.apple.com/?q=10.307959,124.020848",
            "https://maps.apple.com/?ll=10.307959,124.020848",
        ]
        for url in coord_urls:
            self.assertTrue(_is_coordinate_query_url(url), f"Should detect coordinate query url: {url}")

        named_urls = [
            "https://www.google.com/maps/place/Shangri-La+Mactan/@10.307959,124.020848,17z/",
            "https://maps.apple.com/?q=Shangri-La+Mactan",
            "https://www.google.com/maps/search/?api=1&query=Bohol+Beach+Club",
        ]
        for url in named_urls:
            self.assertFalse(_is_coordinate_query_url(url), f"Legitimate named place URL should not be flagged: {url}")

    def test_coordinate_query_rejected_as_verified_platform_url(self):
        data = {
            'hotels': [['宿务', '麦克坦香格里拉度假酒店', 'Shangri-La Mactan', 'hotel', '', '', '', '10.307959,124.020848', '', '']],
            'map_targets': {
                '宿务|麦克坦香格里拉度假酒店': {
                    'canonical_name': '麦克坦香格里拉度假酒店',
                    'destination': '宿务',
                    'country': '菲律宾',
                    'target_level': 'verified_platform_url',
                    'verification_status': 'verified',
                    'coords': '10.307959,124.020848',
                    'google_url': 'https://www.google.com/maps/search/?api=1&query=10.307959,124.020848',
                    'source_url': 'https://example.com/hotels/shangrila',
                    'checked_at': '2026-09-17',
                    'qa_evidence': 'evidence/maps.json'
                }
            }
        }
        with patch('pathlib.Path.is_file', return_value=True):
            with patch('pathlib.Path.read_text', return_value=json.dumps({
                'targets': {
                    '宿务|麦克坦香格里拉度假酒店': {
                        'resolved_name': 'Shangri-La Mactan Resort',
                        'resolved_address': 'Punta Engano Road, Lapu-Lapu City',
                        'landing_url': 'https://www.google.com/maps/search/?api=1&query=10.307959,124.020848',
                        'coords': '10.307959,124.020848'
                    }
                }
            })):
                errors, _ = audit_map_targets(data, base_dir=Path('/mock'), require_exact=True)
                self.assertTrue(any("经纬度坐标" in e or "坐标搜索" in e for e in errors), f"Gate must reject coordinate URL as platform_url! Errors: {errors}")

    def test_map_qa_rejects_numeric_coordinate_as_resolved_name(self):
        data = {
            'hotels': [['宿务', '麦克坦香格里拉度假酒店', 'Shangri-La Mactan', 'hotel', '', '', '', '10.307959,124.020848', '', '']],
            'map_targets': {
                '宿务|麦克坦香格里拉度假酒店': {
                    'canonical_name': '麦克坦香格里拉度假酒店',
                    'destination': '宿务',
                    'country': '菲律宾',
                    'target_level': 'verified_coordinate',
                    'verification_status': 'verified',
                    'coords': '10.307959,124.020848',
                    'source_url': 'https://example.com/hotels/shangrila',
                    'checked_at': '2026-09-17',
                    'qa_evidence': 'evidence/maps.json'
                }
            }
        }
        with patch('pathlib.Path.is_file', return_value=True):
            with patch('pathlib.Path.read_text', return_value=json.dumps({
                'targets': {
                    '宿务|麦克坦香格里拉度假酒店': {
                        'resolved_name': '10.307959, 124.020848',
                        'resolved_address': 'Punta Engano Road, Lapu-Lapu City',
                        'coords': '10.307959,124.020848'
                    }
                }
            })):
                errors, _ = audit_map_targets(data, base_dir=Path('/mock'), require_exact=True)
                self.assertTrue(any("resolved_name 为坐标数字" in e for e in errors), f"Gate must reject coordinate numbers as resolved_name! Errors: {errors}")

    def test_spot_spot_and_untranslated_file_rejected(self):
        data, manifest, scope, corridors, assets = fixture()
        data["routes"][0][7] = "12 days 11 Spot Island Exploration"
        result = audit_formal_data(data, manifest, scope, corridors, assets)
        self.assertEqual(result["status"], "FAIL")
        self.assertTrue(any("占位符套话" in e or "days" in e for e in result["errors"]))

    def test_route_corridor_hyphen_delimiters_support(self):
        corridor = "宿务-薄荷岛-锡基霍尔-杜马盖地-宿务"
        nodes = [s.strip() for s in re.split(r"\s*(?:→|->|—|-|>)\s*", corridor) if s.strip()]
        self.assertEqual(len(nodes), 5)
        self.assertEqual(nodes, ["宿务", "薄荷岛", "锡基霍尔", "杜马盖地", "宿务"])


if __name__ == '__main__':
    unittest.main()
