# -*- coding: utf-8 -*-
"""v4.2.2 V4 — 地图发布门禁与 §9 执行型正反例。

覆盖四件事，每件都必须"咬人"：
1. 严重性登记（谁整批阻断、谁逐项暴露）本身有牙齿：未分级的 code 一律按 blocking 处理。
2. `required_location_role` 按类别适用矩阵判定；角色取值合法性走全局枚举，不由矩阵白名单代劳。
3. 零调用四项来自执行期拦截器：先用一次故意的本机回环证明钩子是活的，再谈 0 有意义。
4. 四种 link mode 的 dataset → renderer → DOM → href 用真实浏览器验，§9 明令不得只扫源码。

夹具与判定共用 `test_v422_map_honest_contract` 的 `target()/decide()/publisher_row()`，
避免同一合同在两个文件里各写一套（那正是本项目反复出问题的形状）。
"""
from __future__ import annotations

import copy
import io
import json
import re
import socket
import tempfile
import unittest
import urllib.request
from pathlib import Path

import map_gate_v422 as gate_mod
import map_link_selector as mls
import spa_renderer as sr
import zero_call_sentinel as sentinel
from test_v422_map_honest_contract import (DATA_MODEL, LOOKUP, POLICY, SELECTION,
                                           decide, publisher_row, target)

ROOT = Path(__file__).resolve().parent.parent
RUNS = ("california_v420", "philippines_v419")
V2R = Path(r"D:/文档/项目开发/Travel-Scope/.temp/v422_honest_map/V2r_migration")
PROVIDERS = sorted(SELECTION["providers"])


def gate():
    return gate_mod.load_gate()


def migrated(rows):
    """给夹具挂上本版血缘——门禁的强制力就靠这个开关识别『这是 v4.2.2 生成的数据』。"""
    return {"map_targets": rows,
            "map_link_selection": {"selection_version": SELECTION["selection_version"]}}


def full_ledger(scope="test window"):
    with sentinel.guarded(scope):
        led = sentinel.ledger({"scope": scope})
    return led


def select_row(row, tid="t-1"):
    """把夹具补成一条**字段完整**的 v4.2.2 行，再跑真实选择机。

    这里补的四项正是 V2R 迁移器写进每一份成品的东西（`policy_version`/`evaluated_at`/
    `classifier_version` 必填、`lineage_group` 显式空、坐标缺失必须写 MISSING 而不是含混状态）。
    不补的话，本文件要测的「严重性分级」会被一堆 `MAP_FIELD_MISSING` 噪声淹没，
    测试结果就分不清是门监理所应当还是夹具没写全。
    """
    merged = dict(row)
    merged.setdefault("target_id", tid)
    merged.setdefault("policy_version", "v4.2.2/data-model.json")
    merged.setdefault("evaluated_at", "2026-10-29T12:00:00+08:00")
    merged.setdefault("classifier_version", "refclassifier-4")
    merged.setdefault("lineage_group", "")
    merged.setdefault("evidence", [])
    if merged.get("lat") in (None, "") and merged.get("lng") in (None, ""):
        if str(merged.get("coordinate_status")) == "UNVERIFIED":
            # 与 V2R 真实行同形：源里有坐标但未经核验 ⇒ 值在场、状态 UNVERIFIED。
            merged["lat"], merged["lng"] = 10.3129, 123.9353
        elif not merged.get("lat"):
            merged["coordinate_status"] = "MISSING"
    merged.update(decide(merged))
    merged["map_link_by_provider"] = mls.select_all_providers(merged["target_id"], merged,
                                                             sel=SELECTION, policy=POLICY,
                                                             lookup=LOOKUP)
    return merged


