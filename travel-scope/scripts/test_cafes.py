"""Offline regression for café inclusion and omitted-search detection."""
import copy
import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
import openpyxl
import gen_travel_scope as gen
from cafe_contract import validate_cafes


class CafeTests(unittest.TestCase):
    def payload(self, domestic=False):
        row = ['Demo City', '示例咖啡馆', 'Demo Cafe', 'Coffee', '30', 'Google:4.5', '10',
               '39.9,116.4' if domestic else '10.3,123.9', 'https://example.com/cafe-a.png',
               'https://example.com/cafe-b.png', 'Demo address', 'amap-demo' if domestic else '']
        return {'destinations': [['Demo City', 'Demo City']], 'cafes': [row], 'restaurants': [],
                'domestic_destination': domestic, 'google_place_ids': {row[1]: 'demo-place'},
                'cafe_classification': {row[1]: {'primary_role': 'cafe', 'evidence': ['fixture']}},
                'cafe_coverage': [{'destination': 'Demo City', 'status': 'included',
                                   'queries': ['Demo coffee'], 'evidence': ['fixture']}]}

    def test_contract_both_branches(self):
        for domestic in (True, False):
            p = self.payload(domestic)
            validate_cafes(p)
            missing = copy.deepcopy(p)
            del missing['cafes']
            with self.assertRaises(ValueError): validate_cafes(missing)
            duplicate = copy.deepcopy(p)
            duplicate['restaurants'] = duplicate['cafes'][:]
            with self.assertRaises(ValueError): validate_cafes(duplicate)
            empty = copy.deepcopy(p)
            empty['cafes'] = []
            empty['cafe_coverage'][0].update(status='no_reliable_results', reason='No verified candidates')
            validate_cafes(empty)
            empty['cafe_coverage'] = []
            with self.assertRaises(ValueError): validate_cafes(empty)

    def test_outputs_with_and_without_cafes(self):
        with tempfile.TemporaryDirectory() as folder, contextlib.redirect_stdout(io.StringIO()):
            for domestic in (True, False):
                gen.DEMO_MODE = True
                gen.load_demo_fixture(Path(__file__).parent.parent / 'fixtures/demo.json')
                p = self.payload(domestic)
                gen.DOMESTIC_DESTINATION = domestic
                p['cafes'][0][0] = gen.DESTINATIONS[0][0]
                gen.CAFES = p['cafes']
                gen.GOOGLE_PLACE_IDS = p['google_place_ids']
                # Change only the fixture coordinates to exercise provider-specific sheets.
                for row in gen.HOTELS: row[7] = p['cafes'][0][7]
                for lang in ('cn', 'en'):
                    gen.OUTPUT_LANG = lang
                    h, x, m = [Path(folder) / ('guide.' + ext) for ext in ('html', 'xlsx', 'md')]
                    gen.generate_html(h, ['google'] if not domestic else ['amap', 'baidu'])
                    gen.generate_excel(x, False)
                    gen.generate_markdown(m)
                    assert 'Demo Cafe' in h.read_text(encoding='utf-8')
                    assert 'Demo Cafe' in m.read_text(encoding='utf-8')
                    w = openpyxl.load_workbook(x)
                    sheet = w['Cafés' if lang == 'en' else '咖啡馆推荐']
                    assert sheet.cell(2, 3).value == 'Demo Cafe'
                    if not domestic:
                        assert sheet.cell(2, 9).value == p['cafes'][0][8]
                        assert sheet.cell(2, 12).value == 'demo-place'
                    w.close()
                gen.CAFES = []
                gen.generate_excel(x, False)
                w = openpyxl.load_workbook(x)
                assert 'Cafés' not in w.sheetnames
                w.close()


if __name__ == '__main__':
    unittest.main()
