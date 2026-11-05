# -*- coding: utf-8 -*-
"""v4.2.2 V6-V：§8.1 那条「dataset/DOM/href/link mode 不一致 = 0」必须真的在读者页上被执行。

为什么这不是重构口味，而是一个真实缺陷（seal-31 候选页实测，
.temp/v422_honest_map/V6_candidate_run/artifacts/v6v_provenance_carry.json）：

  map_gate_v422.applicability() 的开关读 dataset["map_link_selection"]["selection_version"]。
  但 gen_travel_scope.load_demo_fixture() 从不 hydrate 这个键、export_runtime_dataset() 也不输出它，
  所以两棵候选页上的 check_map_dom_dataset_consistency 一律以
  enforced=false / NOT_V422_MIGRATED_NO_SELECTION_PROVENANCE 退出。门禁自己的 follow_up 写着
  「不适用不等于通过」——本轮之前，交付物上没有任何一次比对发生过，而报告里那个数字看起来像通过。

这属于踩过的坑第 3 条的同一类：报 0 之前必须先证明取值面是活的。

约定：本文件不写发布树产物，夹具与渲染一律落到临时目录。
"""
from __future__ import annotations

import copy
import json
import re
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
ROOT = SCRIPTS.parent

import gen_travel_scope as gen           # noqa: E402
import map_gate_v422 as mg422            # noqa: E402
import map_link_selector as mls          # noqa: E402
import spa_renderer as sr                 # noqa: E402
import visual_qa as vq                    # noqa: E402

SELECTION = mls.load_selection()
CURRENT_VERSION = str(SELECTION["selection_version"])
PROVENANCE = {
    "selection_version": CURRENT_VERSION,
    "round": "v4.2.2 V2R",
    "implementation": "scripts/map_link_selector.py::select",
    "providers_decided": ["google", "apple"],
    "reader_primary_provider": "google",
    "targets": 205,
    "w3_resolver_used": False,
    "historical_run_written": False,
}


def google_target(target_id: str, name: str) -> dict:
    """一条最小但完整的 NAMED_SEARCH 目标：读者页只渲染 google 面。"""
    return {
        "target_id": target_id, "entity_type": "named_entity", "category": "attraction",
        "criticality": "STANDARD", "display_name": name,
        "names": {"en": name, "cn": name}, "country_code": "US", "destination_scope": "测试市",
        "identity_status": "UNVERIFIED", "coordinate_status": "VERIFIED",
        "google_resolution_status": "NOT_OBSERVED", "resolver_used": False, "evidence": [],
        "canonical_name": name, "coords": "37.0,-122.0",
        "link_mode": "NAMED_SEARCH",
        "map_link_url": "https://www.google.com/maps/search/?api=1&query=%s" % name.replace(" ", "%20"),
        "google_url": "https://www.google.com/maps/search/?api=1&query=%s" % name.replace(" ", "%20"),
        "link_notices": [],
        "map_link_by_provider": {
            "google": {"link_mode": "NAMED_SEARCH",
                       "map_link_url": "https://www.google.com/maps/search/?api=1&query=%s"
                                       % name.replace(" ", "%20")},
            "apple": {"link_mode": "NAMED_SEARCH",
                      "map_link_url": "https://maps.apple.com/?q=%s" % name.replace(" ", "%20")},
        },
        "policy_version": "v4.2.2", "evaluated_at": "2026-10-31T00:00:00+08:00",
        "lineage_group": "", "link_builder_version": "v4.2.2", "link_selection_version": CURRENT_VERSION,
        "map_query_name_source": "canonical_name", "selection_signals": [],
        "address_status": "UNVERIFIED", "criticality_source": "registered_default",
        "criticality_derivation_reason": "registered_default", "criticality_derived_from_field": "",
    }


def dom_row(target: dict) -> dict:
    """浏览器取值面的形状（MAP_DOM_ROWS_JS 的产物），不是发布代码里的第二套规则。"""
    return {"targetId": target["target_id"], "provider": "google",
            "href": target["map_link_url"], "linkMode": target["link_mode"],
            "text": str(SELECTION["ui"]["button_copy"]["NAMED_SEARCH"]["cn"]),
            "identityStatus": target["identity_status"],
            "coordinateStatus": target["coordinate_status"],
            "resolutionStatus": target["google_resolution_status"],
            "entityType": target["entity_type"], "criticality": target["criticality"]}


class StubPage:
    def __init__(self, rows):
        self.rows = rows

    def evaluate(self, script):
        assert script is vq.MAP_DOM_ROWS_JS, "取值面必须走同一份 JS，测试不另写选择器"
        return self.rows