class GateConfigStrictnessTests(unittest.TestCase):
    """登记文件自己必须是可证伪的：改坏它，加载就报错，而不是安静地少一条规则。"""

    def broken(self, mutate):
        cfg = copy.deepcopy(gate())
        mutate(cfg)
        path = ROOT / "references" / "_tmp_broken_gate.json"
        path.write_bytes(json.dumps(cfg, ensure_ascii=False, indent=2).encode("utf-8"))
        try:
            return gate_mod.load_gate(path)
        finally:
            path.unlink()

    def test_missing_required_key_blocks(self):
        for key in gate_mod.REQUIRED_GATE_KEYS:
            with self.assertRaises(gate_mod.MapGateConfigError, msg=key):
                self.broken(lambda cfg, k=key: cfg.pop(k))

    def test_same_code_cannot_be_both_blocking_and_exposed(self):
        def flip(cfg):
            cfg["classification"]["exposed_exact"].append("MAP_FIELD_NOT_EXPLICIT")
        with self.assertRaises(gate_mod.MapGateConfigError):
            self.broken(flip)

    def test_unclassified_emitted_code_blocks(self):
        """data_model 里能吐出的 code 一旦不在册（删掉登记），加载必须报错。"""
        def drop(cfg):
            cfg["classification"]["exposed_exact"].remove("CRITICAL_NOT_VERIFIED")
            cfg["classification"]["exposed_prefixes"] = []
        with self.assertRaises(gate_mod.MapGateConfigError):
            self.broken(drop)

    def test_dead_registered_code_blocks(self):
        def add_dead(cfg):
            cfg["classification"]["exposed_exact"].append("NOTHING_EVER_EMITS_THIS")
        with self.assertRaises(gate_mod.MapGateConfigError):
            self.broken(add_dead)

    def test_split_code_needs_both_rule_and_membership(self):
        for mutate in (
                lambda cfg: cfg["classification"]["field_split_codes"].pop("MAP_FIELD_MISSING"),
                lambda cfg: cfg["classification"].pop("split_codes")):
            with self.assertRaises(gate_mod.MapGateConfigError):
                self.broken(mutate)

    def test_field_split_must_cover_every_required_field(self):
        def shrink(cfg):
            rule = cfg["classification"]["field_split_codes"]["MAP_FIELD_MISSING"]
            rule["exposed_when_missing_fields"].remove("category")
        with self.assertRaises(gate_mod.MapGateConfigError):
            self.broken(shrink)

    def test_zero_call_gate_cannot_be_softened(self):
        for mutate in (
                lambda cfg: cfg["zero_call_gate"].update(must_all_be_zero=False),
                lambda cfg: cfg["zero_call_gate"].update(evidence_source="source_scan"),
                lambda cfg: cfg["zero_call_gate"].pop("refuse_when_not_armed"),
                lambda cfg: cfg["zero_call_gate"]["required_metrics"].pop(),
                lambda cfg: cfg["zero_call_gate"].update(hard_zero_extra_metrics=[]),
                lambda cfg: cfg["zero_call_gate"]["hard_zero_extra_metrics"].pop()):
            with self.assertRaises(gate_mod.MapGateConfigError):
                self.broken(mutate)


