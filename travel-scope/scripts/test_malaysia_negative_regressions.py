# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import sys
import unittest
from unittest.mock import patch
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / 'scripts'
sys.path.insert(0, str(SCRIPTS))

from formal_data_gate import _direct_url, audit as audit_formal_data
from map_contract import audit_map_targets


class MalaysiaRegressionTests(unittest.TestCase):
    def test_sequential_numbered_patterns_rejected(self):
        bad_urls = [
            'https://example.com/dest/my-kuala-lumpur-0001',
            'https://tourism.gov.my/hotels/kl-0001.html',
            'https://visit.malaysia.travel/poi/spot-0012',
            'https://hotel-booking.my/hotel/stay-00005.html',
        ]
        for url in bad_urls:
            self.assertFalse(_direct_url(url), f'v4.0.8 gate must reject sequential numbered URL: {url}')
        
        good_urls = [
            'https://www.shangri-la.com/kualalumpur/shangrila/',
            'https://www.malaysia.travel/explore/batu-caves',
            'https://wlt.gxzf.gov.cn/zwgk/fdzdgknr/ml/gljg/202305/t20230519_2508119.html'
        ]
        for url in good_urls:
            self.assertTrue(_direct_url(url), f'v4.0.8 gate must accept authentic URL: {url}')

    def test_map_landing_verification_required(self):
        data = {
            'hotels': [['吉隆坡', '测试酒店', 'Test Hotel', 'hotel', '', '', '', '3.15,101.71', '', '']],
            'map_targets': {
                '吉隆坡|测试酒店': {
                    'canonical_name': '测试酒店',
                    'destination': '吉隆坡',
                    'country': '马来西亚',
                    'target_level': 'verified_coordinate',
                    'verification_status': 'verified',
                    'coords': '3.15,101.71',
                    'source_url': 'https://example.com/hotels/test',
                    'checked_at': '2026-09-16',
                    'qa_evidence': 'evidence/map_verification.json'
                }
            }
        }
        
        with patch('pathlib.Path.is_file', return_value=True):
            with patch('pathlib.Path.read_text', return_value=json.dumps({
                'targets': {
                    '吉隆坡|测试酒店': {
                        'coords': '3.15,101.71',
                        'status': 'PASS'
                    }
                }
            })):
                errors, _ = audit_map_targets(data, base_dir=Path('/mock'), require_exact=True)
                self.assertTrue(any('缺少第三方实际落地名称' in e for e in errors), f'Expected missing landing error, got: {errors}')

    def test_map_self_cloning_verification_rejected(self):
        # Flaw: copying input name as resolved_name without real platform metadata
        data = {
            'hotels': [['吉隆坡', '测试酒店', 'Test Hotel', 'hotel', '', '', '', '3.15,101.71', '', '']],
            'map_targets': {
                '吉隆坡|测试酒店': {
                    'canonical_name': '测试酒店',
                    'destination': '吉隆坡',
                    'country': '马来西亚',
                    'target_level': 'verified_coordinate',
                    'verification_status': 'verified',
                    'coords': '3.15,101.71',
                    'source_url': 'https://example.com/hotels/test',
                    'checked_at': '2026-09-16',
                    'qa_evidence': 'evidence/map_verification.json'
                }
            }
        }
        with patch('pathlib.Path.is_file', return_value=True):
            with patch('pathlib.Path.read_text', return_value=json.dumps({
                'targets': {
                    '吉隆坡|测试酒店': {
                        'resolved_name': '测试酒店',  # Identical self-clone
                        'resolved_address': '测试地址',
                        'coords': '3.15,101.71',
                        'status': 'PASS'
                    }
                }
            })):
                errors, _ = audit_map_targets(data, base_dir=Path('/mock'), require_exact=True)
                self.assertTrue(any('疑似自体克隆假核验' in e for e in errors), f'Expected self-cloning error, got: {errors}')


if __name__ == '__main__':
    unittest.main()
