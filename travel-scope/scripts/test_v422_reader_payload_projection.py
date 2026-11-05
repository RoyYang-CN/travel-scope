# -*- coding: utf-8 -*-
"""v4.2.2 V6-B：读者载荷投影（map-link-selection.json::reader_payload_projection）的执行型牙齿。

业主窄指令第 4 条要求：reader 不消费 provider 数据时，优先在渲染 payload 中剔除，而不是删审计
记录。V3R 只剔了 per-provider 决策容器；本文件把补全后的口径钉死——

  1. 登记与实现双向核对：种类闭集里有的必须登记，登记了的必须会被执行（否则登记是文档）；
  2. 投影必须按 registered rendered_providers 走，换成只渲染 apple 时被告必须是 google
     （证明没有把 "apple" 写死在代码里）；
  3. 审计面输入必须逐字节不变（剔除只作用于渲染副本）；
  4. 门禁必须能查出泄漏：把 apple_url 塞回读者载荷 → MAP_READER_PAYLOAD_AUDIT_FIELD_LEAK；
  5. marker 里每一项数字必须等于同一份数据现算的测量值（登记过期即 FAIL）。

约定：本文件不写发布树产物，渲染一律落到临时目录。
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

import map_link_selector as mls          # noqa: E402
import spa_renderer as sr                # noqa: E402
import visual_qa as vq                   # noqa: E402

SELECTION = json.loads((ROOT / "references" / "map-link-selection.json").read_text(encoding="utf-8"))
BLOCK = SELECTION["reader_payload_projection"]
BLOCK_FIELD_NAMES = [row["field"] for row in BLOCK["process_record_fields"]]


def utf8(value) -> int:
    return len(json.dumps(value, ensure_ascii=False).encode("utf-8"))


def apple_target(**over):
    """一条 CA 形状的 target：两个 provider 的决策 + legacy URL + 分类判决 + 隔离行 + 隔离链接。"""
    row = {
        "target_id": "t-apple", "entity_type": "named_entity", "category": "hotel",
        "criticality": "STANDARD", "display_name": "Apple Park Visitor Center",
        "names": {"en": "Apple Park Visitor Center", "cn": "苹果公园访客中心"},
        "country_code": "US", "destination_scope": "旧金山",
        "identity_status": "UNVERIFIED", "coordinate_status": "VERIFIED",
        "google_resolution_status": "NOT_OBSERVED", "resolver_used": False, "evidence": [],
        # 读者真正要看的几样：按钮形态、落点 URL、核对提示、名字、坐标、旧档位。
        # V6-P 之后这几条仍然必须留在读者载荷里——剔除面扩大不等于把读者要的东西也剔了。
        "canonical_name": "Apple Park Visitor Center", "coords": "37.3327121,-122.0054121",
        "target_level": "named_search_candidate", "link_mode": "NAMED_SEARCH",
        "map_link_url": "https://www.google.com/maps/search/?api=1&query=Apple%20Park",
        "link_notices": ["AMBIGUOUS_MULTI_RESULT"],
        "google_url": "https://www.google.com/maps/search/?api=1&query=Apple%20Park",
        "apple_url": "https://maps.apple.com/?q=Apple%20Park",
        "isolated_link_url": "https://maps.apple.com/?q=Stale%20Apple%20Link",
        "map_link_by_provider": {
            "google": {"link_mode": "NAMED_SEARCH", "map_link_url":
                       "https://www.google.com/maps/search/?api=1&query=Apple%20Park",
                       "link_selection_version": "v422-link-selection-1"},
            "apple": {"link_mode": "NONE", "map_link_url": "",
                      "link_selection_version": "v422-link-selection-1"},
        },
        "classifier_verdicts": {
            "google_url": {"identity": {"provider": "google", "host": "www.google.com"}},
            "apple_url": {"identity": {"provider": "apple", "host": "maps.apple.com"}},
            "source_url": {"identity": {"provider": "google", "host": "example.com"}},
        },
        "quarantine": [
            {"kind": "apple_url", "reason_code": "PROVIDER_HOSTED_URL_NOT_EVIDENCE",
             "value": "https://maps.apple.com/?q=Old",
             "classifier": {"identity": {"provider": "apple", "host": "maps.apple.com"}}},
            {"kind": "source_url", "reason_code": "SELF_ATTESTATION_SOURCE_URL",
             "value": "https://example.com/self"},
        ],
        # provider-neutral 血缘面：本轮不动，测试要证明它留着
        "migration": {"derivations": {"category": ["ca#/hotels/18"]}},
    }
    row.update(over)
    return row


def ui(rendered=None):
    cfg = SELECTION["ui"]
    return {"selection_version": SELECTION["selection_version"],
            "primary_provider": cfg["primary_provider"],
            "rendered_providers": list(rendered if rendered is not None
                                        else cfg["rendered_providers"]),
            "button_copy": cfg["button_copy"], "notices": cfg["notices"],
            "authority": "references/map-link-selection.json"}


class ProjectionRegisterTests(unittest.TestCase):
    """登记与实现必须双向核对：任何一边单独存在都是假的。"""

    def test_registered_kinds_equal_implemented_kinds(self):
        registered = {row["kind"] for row in BLOCK["audit_only_field_kinds"]}
        self.assertEqual(registered, set(mls.PROJECTION_FIELD_KINDS),
                         "字段种类闭集与登记不一致：多出来的一条不会被执行，"
                         "少掉的那条是渲染器自创的剔除规则")

    def test_every_kind_names_a_provider_placeholder(self):
        for row in BLOCK["audit_only_field_kinds"]:
            self.assertIn("{provider}", row["field"],
                          "字段模式写死 provider 名＝第二套硬编码（V0-L12 单一实现）")
            self.assertIsInstance(row["measured"], dict, "登记必须带实测数字")
            for provider, runs in row["measured"].items():
                self.assertNotIn("{provider}", provider, "provider 名必须是实测出来的键，不是占位符")
                for run, value in runs.items():
                    self.assertIn("utf8_bytes", value, "%s/%s 的实测没有字节数" % (provider, run))
                    self.assertIn("rows", value, "%s/%s 的实测没有行数" % (provider, run))
                    self.assertIsInstance(value["utf8_bytes"], int)

    def test_projection_block_is_required(self):
        cfg = copy.deepcopy(SELECTION)
        cfg.pop("reader_payload_projection")
        path = ROOT / "references" / "_tmp_no_projection_block.json"
        path.write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")
        try:
            with self.assertRaises(mls.SelectionConfigError):
                mls.load_selection(path)
        finally:
            path.unlink()

    def test_unimplemented_registered_kind_blocks(self):
        cfg = copy.deepcopy(SELECTION)
        cfg["reader_payload_projection"]["audit_only_field_kinds"].append(
            {"kind": "secrets_field", "field": "{provider}_secret",
             "measured": {"california_v420": {"rows": 0, "utf8_bytes": 0}}})
        self._assert_broken(cfg, "渲染器不会执行")

    def test_pattern_without_provider_placeholder_blocks(self):
        cfg = copy.deepcopy(SELECTION)
        cfg["reader_payload_projection"]["audit_only_field_kinds"][1]["field"] = "apple_url"
        self._assert_broken(cfg, "占位符")

    def test_unexplained_not_projected_block_blocks(self):
        cfg = copy.deepcopy(SELECTION)
        cfg["reader_payload_projection"]["not_projected"]["why_untouched"] = ""
        self._assert_broken(cfg, "why_untouched")

    def _assert_broken(self, cfg, needle):
        path = ROOT / "references" / "_tmp_broken_projection.json"
        path.write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")
        try:
            with self.assertRaises(mls.SelectionConfigError) as caught:
                mls.load_selection(path)
            self.assertIn(needle, str(caught.exception))
        finally:
            path.unlink()


class ProjectionBehaviourTests(unittest.TestCase):
    def project(self, row, rendered=None):
        adapted = {"map_targets": {"t-apple": copy.deepcopy(row)}}
        marker = sr._project_reader_map_links(adapted, ui(rendered))
        return adapted["map_targets"]["t-apple"], marker

    def test_audit_only_provider_fields_leave_the_reader_payload(self):
        row, marker = self.project(apple_target())
        self.assertNotIn("apple", row["map_link_by_provider"],
                         "读者拿不到的按钮，读者也不该为它的决策付下载字节")
        self.assertNotIn("apple_url", row, "legacy provider URL 仍在读者载荷里")
        # V6-P：classifier_verdicts / quarantine 整字段属于「过程记录」，判决日志与隔离记录
        # 不再按 provider 逐条留——但按 provider 归属的那几条仍然要逐条记账（种类没被架空）。
        self.assertNotIn("classifier_verdicts", row,
                         "分类判决日志渲染器不读，整字段属过程记录（V6-P 登记）")
        self.assertEqual(marker["stripped_fields"]["classifier_verdict_entry"]["apple"]["rows"], 1,
                         "apple 归属的判决行必须仍按 provider 口径记进 marker，不能只算整字段剔除")
        self.assertNotIn("quarantine", row, "隔离记录渲染器不读，整字段属过程记录（V6-P 登记）")
        self.assertEqual(marker["stripped_fields"]["quarantine_provider_rows"]["apple"]["rows"], 1,
                         "隔离行仍按 provider 归属逐条记账：整包剔不等于没分过类")
        self.assertNotIn("isolated_link_url", row,
                         "被隔离的供应商链接留在读者文件里＝源码里躺着一条没人渲染的 URL")

    def test_rendered_provider_face_is_never_touched(self):
        row, _ = self.project(apple_target())
        self.assertIn("google", row["map_link_by_provider"])
        self.assertEqual(row["google_url"], apple_target()["google_url"],
                         "被渲染 provider 的 URL 与决策容器原样留着：投影不是「挑喜欢的删」")
        self.assertEqual(row["identity_status"], "UNVERIFIED",
                         "DOM 八项属性之一的身份维度不许被剔，否则诚实档位就没法渲染")
        # V6-P 的判据是「渲染器读不读」：这些字段两个渲染器都不读，所以进审计面而不进读者载荷。
        for field in ("classifier_verdicts", "migration"):
            self.assertNotIn(field, row, "%s 属登记过的过程记录，必须不在读者载荷里" % field)

    def test_process_records_leave_the_payload_and_are_counted(self):
        """V6-P 的正面牙齿：登记的每一条过程记录都真的被剔，且 marker 记下行数与字节。"""
        row = apple_target(migration={"derivations": {"category": ["ca#/hotels/18"]}},
                           unresolved_fields=["address_status"], policy_version="v422-x",
                           link_builder_version="v422-link-selection-1",
                           link_selection_version="v422-link-selection-1",
                           evaluated_at="2026-10-30T00:00:00Z", lineage_group="lg-1",
                           address_status="UNVERIFIED", selection_signals=["critical_target"],
                           criticality_derivation_reason="keyword:stay",
                           criticality_derived_from_field="category", criticality_source="route",
                           map_query_name_source="names.en", resolver_used=False,
                           # 这两条在 provider 轮里会被逐条记账，字节口径归上面那条测试管；
                           # 这里清空，才能拿「整字段剩余字节」做精确对账。
                           quarantine=[], classifier_verdicts={})
        projected, marker = self.project(row)
        for field in BLOCK_FIELD_NAMES:
            self.assertNotIn(field, projected, "%s 仍在读者载荷里" % field)
            self.assertIn(field, marker["stripped_process_records"],
                          "%s 被剔了却没进 marker：审计看不出读者少下载了什么" % field)
            self.assertEqual(marker["stripped_process_records"][field]["rows"], 1)
        for field in BLOCK_FIELD_NAMES:
            self.assertEqual(marker["stripped_process_records"][field]["utf8_bytes"],
                             utf8({field: row[field]}),
                             "%s 的登记字节必须等于这段字段在 payload 里真占的字节" % field)
        # 读者仍然要看的东西：一个都不许被顺手剔掉
        for field in ("link_mode", "map_link_url", "link_notices", "identity_status",
                      "coordinate_status", "google_resolution_status", "canonical_name",
                      "coords", "target_level", "criticality"):
            self.assertIn(field, row, "fixture 前提：%s 本来是读者字段" % field)

    def test_process_record_register_is_two_way_checked(self):
        registered = {row["field"] for row in BLOCK["process_record_fields"]}
        self.assertEqual(registered, set(mls.PROCESS_RECORD_FIELDS),
                         "过程记录剔除面必须双向核对：登记没实现＝读者照样下载，"
                         "实现没登记＝渲染器自己扩大了剔除面")
        for row in BLOCK["process_record_fields"]:
            self.assertTrue(str(row.get("why_reader_does_not_consume") or "").strip())
            self.assertIn("dataset.json", str(row.get("audit_surface_kept") or ""),
                          "审计面保留位置没写清＝这条剔除无从复核")

    def test_projection_follows_config_not_a_hardcoded_provider(self):
        row, marker = self.project(apple_target(), rendered=["apple"])
        self.assertNotIn("google", row["map_link_by_provider"])
        self.assertNotIn("google_url", row, "登记只渲染 apple 时，被告必须是 google")
        self.assertIn("apple_url", row, "被渲染的那一面必须原样留着，剔除不能变成挑喜欢的删")
        self.assertEqual(marker["stripped_providers"], {"google": 1})
        self.assertEqual(sorted(marker["stripped_fields"]),
                         sorted(["map_link_container_entry", "provider_url_field",
                                 "classifier_verdict_entry"]),
                         "只渲染 apple 时被告是 google；fixture 的隔离行都归属 apple，"
                         "所以 quarantine_provider_rows 这一种本轮不该出现（出现了就是误伤）")

    def test_marker_numbers_equal_a_fresh_measurement_of_the_same_rows(self):
        row = apple_target()
        expected = {
            "map_link_container_entry": {"apple": {
                "apple": row["map_link_by_provider"]["apple"]}},
            "provider_url_field": {"apple": {"apple_url": row["apple_url"]}},
            "classifier_verdict_entry": {"apple": {
                "apple_url": row["classifier_verdicts"]["apple_url"]}},
            "quarantine_provider_rows": {"apple": [row["quarantine"][0]]},
            "isolated_link_url_provider_host": {"apple": {
                "isolated_link_url": row["isolated_link_url"]}},
        }
        _, marker = self.project(row)
        self.assertEqual(set(marker["stripped_fields"]), set(expected),
                         "marker 里出现的种类必须正好是登记里会被执行的那几条")
        for kind, providers in expected.items():
            for provider, value in providers.items():
                bucket = marker["stripped_fields"][kind][provider]
                self.assertEqual(bucket["utf8_bytes"], utf8(value),
                                 "%s/%s 的登记字节与现算不符（口径＝这段字段在 payload 里真占的字节）"
                                 % (kind, provider))
                self.assertEqual(bucket["rows"], 1)
        provider_bytes = sum(b["utf8_bytes"] for providers in marker["stripped_fields"].values()
                             for b in providers.values())
        process_bytes = sum(b["utf8_bytes"]
                            for b in marker["stripped_process_records"].values())
        self.assertEqual(marker["stripped_utf8_bytes"], provider_bytes + process_bytes,
                         "总字节必须同时包含 provider 归属剔除与过程记录剔除，少一类就是假账")

    def test_required_marker_fields_are_present(self):
        _, marker = self.project(apple_target())
        required = json.loads((ROOT / "references" / "data-model.json")
                              .read_text(encoding="utf-8"))[
            "map_link_per_provider_container"]["reader_payload_projection"][
            "marker_fields_required"]
        for field in required:
            self.assertIn(field, marker, "%s 没进 marker，审计看不出剔了什么" % field)

    def test_input_dataset_is_never_mutated(self):
        source = apple_target()
        snapshot = json.dumps(source, sort_keys=True, ensure_ascii=False)
        self.project(source)
        self.assertEqual(json.dumps(source, sort_keys=True, ensure_ascii=False), snapshot,
                         "投影改到了审计面：§3.3 的 per-provider 记录必须一条不少")

    def test_empty_rendered_providers_is_refused(self):
        with self.assertRaises(ValueError):
            sr._project_reader_map_links({"map_targets": {"t": apple_target()}},
                                         ui(rendered=[]))


class GateLeakTests(unittest.TestCase):
    """剔除必须由门禁反向核对，否则「剔了」只是渲染器的一面之词。"""

    def run_gate(self, targets):
        failures, result = [], {}
        vq.check_embedded_map_contract({"map_targets": targets, "demo_mode": True},
                                       failures, result)
        return failures, result

    def clean_projected(self):
        adapted = {"map_targets": {"t-apple": apple_target()}}
        sr._project_reader_map_links(adapted, ui())
        return adapted["map_targets"]

    def test_planted_leak_is_blocked_with_fixed_denominator(self):
        targets = self.clean_projected()
        targets["t-apple"]["apple_url"] = "https://maps.apple.com/?q=Planted"
        targets["t-apple"]["map_link_by_provider"]["apple"] = {"link_mode": "NAMED_SEARCH"}
        failures, result = self.run_gate(targets)
        leak = [item for item in failures if item.startswith("MAP_READER_PAYLOAD_AUDIT_FIELD_LEAK")]
        self.assertEqual(len(leak), 1, "把未渲染 provider 的字段塞回读者载荷，门禁必须报")
        self.assertIn("2 处", leak[0], "报的处数必须等于真泄漏的字段面数，不能只说「有泄漏」")
        self.assertEqual(result["map_reader_payload_leaked_audit_fields"], 2)

    def test_projected_payload_passes_the_leak_check(self):
        failures, result = self.run_gate(self.clean_projected())
        self.assertEqual([item for item in failures
                          if item.startswith("MAP_READER_PAYLOAD_AUDIT_FIELD_LEAK")], [])
        self.assertEqual(result["map_reader_payload_leaked_audit_fields"], 0)
        self.assertEqual(result["map_reader_payload_audit_only_providers"],
                         mls.reader_payload_projection()["audit_only_providers"])

    def test_leak_denominator_is_the_shipped_target_count(self):
        targets = self.clean_projected()
        targets["t-second"] = apple_target(target_id="t-second", target_level="verified_coordinate")
        sr._project_reader_map_links({"map_targets": targets}, ui())
        targets["t-second"]["apple_url"] = "https://maps.apple.com/?q=Second"
        failures, _ = self.run_gate(targets)
        leak = next(item for item in failures
                    if item.startswith("MAP_READER_PAYLOAD_AUDIT_FIELD_LEAK"))
        self.assertIn("2 条 map_targets", leak, "分母必须是这页真带了多少条目标")

    def test_planted_process_record_is_blocked_with_fixed_denominator(self):
        """V6-P 的门禁牙齿：过程记录塞回读者载荷必须被查出，而不是「渲染器说剔了就信」。"""
        targets = self.clean_projected()
        targets["t-apple"]["migration"] = {"derivations": {"category": ["ca#/hotels/18"]}}
        targets["t-apple"]["classifier_verdicts"] = {"google_url": {"identity": {}}}
        failures, result = self.run_gate(targets)
        leak = [item for item in failures
                if item.startswith("MAP_READER_PAYLOAD_PROCESS_RECORD_LEAK")]
        self.assertEqual(len(leak), 1, "读者载荷里躺着过程记录，门禁必须报")
        self.assertIn("2/%d" % len(targets), leak[0],
                      "报的处数与分母必须是「这页真有几条目标」，不能只说「有泄漏」")
        self.assertEqual(result["map_process_record_leaks"], 2)

    def test_projected_payload_passes_the_process_record_check(self):
        failures, result = self.run_gate(self.clean_projected())
        self.assertEqual([item for item in failures
                          if item.startswith("MAP_READER_PAYLOAD_PROCESS_RECORD_LEAK")], [],
                         "投影做对了却仍被过程记录条判失败＝规则没对齐")


class RenderEndToEndTests(unittest.TestCase):
    def test_rendered_artifact_payload_has_no_audit_only_provider_field(self):
        dataset = {"country": "测试国", "country_en": "Testland", "duration_days": 3,
                   "routes": [["测试线路", "3 天", "北部", "a", "b", 1000, "c", "Test Route"]],
                   "route_budgets": {"测试线路": {"total_cny": 1000}},
                   "itinerary": [], "map_targets": {"t-apple": apple_target()}}
        out = Path(tempfile.mkdtemp()) / "v6b_page.html"
        sr.render_spa_document(str(out), dataset, media_delivery_mode="linked")
        html = out.read_text(encoding="utf-8")
        payload = embedded_dataset(html)
        row = payload["map_targets"]["t-apple"]
        self.assertNotIn("apple_url", row)
        self.assertNotIn("apple", row["map_link_by_provider"])
        self.assertEqual(payload["map_link_render_projection"]["stripped_providers"],
                         {"apple": 1})
        self.assertGreater(payload["map_link_render_projection"]["stripped_utf8_bytes"], 0)
        self.assertIn("maps.apple.com", json.dumps(dataset, ensure_ascii=False),
                      "输入审计面本来必须有 Apple 面，否则这条测试什么都没测")


def embedded_dataset(html: str) -> dict:
    match = re.search(r'<script id="dataset"[^>]*>(.*?)</script>', html, re.S)
    if not match:
        raise AssertionError("成品里没有可解析的内嵌 dataset，读者身份无从对账")
    return json.loads(match.group(1))


if __name__ == "__main__":
    unittest.main()