class SeverityClassificationTests(unittest.TestCase):
    def test_missing_field_severity_follows_the_field_not_the_code(self):
        g = gate()
        findings = [
            "MAP_FIELD_MISSING|k|fields=category 缺 §17.2.5 必填字段: ['category']",
            "MAP_FIELD_MISSING|k|fields=identity_status 缺 §17.2.5 必填字段: ['identity_status']",
            "MAP_FIELD_MISSING|k|fields=category,resolver_used 缺 …",
        ]
        split = gate_mod.classify(findings, g)
        self.assertEqual(len(split["exposed"]), 1, split)
        self.assertEqual(len(split["blocking"]), 2, split)
        self.assertEqual(split["unclassified"], [])

    def test_split_code_without_stable_token_is_unclassified_and_blocking(self):
        result = gate_mod.evaluate(migrated({"t-1": select_row(target())}), gate(), SELECTION,
                                   ledger=full_ledger())
        self.assertEqual(result["counts"]["unclassified"], 0, result["blocking"])
        g = gate()
        loose = gate_mod.classify(["MAP_FIELD_MISSING|k 缺 §17.2.5 必填字段: ['category']"], g)
        self.assertEqual(len(loose["unclassified"]), 1,
                         "没有 fields= 稳定片段时不许猜严重性")

    def test_dynamic_prefixed_codes_are_classified(self):
        g = gate()
        split = gate_mod.classify(["IDENTITY_VERIFIED_WITHOUT_POLICY_VERSION|k 缺版本"], g)
        self.assertEqual(len(split["blocking"]), 1, split)

    def test_verdicts_are_three_valued_and_exposures_never_block(self):
        rows = {"t-1": select_row(target())}          # UNVERIFIED + NAMED_SEARCH
        result = gate_mod.evaluate(migrated(rows), gate(), SELECTION, ledger=full_ledger())
        self.assertEqual(result["counts"]["blocking"], 0, result["blocking"])
        self.assertTrue(result["counts"]["exposed"] >= 1)
        self.assertEqual(result["batch_verdict"], "PASS_WITH_EXPOSURES")
        self.assertEqual(result["applicability"]["reason"], "DECLARED_CURRENT")

    def test_absent_ledger_blocks_and_is_not_reported_as_zero(self):
        result = gate_mod.evaluate(migrated({"t-1": select_row(target())}), gate(), SELECTION,
                                   ledger=None)
        self.assertEqual(result["batch_verdict"], "FAIL")
        self.assertTrue(any(item.startswith("GATE_ZERO_CALL_LEDGER_ABSENT|")
                             for item in result["blocking"]))
        self.assertEqual(result["zero_call"]["counts"], {},
                         "没有账本就不许出现任何 0 读数")