class GeneratorCarryTests(unittest.TestCase):
    def fixture(self, tmp: Path, block, targets=None) -> Path:
        payload = json.loads((ROOT / "fixtures" / "demo.json").read_text(encoding="utf-8"))
        if block is _SKIP:
            payload.pop("map_link_selection", None)
        else:
            payload["map_link_selection"] = block
        if targets is not None:
            payload["map_targets"] = targets
        path = tmp / "demo_with_provenance.json"
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        return path

    def test_block_from_input_dataset_reaches_the_reader_payload(self):
        with tempfile.TemporaryDirectory() as tmp:
            targets = {"t-1": google_target("t-1", "Apple Park Visitor Center"),
                       "t-2": google_target("t-2", "Chase Center")}
            path = self.fixture(Path(tmp), PROVENANCE, targets=targets)
            gen.load_demo_fixture(str(path))
            out = gen.export_runtime_dataset(output_dir=None, map_platforms=["google", "apple"])
            self.assertEqual(out.get("map_link_selection"), PROVENANCE,
                             "血缘块在生成阶段被丢掉，§8.1 就又在交付物上空转一轮")
            self.assertEqual(out["map_link_selection"]["selection_version"], CURRENT_VERSION,
                             "读者页声明的版本必须等于当前登记版本")
            self.assertEqual(sorted(out["map_targets"]), sorted(targets),
                              "带血缘不许顺手改目标分母：读者页的目标集合必须等于输入的那两个")

    def test_malformed_block_is_rejected_instead_of_dropped(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self.fixture(Path(tmp), ["not", "a", "mapping"])
            with self.assertRaises(ValueError):
                gen.load_demo_fixture(str(path))

    def test_input_without_block_yields_explicit_empty_block(self):
        """v4.2.1 夹具本来就没有本版血缘：载荷里给空对象，让门禁说出「不适用」而不是沉默。"""
        with tempfile.TemporaryDirectory() as tmp:
            path = self.fixture(Path(tmp), _SKIP)
            gen.load_demo_fixture(str(path))
            out = gen.export_runtime_dataset(output_dir=None, map_platforms=["amap"])
            self.assertEqual(out.get("map_link_selection"), {})
            self.assertFalse(mg422.applicability(out, SELECTION)["enforced"])


_SKIP = object()


class ReaderPayloadCarryTests(unittest.TestCase):
    def dataset(self):
        targets = {"t-1": google_target("t-1", "Apple Park Visitor Center")}
        return {"country": "测试国", "country_en": "Testland", "duration_days": 3,
                "routes": [["测试线路", "3 天", "北部", "a", "b", 1000, "c", "Test Route"]],
                "route_budgets": {"测试线路": {"total_cny": 1000}},
                "itinerary": [], "map_targets": targets,
                "map_link_selection": copy.deepcopy(PROVENANCE)}

    def embedded(self, dataset) -> dict:
        out = Path(tempfile.mkdtemp()) / "v6v_page.html"
        sr.render_spa_document(str(out), dataset, media_delivery_mode="linked")
        html = out.read_text(encoding="utf-8")
        match = re.search(r'<script id="dataset"[^>]*>(.*?)</script>', html, re.S)
        self.assertIsNotNone(match, "成品里没有内嵌 dataset，读者身份无从对账")
        return json.loads(match.group(1))

    def test_reader_projection_does_not_strip_the_provenance_block(self):
        payload = self.embedded(self.dataset())
        self.assertEqual(payload["map_link_selection"]["selection_version"], CURRENT_VERSION,
                         "读者载荷的投影把 §8.1 的开关一起剔掉了")
        self.assertNotIn("apple", payload["map_targets"]["t-1"]["map_link_by_provider"],
                         "同一条测试必须同时证明：投影确实在工作，只是不碰血缘")

    def test_carried_block_is_small_and_declares_no_per_target_state(self):
        payload = self.embedded(self.dataset())
        block = payload["map_link_selection"]
        size = len(json.dumps(block, ensure_ascii=False).encode("utf-8"))
        self.assertLess(size, 4096, "血缘块必须是常数级字节；超过 4KB 说明有人把逐 target 决策塞进来了")
        for forbidden in ("map_targets", "identity_status", "google_resolution_status",
                          "target_level", "verification_status"):
            self.assertNotIn(forbidden, json.dumps(block, ensure_ascii=False),
                             "§8.2：搜索链接路径上不许携带任何身份/核验状态，血缘块也不例外")


class ApplicabilitySwitchTests(unittest.TestCase):
    def dataset_with(self, block):
        row = {"t-1": google_target("t-1", "One")}
        return {"map_targets": row, "map_link_selection": block}

    def test_missing_provenance_is_not_applicable_not_passed(self):
        result = mg422.applicability(self.dataset_with({}), SELECTION)
        self.assertFalse(result["enforced"])
        self.assertEqual(result["reason"], "NOT_V422_MIGRATED_NO_SELECTION_PROVENANCE")
        self.assertIn("不适用不等于通过", result["follow_up"],
                      "不适用必须在报告里被写成一句待办，而不是读起来像通过")

    def test_stale_provenance_refuses_to_judge(self):
        result = mg422.applicability(self.dataset_with({"selection_version": "v421-older"}),
                                     SELECTION)
        self.assertFalse(result["enforced"])
        self.assertEqual(result["reason"], "SELECTION_VERSION_MISMATCH",
                         "拿本版规则判上一版数据会造噪声；换个版本声明就想绕过对账也不行")

    def test_current_provenance_turns_the_gate_on(self):
        result = mg422.applicability(self.dataset_with(dict(PROVENANCE)), SELECTION)
        self.assertTrue(result["enforced"])
        self.assertEqual(result["reason"], "DECLARED_CURRENT")


class Section81IsLiveTests(unittest.TestCase):
    """把「带血缘 ⇒ 真的比对」和「不带 ⇒ 什么都没比」同时钉住：这是本轮改动的可观测量。"""

    def run_check(self, dataset, rows):
        failures, result = [], {}
        vq.check_map_dom_dataset_consistency(StubPage(rows), dataset, failures, result)
        return failures, result["map_dom_dataset_consistency"]

    def test_a_button_that_is_not_rendered_is_reported_when_provenance_is_carried(self):
        target = google_target("t-1", "Chase Center")
        dataset = {"map_targets": {"t-1": target}, "map_link_selection": dict(PROVENANCE)}
        failures, node = self.run_check(dataset, [])
        self.assertTrue(node["enforced"])
        self.assertEqual(node["findings_total"], 1)
        self.assertTrue(any(item.startswith("GATE_DOM_HREF_MISSING|Chase Center") or
                            item.startswith("GATE_DOM_HREF_MISSING|t-1") for item in failures),
                        "§8.1 生效后，dataset 有 URL 而 DOM 没按钮必须报出来")

    def test_without_provenance_the_same_page_reports_nothing_and_that_is_the_mask(self):
        target = google_target("t-1", "Chase Center")
        dataset = {"map_targets": {"t-1": target}, "map_link_selection": {}}
        failures, node = self.run_check(dataset, [])
        self.assertFalse(node["enforced"])
        self.assertEqual(failures, [],
                         "这正是本轮之前的状态：同一条缺失因为开关关掉而无人报")

    def test_matching_dom_produces_zero_findings_for_the_right_reason(self):
        target = google_target("t-1", "Chase Center")
        dataset = {"map_targets": {"t-1": target}, "map_link_selection": dict(PROVENANCE)}
        failures, node = self.run_check(dataset, [dom_row(target)])
        self.assertTrue(node["enforced"], "0 必须来自「量过且一致」")
        self.assertEqual(node["dom_rows"], 1)
        self.assertEqual(node["expected_buttons"], 1)
        self.assertEqual(failures, [])


class RegistryClosureTests(unittest.TestCase):
    def block(self):
        return (SELECTION["reader_payload_projection"]
                ["selection_provenance_block_carried"])

    def test_carry_is_registered_with_measured_cost(self):
        row = self.block()
        self.assertEqual(row["block"], "map_link_selection")
        measured = row["measured_2026_10_31"]
        self.assertEqual(measured["utf8_bytes_california"], 994,
                         "读者载荷多带的字节必须实测登记，不登记就成了口头保证")
        self.assertEqual(measured["findings_when_enforced"]["california"], 5,
                         "放行 §8.1 会逼出的 5 条缺口必须写在登记里，而不是等下一轮重新发现")
        self.assertTrue(row["must_not_be_closed_by"], "怎么把它变绿是不允许的，必须写下来")

    def test_registered_carriers_are_the_modules_that_actually_carry_it(self):
        source = (SCRIPTS / "gen_travel_scope.py").read_text(encoding="utf-8")
        self.assertIn('"map_link_selection": MAP_LINK_SELECTION', source,
                      "登记说生成器携带，代码里就必须真有这一行")
        self.assertIn("MAP_LINK_SELECTION = dict(raw_link_selection or {})", source)
        for item in self.block()["carried_by"]:
            self.assertTrue((ROOT / item.split("::")[0]).is_file(), "%s 不存在" % item)


if __name__ == "__main__":
    unittest.main()