class RoleApplicabilityTests(unittest.TestCase):
    """业主指令 §5：酒店不该因为缺航站楼/码头角色而报错，但机场必须说清是哪个航站楼。"""

    def errors(self, **over):
        row = dict(target(category="hotel", required_location_role="RECEPTION"), **over)
        return [item.split("|")[0] for item in
                gate_mod.load_gate() and
                __import__("data_model").validate_map_targets({"t-1": row}, POLICY)]

    def test_hotel_without_role_is_not_an_error(self):
        import data_model
        row = target(category="hotel", required_location_role="", criticality="CRITICAL_ITINERARY")
        found = [item for item in data_model.validate_map_targets({"t-1": row}, POLICY)
                 if "role" in item.lower() or "ROLE" in item.split("|")[0]]
        self.assertEqual(found, [], "酒店缺角色仍被判错——§5 要修的正是这条")

    def test_critical_transport_node_without_role_is_exposed(self):
        import data_model
        row = target(category="transport_node", required_location_role="",
                     criticality="CRITICAL_ITINERARY")
        found = [item for item in data_model.validate_map_targets({"t-1": row}, POLICY)
                 if item.startswith("CRITICAL_ROLE_MISSING")]
        self.assertEqual(len(found), 1, found)
        split = gate_mod.classify(found, gate())
        self.assertEqual((len(split["blocking"]), len(split["exposed"])), (0, 1),
                         "缺角色是局部暴露，不得整批阻断")

    def test_non_critical_transport_node_without_role_is_silent(self):
        import data_model
        row = target(category="transport_node", required_location_role="",
                     criticality="NICE_TO_HAVE")
        self.assertEqual([item for item in
                          data_model.validate_map_targets({"t-1": row}, POLICY)
                          if item.startswith("CRITICAL_ROLE_MISSING")], [])

    def test_unknown_category_is_exposed_not_guessed(self):
        import data_model
        blank = target(category="", required_location_role="")
        hits = [item.split("|")[0] for item in
                data_model.validate_map_targets({"t-1": blank}, POLICY)
                if item.startswith("ROLE_APPLICABILITY")]
        self.assertEqual(hits, ["ROLE_APPLICABILITY_CATEGORY_UNKNOWN"], hits)
        weird = target(category="lighthouse", required_location_role="")
        hits = [item.split("|")[0] for item in
                data_model.validate_map_targets({"t-1": weird}, POLICY)
                if item.startswith("ROLE_APPLICABILITY")]
        self.assertEqual(hits, ["ROLE_APPLICABILITY_CATEGORY_UNREGISTERED"], hits)

    def test_role_value_legality_is_global_enum_not_category_whitelist(self):
        """V4-A 第一版曾用 per-category 白名单，把 11 条「码头里的餐厅/咖啡馆」判成错。"""
        import data_model
        row = target(category="restaurant", required_location_role="PIER",
                     criticality="NICE_TO_HAVE")
        found = [item for item in data_model.validate_map_targets({"t-1": row}, POLICY)
                 if "ROLE_NOT_ALLOWED" in item]
        self.assertEqual(found, [], "类别白名单又回来了")
        bogus = target(category="hotel", required_location_role="SOMETHING_ELSE")
        hits = [item.split("|")[0] for item in
                data_model.validate_map_targets({"t-1": bogus}, POLICY)
                if item.startswith("MAP_ENUM_INVALID")]
        self.assertEqual(hits, ["MAP_ENUM_INVALID"], "非法角色取值必须由全局枚举接住")

    def test_matrix_registry_is_self_consistent_and_covers_real_categories(self):
        matrix = DATA_MODEL["required_location_role_applicability"]
        enum = set(DATA_MODEL["required_location_role"])
        for category, spec in matrix["by_category"].items():
            self.assertTrue(set(spec["typical_roles"]) <= enum | {""}, category)
            self.assertIn(spec["role_required"], (True, False), category)
        # 真实数据里出现过的类别必须都在册（dive_site/dive 两种拼法都登记，V4-A 实测理由）
        for category in ("hotel", "restaurant", "cafe", "attraction", "transport_node",
                         "dive_site", "dive"):
            self.assertIn(category, matrix["by_category"], "%s 没登记适用性" % category)
        self.assertEqual(matrix["by_category"]["transport_node"]["role_required"], True)
        self.assertEqual(matrix["by_category"]["hotel"]["role_required"], False)

    def test_role_field_no_longer_in_unconditional_required_list(self):
        self.assertNotIn("required_location_role", DATA_MODEL["map_target_required_fields"])
        self.assertIn("required_location_role", DATA_MODEL["map_target_conditional_fields"])
        rule = gate()["classification"]["field_split_codes"]["MAP_FIELD_MISSING"]
        all_fields = (set(rule["blocking_when_missing_fields"])
                      | set(rule["exposed_when_missing_fields"]))
        self.assertEqual(set(DATA_MODEL["map_target_required_fields"]) - all_fields, set(),
                         "必填字段里没有严重性分级的，等于给门禁留了第三类")


class ZeroCallSentinelTests(unittest.TestCase):
    """§11 V4：先证明钩子是活的，0 才有意义。"""

    def test_negative_control_proves_the_hooks_fire(self):
        with sentinel.guarded("negative control"):
            try:
                socket.create_connection(("127.0.0.1", 59997), timeout=0.3)
            except OSError:
                pass
            led = sentinel.ledger()
        self.assertTrue(led["armed"], led["interceptors_missing"])
        self.assertGreaterEqual(led["counts"]["network_attempts_total"], 1)
        self.assertGreaterEqual(led["counts"]["local_loopback_attempts"], 1)

    def test_clean_window_reads_zero_without_being_told_to(self):
        led = full_ledger()
        for metric in gate()["zero_call_gate"]["required_metrics"]:
            self.assertEqual(led["counts"][metric], 0, metric)

    def test_host_classification_comes_from_the_register_not_the_code(self):
        body = (ROOT / "scripts" / "zero_call_sentinel.py").read_text(encoding="utf-8")
        rules = gate()["zero_call_gate"]["host_classification"]
        for needle in rules["billable_hosts"] + rules["scrape_hosts"] + rules["paid_fallback_hosts"]:
            self.assertNotIn(needle, body, "%s 写死在哨兵里＝第二套主机判定" % needle)
        self.assertIn("host_classification", body)

    def test_attempt_to_billable_host_is_counted_from_execution(self):
        """一次真实的 HTTP 尝试必须在 http 请求层被分类记账——即便连接根本没建立。

        早先这题把 `HTTPSConnection.request` 换成假函数，结果遮掉了哨兵装在
        `HTTPConnection.request` 上的钩子，账本永远是 0（假阴性）。现在只在**建立传输**那一步
        拦停：既保证真实 urllib 路径完整走到被挂钩的 request()，又不让测试真的往外发包。
        """
        import http.client

        class Blocked(OSError):
            pass

        original_connect = http.client.HTTPConnection.connect

        def blocked(self, *args, **kwargs):
            raise Blocked("测试拦停：不得建立真实连接")
        http.client.HTTPConnection.connect = blocked
        try:
            with sentinel.guarded("billable classification"):
                try:
                    urllib.request.urlopen("https://maps.googleapis.com/maps/api/place/x",
                                           timeout=0.2)
                except Exception:
                    pass
                led = sentinel.ledger()
        finally:
            http.client.HTTPConnection.connect = original_connect
        self.assertGreaterEqual(led["counts"]["google_billable_api_calls"], 1, led["counts"])
        self.assertIn("maps.googleapis.com", led["hosts_seen"], led["hosts_seen"])
        self.assertEqual(led["counts"]["google_api_keys_used"], 0,
                        "没读凭据就不许把 key 使用数记成非 0")

    def test_window_active_prevents_double_arming(self):
        disarm = sentinel.arm()
        try:
            self.assertTrue(sentinel.window_active())
        finally:
            disarm()
        self.assertFalse(sentinel.window_active())

    def test_gate_uses_the_ledger_and_refuses_unarmed_or_nonzero(self):
        g = gate()
        bad = full_ledger()
        bad["counts"]["google_billable_api_calls"] = 3
        self.assertTrue(any("NONZERO" in item for item in
                            gate_mod.zero_call_findings(bad, g)))
        partial = full_ledger()
        partial["interceptors_armed"] = ["socket.connect"]
        partial["armed"] = False
        self.assertTrue(any("NOT_ARMED" in item for item in
                            gate_mod.zero_call_findings(partial, g)))

    def test_external_attempt_is_hard_zero_but_loopback_only_needs_explanation(self):
        """本机回环是真实存在的（浏览器驱动），把它当成违规会逼人作假；不说明才是违规。"""
        g = gate()
        self.assertIn("external_network_attempts", g["zero_call_gate"]["hard_zero_extra_metrics"])
        self.assertNotIn("network_attempts_total", g["zero_call_gate"]["required_metrics"])
        led = full_ledger()
        led["counts"]["network_attempts_total"] = 2
        led["counts"]["local_loopback_attempts"] = 2
        led["counts"]["external_network_attempts"] = 0
        unexplained = gate_mod.zero_call_findings(led, g)
        self.assertTrue(any("LOOPBACK_UNEXPLAINED" in item for item in unexplained), unexplained)
        explained = dict(led, loopback_explanation="Playwright 与本机 Chrome driver 的 CDP 连接")
        self.assertEqual(gate_mod.zero_call_findings(explained, g), [],
                         "回环已经说明、且没有任何非回环尝试——这就是合规账本")
        out_of_process = full_ledger()
        out_of_process["counts"]["external_network_attempts"] = 1
        out_of_process["loopback_explanation"] = "同上"
        self.assertTrue(any(item.startswith("GATE_ZERO_CALL_METRIC_NONZERO|external_network_attempts")
                            for item in gate_mod.zero_call_findings(out_of_process, g)))
        blind = full_ledger()
        blind["counts"].pop("local_loopback_attempts")
        blind["counts"].pop("external_network_attempts")
        self.assertTrue(any("UNMEASURED" in item for item in gate_mod.zero_call_findings(blind, g)),
                        "派生指标没读数就不许当 0 用")


class HardConflictAndConsistencyTests(unittest.TestCase):
    def test_conflict_with_button_is_batch_blocking(self):
        row = select_row(target(identity_status="CONFLICT"))
        row = dict(row, link_mode="NAMED_SEARCH", map_link_url="https://example.invalid/x")
        rows = {"t-1": row}
        result = gate_mod.evaluate(migrated(rows), gate(), SELECTION, ledger=full_ledger())
        self.assertEqual(result["batch_verdict"], "FAIL")
        self.assertTrue(any(item.startswith("GATE_HARD_CONFLICT_HAS_BUTTON|")
                            for item in result["blocking"]), result["blocking"])

    def test_conflict_without_button_is_not_a_gate_failure(self):
        rows = {"t-1": select_row(target(identity_status="CONFLICT"))}
        self.assertEqual(rows["t-1"]["link_mode"], "NONE")
        result = gate_mod.evaluate(migrated(rows), gate(), SELECTION, ledger=full_ledger())
        self.assertFalse([item for item in result["blocking"]
                          if item.startswith("GATE_HARD_CONFLICT_HAS_BUTTON")])

    def test_wrong_entity_and_quarantine_codes_also_block_a_button(self):
        row = dict(select_row(target(google_resolution_status="WRONG_ENTITY")),
                   link_mode="NAMED_SEARCH", map_link_url="https://example.invalid/x")
        blocking = gate_mod.evaluate(migrated({"t-1": row}), gate(), SELECTION,
                                     ledger=full_ledger())["blocking"]
        self.assertTrue(any(item.startswith("GATE_HARD_CONFLICT_HAS_BUTTON") for item in blocking))

    def test_dataset_and_report_must_agree_field_by_field(self):
        rows = {"t-1": select_row(target())}
        report = [{"target_id": "t-1", "provider": "google",
                   "after": dict(rows["t-1"], link_mode="PUBLISHER_ENTITY_LINK")}]
        result = gate_mod.evaluate(migrated(rows), gate(), SELECTION, report_rows=report,
                                   ledger=full_ledger())
        hits = [item for item in result["blocking"]
                if item.startswith("GATE_DATASET_REPORT_DIFFER")]
        self.assertTrue(hits, "dataset 被改成实体链、报告没改，门禁必须看见")
        clean = gate_mod.evaluate(migrated(rows), gate(), SELECTION, report_rows=[
            {"target_id": "t-1", "provider": "google", "after": rows["t-1"]}],
            ledger=full_ledger())
        self.assertFalse([item for item in clean["blocking"]
                          if item.startswith("GATE_DATASET_REPORT_DIFFER")], clean["blocking"])

    def test_report_denominator_is_fixed_and_missing_rows_are_named(self):
        rows = {"t-1": select_row(target()), "t-2": select_row(target(target_id="t-2"))}
        report = [{"target_id": "t-1", "provider": "google", "after": rows["t-1"]}]
        blocking = gate_mod.evaluate(migrated(rows), gate(), SELECTION, report_rows=report,
                                     ledger=full_ledger())["blocking"]
        self.assertTrue(any("GATE_REPORT_DENOMINATOR_MISMATCH" in item for item in blocking))
        self.assertTrue(any("GATE_TARGET_MISSING_FROM_REPORT|t-2" in item for item in blocking))

    def test_audit_and_reader_containers_are_judged_by_different_rules(self):
        rows = {"t-1": select_row(target())}
        audit = gate_mod.evaluate(migrated(rows), gate(), SELECTION, ledger=full_ledger(),
                                  payload_kind="audit")
        self.assertEqual([item for item in audit["blocking"]
                          if "PROVIDER_SET_DIFFERS" in item], [])
        reader = gate_mod.evaluate(migrated(rows), gate(), SELECTION, ledger=full_ledger(),
                                   payload_kind="reader")
        self.assertTrue([item for item in reader["blocking"]
                         if "PROVIDER_SET_DIFFERS" in item],
                        "读者载荷还带着 apple 却没被门禁发现，就是 V3R 投影白做")
        adapted = {"map_targets": copy.deepcopy(rows)}
        sr._project_reader_map_links(adapted, sr._map_link_ui())
        projected = gate_mod.evaluate(migrated(adapted["map_targets"]), gate(), SELECTION,
                                      ledger=full_ledger(), payload_kind="reader")
        self.assertEqual([item for item in projected["blocking"]
                          if "PROVIDER_SET_DIFFERS" in item], [],
                         "投影后的载荷必须被 reader 口径判为合规")


class PopulationGateOnRealDataTests(unittest.TestCase):
    """§9 固定分母：两棵 run 的 403 目标 / 806 provider 决策逐条进门禁，不过滤失败行。"""

    @classmethod
    def setUpClass(cls):
        if not V2R.is_dir():
            raise unittest.SkipTest("V2R 证据目录不存在：%s" % V2R)

    def load(self, run):
        dataset = json.loads((V2R / "primary" / run / "dataset_v422_selected.json")
                             .read_text(encoding="utf-8"))
        rows = [json.loads(line) for line in io.open(
            V2R / "primary" / run / "link_selection_report.jsonl", encoding="utf-8")]
        return dataset, rows

    def test_both_runs_are_enforced_with_fixed_denominators(self):
        g, ledger = gate(), full_ledger("population gate")
        totals = {"targets": 0, "decisions": 0}
        for run in RUNS:
            dataset, rows = self.load(run)
            self.assertEqual(len(rows), len(dataset["map_targets"]) * len(PROVIDERS), run)
            result = gate_mod.evaluate(dataset, g, SELECTION, report_rows=rows, ledger=ledger,
                                       payload_kind="audit")
            self.assertTrue(result["enforced"], result["applicability"])
            self.assertEqual(result["counts"]["blocking"], 0, result["blocking"][:5])
            self.assertEqual(result["counts"]["unclassified"], 0)
            self.assertEqual(result["batch_verdict"], "PASS_WITH_EXPOSURES")
            totals["targets"] += result["targets"]
            totals["decisions"] += len(rows)
        self.assertEqual(totals, {"targets": 403, "decisions": 806})

    def test_role_matrix_actually_removed_the_fake_errors(self):
        """V2R 之前这批数据报 278 条缺角色；现在只该留下真正该问的那些（关键 transport_node）。"""
        g, ledger = gate(), full_ledger("role regression pin")
        tally = {}
        for run in RUNS:
            dataset, rows = self.load(run)
            result = gate_mod.evaluate(dataset, g, SELECTION, report_rows=rows, ledger=ledger)
            for code, count in result["code_tally"].items():
                tally[code] = tally.get(code, 0) + count
        self.assertEqual(tally.get("MAP_FIELD_MISSING", 0), 14, tally)
        self.assertEqual(tally.get("CRITICAL_ROLE_MISSING", 0), 4, tally)
        self.assertGreaterEqual(tally.get("CRITICAL_NOT_VERIFIED", 0), 100, tally)
        self.assertNotIn("ROLE_NOT_ALLOWED_FOR_CATEGORY", tally,
                         "per-category 白名单不许再回来")

    def test_exposures_are_itemized_not_summarised_away(self):
        g, ledger = gate(), full_ledger("itemization")
        dataset, rows = self.load("philippines_v419")
        result = gate_mod.evaluate(dataset, g, SELECTION, report_rows=rows, ledger=ledger)
        codes = [item.split("|")[1] for item in result["exposed"]]
        self.assertEqual(len(result["exposed"]), sum(result["code_tally"].values()))
        self.assertTrue(all(codes), "暴露项必须逐条可追（§8.2）")
        self.assertEqual(result["google_entity_card_hit_rate"].startswith("NOT MEASURED"), True,
                         "§8.2：实体卡片命中率不得填数")
