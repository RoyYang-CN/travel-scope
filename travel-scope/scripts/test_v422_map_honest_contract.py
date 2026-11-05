# -*- coding: utf-8 -*-
"""v4.2.2 V1 — 诚实地图链接合同的执行型正反例。

范围纪律：本文件只测**合同层**（`references/map-link-selection.json`、
`references/renderer-contract.json`、`references/data-model.json`、
`scripts/map_link_selector.py`）。dataset→renderer→DOM→href 的四态正向用例属 V3/V4，
浏览器与重放属 V4/V6；在这里写它们只会得到自证的 PASS，所以按 §13 记 NOT RUN。

每条负例都必须能"咬人"：断言的是选择器的实际输出与不升级不变量，不是注释里写了什么。
"""
from __future__ import annotations

import ast
import copy
import hashlib
import inspect
import io
import json
import re
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
ROOT = SCRIPTS.parent

import data_model  # noqa: E402
import map_link_selector as mls  # noqa: E402
import spa_renderer as sr  # noqa: E402  （V3R：读者载荷投影）

SELECTION = json.loads((ROOT / "references" / "map-link-selection.json").read_text(encoding="utf-8"))
CONTRACT = json.loads((ROOT / "references" / "renderer-contract.json").read_text(encoding="utf-8"))
DATA_MODEL = json.loads((ROOT / "references" / "data-model.json").read_text(encoding="utf-8"))
MAP_POLICY_MD = (ROOT / "references" / "map-link-policy.md").read_text(encoding="utf-8")

# 合同夹具专用策略：与 test_v421_map_contract 同一手法，把 .example 夹具域名放进批准集，
# 生产策略仍然拒绝——实体链正例只能靠显式夹具成立，不允许悄悄放宽生产配置。
POLICY = copy.deepcopy(DATA_MODEL)
_classifier = POLICY["url_reference_classifier"]
_classifier["surface_eligible_approval_statuses"] = list(dict.fromkeys(
    list(_classifier["surface_eligible_approval_statuses"]) + ["contract_fixture_only_not_for_shipment"]))
_classifier["identity_eligible_approval_statuses"] = list(dict.fromkeys(
    list(_classifier["identity_eligible_approval_statuses"]) +
    ["measured_in_frozen_input_pending_terms_check", "contract_fixture_only_not_for_shipment"]))

LOOKUP = {"destinations": {"宿务": "Cebu", "圣塔芭芭拉": "Santa Barbara"},
          "countries": {"PH": "Philippines", "US": "United States"}}


def target(**over):
    """一条完整的 v4.2.2 target。默认值是**诚实状态**，不是方便取值。"""
    base = {
        "target_id": "t-1", "entity_type": "named_entity", "category": "hotel",
        "criticality": "CRITICAL_ITINERARY", "required_location_role": "MAIN_ENTRANCE",
        "display_name": "Grand Hotel Cebu", "names": {"en": "Grand Hotel Cebu", "cn": "宿务大酒店"},
        "country_code": "PH", "destination_scope": "宿务", "address_status": "MISSING",
        "identity_status": "UNVERIFIED", "coordinate_status": "UNVERIFIED",
        "google_resolution_status": "NOT_OBSERVED", "evidence": [], "resolver_used": False,
        "google_url": "https://www.google.com/maps/search/?api=1&query=Old%20Self%20Attested&ll=1,2",
        "apple_url": "https://maps.apple.com/?q=Old%20Self%20Attested",
    }
    base.update(over)
    return base


def decide(t, provider="google"):
    return mls.select(str(t.get("target_id") or "t"), t, provider, SELECTION,
                      policy=POLICY, lookup=LOOKUP).as_record()


def publisher_row(**over):
    row = {"source_type": "publisher_entity_page",
           "source_url_or_ref": "https://grandhotel.example/cebu",
           "retrieved_at": "2026-10-26", "supported_fields": ["display_name"],
           "lineage_group": "lg-pub", "content_digest": "sha256:def", "usage_scope": "link",
           "status": "complete",
           "declared_link_url": "https://www.google.com/maps/place/grand-hotel-cebu/@10.3,123.9,17z/data=!3m1!4b1",
           "link_url_provider": "google"}
    row.update(over)
    return row


class ConfigStrictnessTests(unittest.TestCase):
    """配置缺失或自相矛盾必须阻断，不允许回退到代码内默认值（§11 V1）。"""

    def broken(self, mutate):
        cfg = copy.deepcopy(SELECTION)
        mutate(cfg)
        path = ROOT / "references" / "_tmp_broken_selection.json"
        path.write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")
        try:
            return mls.load_selection(path)
        finally:
            path.unlink()

    def test_missing_required_key_blocks(self):
        for key in mls.REQUIRED_CONFIG_KEYS:
            with self.assertRaises(mls.SelectionConfigError, msg=key):
                self.broken(lambda cfg, k=key: cfg.pop(k))

    def test_unknown_primitive_blocks(self):
        with self.assertRaises(mls.SelectionConfigError):
            self.broken(lambda cfg: cfg["state_machine"][0]["when_any"].append(
                {"primitive": "google_told_us_so"}))

    def test_unregistered_reason_code_blocks(self):
        with self.assertRaises(mls.SelectionConfigError):
            self.broken(lambda cfg: cfg["state_machine"][0]["then"].update(
                reason_code="SELECTED_BECAUSE_IT_LOOKS_FINE"))

    def test_floating_reason_code_outside_the_machine_blocks(self):
        """V1 前 name_residue_rules/join_ambiguity_signals 各复制了一份 reason code：
        那些字段没有代码读取，是第二套权威。放开的同时把这条门收紧——不管登记不登记都报错。"""
        def add_registered_floating(cfg):
            cfg["join_ambiguity_signals"]["reason_code"] = "SELECTED_NAMED_SEARCH"
        with self.assertRaises(mls.SelectionConfigError):
            self.broken(add_registered_floating)
        def add_unregistered_floating(cfg):
            cfg.setdefault("name_residue_rules", {})["reason_code"] = "SELECTED_BECAUSE_IT_LOOKS_FINE"
        with self.assertRaises(mls.SelectionConfigError):
            self.broken(add_unregistered_floating)

    def test_shipped_config_has_no_floating_reason_code(self):
        """正面自证：现网配置里状态机之外的 reason code 必须为 0 条。"""
        self.assertEqual(list(mls._iter_reason_code_fields(SELECTION)), [],
                         "配置里又长出了游离 reason code 副本")

    def test_dead_reason_code_blocks(self):
        """登记了却状态机走不到 = 报告里永远为 0 的假可观测性。"""
        def dead(cfg):
            cfg["reason_codes"]["SELECTED_NAMED_SEARCH_LOCAL_NAME_AFTER_RESIDUE"] = "假的可观测项"
            for rule in cfg["state_machine"]:
                if rule["rule_id"] == "R4b":
                    rule["reason_code_overrides"] = []
        with self.assertRaises(mls.SelectionConfigError):
            self.broken(dead)

    def test_missing_fallback_rule_blocks(self):
        with self.assertRaises(mls.SelectionConfigError):
            self.broken(lambda cfg: cfg["state_machine"].pop())

    def test_local_name_query_needs_owner_ratification(self):
        """放开本地语言名进境外搜索串必须先有业主裁决登记，否则配置加载即报错。"""
        def flip(cfg):
            cfg["query_rules"]["allow_sourced_local_name_in_query"] = True
            cfg["query_rules"]["local_name_query_ratified_by"] = ""  # 放开必须带登记依据
        with self.assertRaises(mls.SelectionConfigError):
            self.broken(flip)

    def test_local_name_config_and_machine_must_agree(self):
        """配置与状态机必须同向：allow=false 却给本地名按钮 ⇒ 报错；allow=true 却不给 ⇒ 也报错。"""
        def grant_button(cfg):
            cfg["query_rules"]["allow_sourced_local_name_in_query"] = False
            for rule in cfg["state_machine"]:
                if rule["rule_id"] == "R4b":
                    rule["then"] = {"link_mode": "NAMED_SEARCH",
                                    "reason_code": "SELECTED_NAMED_SEARCH"}
        with self.assertRaises(mls.SelectionConfigError):
            self.broken(grant_button)

    def test_search_template_carrying_place_id_is_refused(self):
        cfg = copy.deepcopy(SELECTION)
        cfg["providers"]["google"]["search_url_template"] += "&query_place_id=ChIJfake"
        with self.assertRaises(mls.SelectionConfigError):
            mls.build_url("google", cfg, "Grand Hotel Cebu, Cebu, Philippines")

    def test_unregistered_provider_yields_no_button(self):
        rec = decide(target(), provider="baidu")
        self.assertEqual(rec["link_mode"], "NONE")
        self.assertEqual(rec["map_link_url"], "")


class StateMachinePositiveTests(unittest.TestCase):
    def test_r1_known_bad_link_blocks_and_isolates(self):
        for over in ({"flags": ["known_wrong_link"]},
                     {"quarantine": [{"kind": "google_url", "reason_code": "WRONG_BRANCH_SELECTED",
                                      "value": "x"}]},
                     {"google_resolution_status": "WRONG_ENTITY"},
                     {"identity_status": "CONFLICT"}):
            rec = decide(target(**over))
            self.assertEqual(rec["link_mode"], "NONE", over)
            self.assertTrue(rec["link_selection_reason"].endswith(
                "SELECT_BLOCKED_KNOWN_ERROR_OR_CONFLICT"), over)
            self.assertEqual(rec["isolated_link_url"], target()["google_url"],
                             "被阻断的旧 URL 必须留痕，不得静默删除")

    def test_r2_publisher_entity_link_only_when_all_four_gates_pass(self):
        rec = decide(target(identity_status="VERIFIED",
                            evidence=[publisher_row()]))
        self.assertEqual(rec["link_mode"], "PUBLISHER_ENTITY_LINK")
        self.assertEqual(rec["map_link_url"], publisher_row()["declared_link_url"])
        self.assertEqual(rec["query_fields_used"], [], "实体直达不拼搜索串")

    def test_r2_is_per_provider_and_self_reference_does_not_count(self):
        google = decide(target(identity_status="VERIFIED", evidence=[publisher_row()]))
        apple = decide(target(identity_status="VERIFIED", evidence=[publisher_row()]),
                       provider="apple")
        self.assertEqual(google["link_mode"], "PUBLISHER_ENTITY_LINK")
        self.assertEqual(apple["link_mode"], "NAMED_SEARCH",
                         "Google 的证据不得把 Apple 升级成实体直达（§4 前言）")
        self.assertIn("SELECTED_NAMED_SEARCH_VERIFIED_WITHOUT_ENTITY_LINK",
                      apple["link_selection_reason"])
        self_attested = decide(target(identity_status="VERIFIED", evidence=[publisher_row(
            source_url_or_ref=publisher_row()["declared_link_url"])]))
        self.assertNotEqual(self_attested["link_mode"], "PUBLISHER_ENTITY_LINK",
                            "出处就是链接自己时不构成发布方凭据（§17.3.1）")

    def test_r3_coordinate_only_for_unnamed_landmark_with_verified_coordinates(self):
        landmark = decide(target(entity_type="coordinate_landmark", names={},
                                 display_name="", canonical_name="",
                                 coordinate_status="VERIFIED", lat=10.3, lng=123.9))
        self.assertEqual(landmark["link_mode"], "COORDINATE")
        self.assertIn("10.3,123.9", landmark["map_link_url"])
        named = decide(target(entity_type="named_entity", coordinate_status="VERIFIED",
                              lat=10.3, lng=123.9))
        self.assertNotEqual(named["link_mode"], "COORDINATE",
                            "命名实体永不走纯坐标按钮（§3.2/§17.4.3）")
        unverified = decide(target(entity_type="coordinate_landmark", names={},
                                   display_name="", canonical_name="",
                                   coordinate_status="UNVERIFIED", lat=10.3, lng=123.9))
        self.assertEqual(unverified["link_mode"], "NONE")

    def test_r4_unverified_named_entity_gets_honest_search(self):
        rec = decide(target())
        self.assertEqual(rec["link_mode"], "NAMED_SEARCH")
        self.assertEqual(rec["link_selection_reason"], "R4|SELECTED_NAMED_SEARCH")
        self.assertIn("Grand%20Hotel%20Cebu", rec["map_link_url"])
        self.assertIn("Cebu", rec["map_link_url"])
        self.assertIn("Philippines", rec["map_link_url"])
        self.assertEqual(rec["map_link_url"].split("query=")[1],
                         "Grand%20Hotel%20Cebu,%20Cebu,%20Philippines",
                         "查询串顺序必须是 名称, 目的地, 国家（§6.1）")
        self.assertNotIn("ll=", rec["map_link_url"])
        self.assertNotIn("query_place_id", rec["map_link_url"])
        self.assertEqual(rec["link_notices"], ["key_target_unverified"],
                         "关键目标必须带订单/票证/运营方提示（§5.2）")

    def test_latin_scope_without_a_registry_entry_still_forms_the_destination_segment(self):
        """V2 实跑咬出来的缺陷：登记表只覆盖中文 scope，191/205 条 CA 的 scope 本身就是英文写法。

        修之前这些行的目的地段被整段丢掉，搜索串退化成「名字 + 国家」——看似仍然诚实，实际是
        实现少了一个分支，把 §6.1 的字段优先级悄悄降级了。
        """
        row = target(names={"en": "Best Western Plus Encina Inn and Suites"},
                     display_name="Best Western Plus Encina Inn and Suites",
                     destination_scope="California", country_code="US",
                     criticality="IMPORTANT")
        rec = decide(row)
        self.assertEqual(rec["link_mode"], "NAMED_SEARCH")
        self.assertEqual(rec["map_link_url"].split("query=")[1],
                         "Best%20Western%20Plus%20Encina%20Inn%20and%20Suites,%20California,"
                         "%20United%20States")
        self.assertEqual(rec["query_fields_used"],
                         ["sourced_canonical_name", "sourced_destination", "sourced_country"],
                         "有来源的目的地段必须进串，不能因为登记表没有条目就丢段")

    def test_registry_entry_beats_a_raw_scope_but_never_invents_one(self):
        """登记表给出英文形式时用登记表；两者都是 CJK 时不猜翻译（§4 绝不现场翻译）。"""
        with_table = decide(target(destination_scope="宿务", country_code="PH"))
        self.assertIn("Cebu", with_table["map_link_url"])
        only_local = decide(target(destination_scope="墨宝", country_code="PH"))
        self.assertEqual(only_local["link_mode"], "NAMED_SEARCH", "名称可用就仍给具名搜索")
        self.assertNotIn("墨宝", only_local["map_link_url"],
                         "没有有来源的英文目的地时，不允许把中文目的地塞进境外搜索串")
        self.assertEqual(only_local["query_fields_used"],
                         ["sourced_canonical_name", "sourced_country"])


class StateMachineNegativeTests(unittest.TestCase):
    def test_placeholder_numeric_corridor_and_absent_names_yield_no_button(self):
        cases = {
            "SELECT_BLOCKED_NAME_UNUSABLE": [
                target(names={"en": "California Venue"}, display_name="California Venue"),
                target(names={"en": "39"}, display_name="39"),
                target(names={"en": "旧金山 - 蒙特雷与卡梅尔 - 大苏尔"},
                       display_name="旧金山 - 蒙特雷与卡梅尔 - 大苏尔"),
                target(names={}, display_name="", canonical_name=""),
            ],
        }
        for expect, rows in cases.items():
            for row in rows:
                rec = decide(row)
                self.assertEqual(rec["link_mode"], "NONE", row.get("display_name"))
                self.assertTrue(rec["link_selection_reason"].endswith(expect),
                                "%s -> %s" % (row.get("display_name"), rec["link_selection_reason"]))

    def test_sourced_local_name_gets_named_search_verbatim_percent_encoded(self):
        """§4 禁止动作第 2 条（清册 line 102）＋业主 2026-10-29 登记：本地正式名称原样进串。"""
        name = "墨宝佩斯卡多尔岛大断层"
        rec = decide(target(names={"cn": name}, display_name=name, canonical_name=name))
        self.assertEqual(rec["link_mode"], "NAMED_SEARCH")
        self.assertTrue(rec["link_selection_reason"].endswith(
            "SELECTED_NAMED_SEARCH_LOCAL_NAME_RATIFIED"), rec["link_selection_reason"])
        from urllib.parse import unquote
        self.assertIn(name, unquote(rec["map_link_url"]),
                      "URL 必须原样承载本地正式名称：不得删字、不得截断、不得编造英文名")
        self.assertNotIn("undefined", rec["map_link_url"])
        self.assertEqual(rec["map_query_name_source"], "display_name",
                         "用了哪个有来源字段必须可追（§6.1 血缘）")
        self.assertIn("local_name_only", rec["selection_signals"],
                      "本地名搜索要单独计数，不能混进拉丁名那一条")

    def test_local_name_still_refused_when_it_is_a_deletion_fragment(self):
        """放开的只有『有来源的本地正式名称』：删字残片/占位/数字/走廊串仍然一律 NONE。"""
        for row, why in ((target(names={"cn": "39"}, display_name="39"), "只有数字"),
                         (target(names={"cn": "California Venue"}, display_name="California Venue"),
                          "模板占位名"),
                         (target(names={"cn": "518"}, display_name="518"), "纯数字"),
                         (target(names={"cn": "宿务 - 薄荷岛"}, display_name="宿务 - 薄荷岛"),
                          "走廊串")):
            rec = decide(row)
            self.assertEqual(rec["link_mode"], "NONE", "%s 竟然给了按钮：%r" % (why, rec))
            self.assertTrue(rec["link_selection_reason"].endswith("SELECT_BLOCKED_NAME_UNUSABLE"),
                            "%s 的原因码不对：%s" % (why, rec["link_selection_reason"]))

    def test_parenthesised_english_fragment_is_treated_as_deletion_residue(self):
        """'(Union Station)' 是删掉汉字后的片段：不许当英文名用，但本地正式名称照旧可搜。"""
        t = target(names={"cn": "洛杉矶联合车站", "en": "(Union Station)"},
                   display_name="洛杉矶联合车站")
        self.assertTrue(mls.is_deletion_residue(t))
        rec = decide(t)
        self.assertEqual(rec["link_mode"], "NAMED_SEARCH")
        from urllib.parse import unquote
        self.assertIn("洛杉矶联合车站", unquote(rec["map_link_url"]))
        self.assertNotIn("(Union Station)", unquote(rec["map_link_url"]),
                         "残片被当成了英文名（§4 禁止字符级改名）")
        self.assertTrue(rec["link_selection_reason"].endswith(
            "SELECTED_NAMED_SEARCH_LOCAL_NAME_AFTER_RESIDUE"), rec["link_selection_reason"])
        self.assertEqual(rec["map_query_name_source"], "names.cn(after_residue)",
                         "残片降级必须在血缘里显式留下痕迹，否则报告分不出『本来没英文名』和"
                         "『英文名是被删出来的』（V0-L02/V0-L06 就是后者）")

    def test_character_stripped_english_name_is_residue_and_falls_back_to_local_name(self):
        """『长滩岛Bulabog』去掉汉字就是『Bulabog』：这条英文名是删字产物，不许当查询名用。"""
        t = target(names={"cn": "长滩岛Bulabog", "en": "Bulabog"}, display_name="长滩岛Bulabog")
        self.assertTrue(mls.is_deletion_residue(t), "删字残片未被识别")
        rec = decide(t)
        from urllib.parse import unquote
        url = unquote(rec["map_link_url"])
        self.assertEqual(rec["link_mode"], "NAMED_SEARCH")
        self.assertIn("query=长滩岛Bulabog", url, "应整串使用有来源的本地正式名称")
        self.assertNotIn("query=Bulabog", url, "查询名被换成了删字后的残片")
        self.assertTrue(rec["link_selection_reason"].endswith(
            "SELECTED_NAMED_SEARCH_LOCAL_NAME_AFTER_RESIDUE"), rec["link_selection_reason"])

    def test_independent_english_name_is_not_residue(self):
        """负向：'Cebu Port Pier 1' 与本地名 '宿务港1号码头' 只是同一地点的两种写法，不是删字残片。"""
        t = target(names={"cn": "宿务港1号码头", "en": "Cebu Port Pier 1"},
                   display_name="宿务港1号码头")
        self.assertFalse(mls.is_deletion_residue(t), "独立英文名被误判为残片——会把好名字降级")
        rec = decide(t)
        self.assertEqual(rec["link_mode"], "NAMED_SEARCH")
        self.assertTrue(rec["link_selection_reason"].endswith("SELECTED_NAMED_SEARCH"),
                        rec["link_selection_reason"])

    def test_plain_local_name_and_residue_fallback_are_counted_apart(self):
        """§1 要求正反对开：同为本地名搜索，『本来没有可信英文名』和『英文名是残片』必须分开计数。"""
        plain = decide(target(names={"cn": "宿务大酒店"}, display_name="宿务大酒店"))
        residue = decide(target(names={"cn": "洛杉矶联合车站", "en": "(Union Station)"},
                                display_name="洛杉矶联合车站"))
        self.assertEqual(plain["link_mode"], residue["link_mode"], "NAMED_SEARCH")
        self.assertNotEqual(plain["link_selection_reason"], residue["link_selection_reason"],
                            "两个来源问题被并进了同一个 reason code，报告看不出来")

    def test_stale_identity_and_useless_observed_outcomes_yield_no_button(self):
        for over, expect in (({"identity_status": "STALE"}, "SELECT_BLOCKED_IDENTITY_STALE"),
                             ({"google_resolution_status": "NO_RESULT"},
                              "SELECT_BLOCKED_OBSERVED_SEARCH_OUTCOME_USELESS"),
                             ({"google_resolution_status": "BLOCKED"},
                              "SELECT_BLOCKED_OBSERVED_SEARCH_OUTCOME_USELESS")):
            rec = decide(target(**over))
            self.assertEqual(rec["link_mode"], "NONE", over)
            self.assertTrue(rec["link_selection_reason"].endswith(expect), rec["link_selection_reason"])

    def test_no_city_country_or_corridor_only_fallback(self):
        """名称不可用时绝不退化成城市/国家搜索——那正是 §4 禁止的伪目标。"""
        rec = decide(target(names={}, display_name="", canonical_name=""))
        self.assertEqual(rec["link_mode"], "NONE")
        self.assertNotIn("Cebu", rec["map_link_url"])
        self.assertNotIn("Philippines", rec["map_link_url"])


class NoPromotionInvariantTests(unittest.TestCase):
    """§3.1/§3.4/§8.2：搜索 URL 的生成不得升级任何状态维度。"""

    def test_selector_writes_only_link_side_fields(self):
        for over in ({}, {"identity_status": "AMBIGUOUS"}, {"google_resolution_status": "MULTIPLE_RESULTS"},
                     {"evidence": [publisher_row()], "identity_status": "VERIFIED"}):
            rec = decide(target(**over))
            extra = set(rec) - set(mls.WRITABLE_FIELDS)
            self.assertEqual(extra, set(), "选择器写出了链接侧以外的字段：%s" % extra)

    def test_target_status_fields_untouched_by_selection(self):
        t = target()
        snapshot = {k: t[k] for k in ("identity_status", "coordinate_status",
                                      "google_resolution_status", "criticality")}
        decide(t)
        self.assertEqual({k: t[k] for k in snapshot}, snapshot,
                         "select() 不得原地修改状态字段")

    def test_named_search_never_reports_entity_verification(self):
        cases = [
            ({}, "SELECTED_NAMED_SEARCH", []),
            ({"identity_status": "AMBIGUOUS"}, "SELECTED_NAMED_SEARCH_AMBIGUOUS_IDENTITY",
             ["ambiguous_multiple_results"]),
            ({"quarantine": [{"kind": "canonical_name", "reason_code": "AMBIGUOUS_JOIN",
                              "value": "x"}],
              "unresolved_fields": [{"reason_code": "CATEGORY_JOIN_AMBIGUOUS"}]},
             "SELECTED_NAMED_SEARCH_AMBIGUOUS_JOIN_SIGNAL", ["join_ambiguity"]),
        ]
        for over, expect_reason, expect_extra in cases:
            rec = decide(target(**over))
            self.assertEqual(rec["link_mode"], "NAMED_SEARCH", over)
            self.assertTrue(rec["link_selection_reason"].endswith(expect_reason),
                            "%s -> %s" % (over, rec["link_selection_reason"]))
            self.assertNotIn("query_place_id", rec["map_link_url"])
            self.assertNotIn("VERIFIED", json.dumps(rec, ensure_ascii=False),
                             "选择结果不得夹带身份已核验的表述")
            if expect_extra == ["ambiguous_multiple_results"]:
                self.assertIn("ambiguous_multiple_results", rec["link_notices"], over)
            if expect_extra == ["join_ambiguity"]:
                self.assertIn("join_ambiguity", rec["selection_signals"], rec)
                self.assertIn("ambiguous_multiple_results", rec["link_notices"], rec)

    def test_deterministic_and_replay_stable(self):
        first = json.dumps(decide(target()), ensure_ascii=False, sort_keys=True)
        for _ in range(3):
            self.assertEqual(json.dumps(decide(target()), ensure_ascii=False, sort_keys=True), first,
                             "同输入同配置必须逐字节可重放（§9）")


class SingleAuthorityConsistencyTests(unittest.TestCase):
    """文案/DOM/枚举在多处登记时，必须逐字一致——不一致就是合同漂移。"""

    def test_renderer_copy_equals_selection_copy(self):
        rc = CONTRACT["presentation"]["map_link_contract"]["link_modes"]
        for mode, copy_spec in SELECTION["ui"]["button_copy"].items():
            if "label_cn" not in copy_spec:
                continue
            self.assertEqual(rc[mode]["label_cn"], copy_spec["cn"], mode)
            self.assertEqual(rc[mode]["label_en"], copy_spec["en"], mode)

    def test_named_search_copy_states_landing_not_verified(self):
        cn = SELECTION["ui"]["button_copy"]["NAMED_SEARCH"]["cn"]
        en = SELECTION["ui"]["button_copy"]["NAMED_SEARCH"]["en"]
        self.assertIn("未核验", cn)
        self.assertIn("not verified", en)
        for phrase in SELECTION["ui"]["button_copy"]["PUBLISHER_ENTITY_LINK"]["forbidden_phrases"]:
            self.assertNotIn(phrase, cn, "搜索按钮不得声称已核验/查看地点")

    def test_dom_attribute_list_is_the_eight_from_section_7(self):
        expected = ["data-target-id", "data-entity-type", "data-criticality",
                    "data-identity-status", "data-coordinate-status", "data-link-mode",
                    "data-google-resolution-status", "data-provider"]
        self.assertEqual(SELECTION["dom_attributes"], expected)
        self.assertEqual(CONTRACT["presentation"]["map_link_contract"]["dom_audit_attributes"], expected)

    def test_reader_notice_text_matches_section_5_2_verbatim(self):
        self.assertEqual(
            SELECTION["ui"]["notices"]["key_target_unverified"]["cn"],
            "地图落点未核验，请以订单、票证或运营方公布的地址、航站楼/码头信息为准。")
        self.assertEqual(
            SELECTION["ui"]["notices"]["ambiguous_multiple_results"]["cn"],
            "可能有多个结果，请核对订单、票证或运营方信息。")
        rc = CONTRACT["presentation"]["map_link_contract"]
        for key, spec in SELECTION["ui"]["notices"].items():
            self.assertEqual(rc["reader_notices"][key], spec["cn"], key)

    def test_schema_points_at_the_same_selection_version(self):
        self.assertEqual(DATA_MODEL["map_link_selection_contract"]["selection_version"],
                         SELECTION["selection_version"])
        self.assertEqual(CONTRACT["presentation"]["map_link_contract"]["link_selection_contract"]
                         ["selection_version"], SELECTION["selection_version"])
        self.assertTrue(CONTRACT["presentation"]["map_link_contract"]["link_selection_contract"]
                        ["forbid_renderer_url_construction"])

    def test_link_context_requires_selection_version_for_button_modes(self):
        for mode in ("PUBLISHER_ENTITY_LINK", "NAMED_SEARCH", "COORDINATE"):
            self.assertIn("link_selection_version",
                          DATA_MODEL["link_context_required_by_mode"][mode], mode)

    def test_policy_prose_carries_the_new_state_machine(self):
        self.assertIn("## 4b.", MAP_POLICY_MD)
        self.assertIn("SELECTED_NAMED_SEARCH_LOCAL_NAME_RATIFIED", MAP_POLICY_MD)
        self.assertIn("SELECTED_NAMED_SEARCH_LOCAL_NAME_AFTER_RESIDUE", MAP_POLICY_MD,
                      "残片降级是单独一条可审计结论，政策正文必须点名它")
        self.assertNotIn("SELECT_BLOCKED_NO_SOURCED_LATIN_NAME", MAP_POLICY_MD,
                         "旧原因码已从闭集移除，政策正文不许还留着它")
        self.assertIn("line 102", MAP_POLICY_MD, "放开本地名必须写清合同出处")
        self.assertIn("NOT MEASURED / NOT A RELEASE GATE", MAP_POLICY_MD)

    def test_reason_codes_are_closed_enumeration(self):
        used = set()
        for rule in SELECTION["state_machine"]:
            used.add(rule["then"]["reason_code"])
            for override in rule.get("reason_code_overrides") or []:
                used.add(override["reason_code"])
        declared = set(SELECTION["reason_codes"])
        self.assertEqual(used - declared, set(), "规则使用了未登记的 reason code")
        self.assertEqual(declared - used, set(), "登记了规则永远用不到的 reason code（假门面）")


    def test_reason_codes_live_only_in_the_config(self):
        """§11 V1「同步错误码」= 只有一个权威：schema 侧只放指针，不放第二份清单。"""
        contract = DATA_MODEL["map_link_selection_contract"]
        self.assertTrue(contract["reason_codes_must_not_be_copied_here"])
        self.assertIn("map-link-selection.json::reason_codes", contract["reason_codes_ref"])

        def lists(node):
            if isinstance(node, dict):
                for value in node.values():
                    for found in lists(value):
                        yield found
            elif isinstance(node, list):
                yield node
                for value in node:
                    for found in lists(value):
                        yield found

        codes = set(SELECTION["reason_codes"])
        copied = [item for item in lists(DATA_MODEL)
                  if codes & {v for v in item if isinstance(v, str)}]
        self.assertEqual(copied, [],
                         "data-model 里出现了复制的选择原因码清单，两处答案迟早分叉：%s" % copied)
        renderer = json.dumps(CONTRACT, ensure_ascii=False)
        self.assertFalse([code for code in codes if code in renderer],
                         "渲染合同也不得复制 reason code")

    def test_output_fields_are_registered_in_schema(self):
        """选择器写进 dataset 的字段面必须与 schema 登记逐项相等（实现不得悄悄扩面）。"""
        registered = set(DATA_MODEL["map_link_output_fields"]["fields"])
        self.assertEqual(set(mls.WRITABLE_FIELDS), registered)
        self.assertEqual(
            DATA_MODEL["map_link_output_fields"]["authority_implementation"],
            "scripts/map_link_selector.py::WRITABLE_FIELDS")
        self.assertIn("link_selection_version", DATA_MODEL["link_context_fields"])
        for name, meaning in DATA_MODEL["map_link_output_fields"]["fields"].items():
            self.assertTrue(meaning.strip(), "%s 必须有可读含义，不能只列名字" % name)


class PerProviderContainerTests(unittest.TestCase):
    """§3.3/§4 前言 + V2-G02：dataset 必须能同时承载两个 provider 的独立决策。"""

    def test_container_covers_exactly_the_registered_providers(self):
        container = mls.select_all_providers("t-1", target(), sel=SELECTION,
                                            policy=POLICY, lookup=LOOKUP)
        self.assertEqual(sorted(container), sorted(SELECTION["providers"]))
        for provider, record in container.items():
            self.assertTrue(set(record) <= set(mls.WRITABLE_FIELDS), provider)
            self.assertEqual(record["link_provider"], provider)
            self.assertEqual(record["link_selection_version"], SELECTION["selection_version"])

    def test_google_evidence_does_not_upgrade_apple_inside_the_container(self):
        row = target(identity_status="VERIFIED", evidence=[publisher_row()])
        container = mls.select_all_providers("t-1", row, sel=SELECTION,
                                            policy=POLICY, lookup=LOOKUP)
        self.assertEqual(container["google"]["link_mode"], "PUBLISHER_ENTITY_LINK")
        self.assertEqual(container["apple"]["link_mode"], "NAMED_SEARCH",
                         "两个 provider 必须各判各的（§4 前言），容器不是共享答案的地方")
        self.assertNotEqual(container["google"]["map_link_url"],
                            container["apple"]["map_link_url"])

    def test_unregistered_provider_is_refused_not_silently_dropped(self):
        with self.assertRaises(mls.SelectionConfigError):
            mls.select_all_providers("t-1", target(), sel=SELECTION, policy=POLICY,
                                     lookup=LOOKUP, providers=["google", "huaweimap"])

    def test_schema_registers_this_container_and_names_the_single_writer(self):
        block = DATA_MODEL["map_link_per_provider_container"]
        self.assertEqual(block["field"], "map_link_by_provider")
        self.assertEqual(block["writer"],
                         "scripts/map_link_selector.py::select_all_providers")
        self.assertEqual(block["primary_provider"], "google")
        self.assertEqual(block["value_fields_ref"], "map_link_output_fields.fields")
        self.assertEqual(sorted(block["legacy_fields"]), ["apple_url", "google_url"],
                         "旧字段只作为证据保留；渲染层引用它们必须由门禁判 FAIL（V3）")


class ConditionalFieldSemanticsTests(unittest.TestCase):
    """§11 V1R-3：resolver_used / evidence / lineage_group 的条件语义必须由真实校验器执行。"""

    def clean_row(self, **over):
        row = dict(target(**over))
        row.pop("google_url", None)
        row.pop("apple_url", None)
        row.update({"lineage_group": "", "policy_version": "v4.2.2-v1r",
                    "evaluated_at": "2026-10-29", "classifier_version": "refclassifier-4",
                    "criticality": "IMPORTANT", "resolver_used": False})
        row.update(mls.select(str(row["target_id"]), row, "google", SELECTION,
                              policy=POLICY, lookup=LOOKUP).as_record())
        return row

    def errors(self, row):
        return data_model.validate_map_targets({str(row["target_id"]): row}, POLICY)

    def test_explicit_empty_evidence_does_not_block_unverified_named_search(self):
        row = self.clean_row(evidence=[], lineage_group="")
        found = self.errors(row)
        self.assertEqual(row["link_mode"], "NAMED_SEARCH", found)
        self.assertEqual([f for f in found if f.startswith(("MAP_FIELD_MISSING",
                                                            "MAP_FIELD_NOT_EXPLICIT",
                                                            "RESOLVER_"))], [],
                         "显式为空的 evidence/lineage 与 resolver_used=false 不该再算缺必填：%s" % found)

    def test_missing_evidence_key_is_reported_as_unknown_not_as_absent(self):
        row = self.clean_row()
        row.pop("evidence")
        self.assertTrue([f for f in self.errors(row) if f.startswith("MAP_FIELD_NOT_EXPLICIT")],
                        "缺键=状态未知，必须与『显式为空』区分")

    def test_fake_resolver_version_is_refused_when_chain_is_off(self):
        row = self.clean_row()
        row["resolver_version"] = "w3-resolver-phase-1"
        self.assertTrue([f for f in self.errors(row)
                         if f.startswith("RESOLVER_VERSION_WITHOUT_RESOLVER")],
                        "resolver_used=false 却写版本号，就是伪造血缘")

    def test_resolver_used_must_be_an_explicit_boolean(self):
        for value in (None, "", "false", 0):
            row = self.clean_row()
            row["resolver_used"] = value
            found = self.errors(row)
            self.assertTrue([f for f in found if f.startswith(("RESOLVER_USED_NOT_EXPLICIT",
                                                               "MAP_FIELD_MISSING"))],
                            "resolver_used=%r 未被点名：%s" % (value, found))

    def test_explicit_empty_evidence_still_blocks_verified_identity(self):
        row = self.clean_row(identity_status="VERIFIED", evidence=[], lineage_group="")
        found = self.errors(row)
        self.assertTrue([f for f in found
                         if f.startswith("IDENTITY_VERIFIED_WITHOUT")],
                        "放开 UNVERIFIED 不等于放开 VERIFIED（§3.1）：%s" % found)

    def test_link_selection_version_stays_mandatory(self):
        row = self.clean_row()
        row.pop("link_selection_version")
        self.assertTrue([f for f in self.errors(row) if "link_selection_version" in f],
                        "本地名放开不影响 §13 的选择机版本必填")


class ValidatorTeethTests(unittest.TestCase):
    """合同不能只写在 schema 列表里：缺 `link_selection_version` 必须由真实校验器点名（§9）。"""

    def button_mode_cases(self):
        return {
            "PUBLISHER_ENTITY_LINK": target(identity_status="VERIFIED", evidence=[publisher_row()]),
            "NAMED_SEARCH": target(),
            "COORDINATE": target(entity_type="coordinate_landmark", names={}, display_name="",
                                 canonical_name="", coordinate_status="VERIFIED",
                                 lat=10.3, lng=123.9),
        }

    def test_validator_names_a_missing_selection_version_for_every_button_mode(self):
        for mode, row in self.button_mode_cases().items():
            merged = dict(row, **decide(row))
            self.assertEqual(merged["link_mode"], mode, "夹具本身没走到这一态，正例无效")
            self.assertEqual([e for e in data_model.validate_map_targets({"t-1": merged}, POLICY)
                              if "link_selection_version" in e], [],
                             "%s 齐备却仍被点名：%s" % (mode, merged))
            broken = dict(merged)
            broken.pop("link_selection_version")
            hits = [e for e in data_model.validate_map_targets({"t-1": broken}, POLICY)
                    if "link_selection_version" in e]
            self.assertEqual(len(hits), 1, "%s 删除 link_selection_version 未被发现：%s" % (mode, hits))

    def test_none_mode_still_needs_only_the_reason(self):
        row = dict(target(identity_status="CONFLICT"), **decide(target(identity_status="CONFLICT")))
        self.assertEqual(row["link_mode"], "NONE")
        self.assertTrue(row["link_selection_reason"])
        self.assertEqual([e for e in data_model.validate_map_targets({"t-1": row}, POLICY)
                          if "link_selection_version" in e], [],
                         "NONE 不产生 URL，不该被要求声明构造版本（否则就是拿假分母卡 honest 降级）")


class SingleAuthorityImplementationTests(unittest.TestCase):
    """§17.7.1 ⑨：新实现不得变成第二套 URL/主机判定；台账数字必须是量出来的。"""

    TARGET = "scripts/map_link_selector.py"

    def _fresh_counts(self):
        patterns = DATA_MODEL["second_judgment_inventory"]["semantic_call_sites_measured"]["patterns"]
        body = (SCRIPTS / "map_link_selector.py").read_text(encoding="utf-8")
        counts = {name: len(re.findall(pattern, body, re.IGNORECASE))
                  for name, pattern in patterns.items()}
        return body, counts, sorted(n for n, c in counts.items() if c)

    def test_selector_parses_no_url_and_extracts_no_host(self):
        body, counts, _touches = self._fresh_counts()
        self.assertEqual(counts["url_parse"], 0, "选择器不得自己解析 URL——判定只住 classify_reference")
        self.assertEqual(counts["host_extraction"], 0, "选择器不得自己取主机名")
        for token in ("google.com", "maps.apple.com", "openstreetmap.org", "maps.googleapis.com",
                      "amap.com", "baidu.com"):
            self.assertNotIn(token, body, "%s 出现在选择器里=第二套 provider 字面量（§6.3）" % token)
        self.assertIn("data_model.classify_reference", body,
                      "实体链门必须复用唯一 classifier 入口，而不是自己看 URL 长相")
        tree = ast.parse(body)
        public = [node.name for node in tree.body
                  if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                  and not node.name.startswith("_")]
        forks = [name for name in public
                 if "host" in name.lower() or "classify" in name.lower()]
        self.assertEqual(forks, [], "公开的 URL/主机判定入口必须只有 data_model.classify_reference")

    def test_registered_ledger_entry_equals_a_fresh_measurement(self):
        _body, counts, touches = self._fresh_counts()
        entries = [item for item in DATA_MODEL["second_judgment_inventory"]["semantic_call_sites"]
                   if item["file"] == self.TARGET]
        self.assertEqual(len(entries), 1, "台账必须且只能有一条选择器记录")
        entry = entries[0]
        self.assertEqual(entry["counts"], counts,
                         "登记数与实际测量不符：%s vs %s" % (entry["counts"], counts))
        self.assertEqual(sorted(entry["touches"]), touches)
        self.assertEqual(entry["sha256_12"],
                         hashlib.sha256((SCRIPTS / "map_link_selector.py").read_bytes())
                         .hexdigest()[:12].upper(),
                         "登记指纹过期：改过实现就必须重新测量并登记")
        self.assertFalse(entry["is_classifier_authority"])
        self.assertEqual(entry["disposition"], "unreviewed_second_judgment_candidate")


class ReaderPayloadProjectionTests(unittest.TestCase):
    """V3R §4：读者载荷只带 rendered_providers；审计面一条不少。投影是配置驱动，不是硬编码 Apple。"""

    def ui(self, rendered=None):
        cfg = SELECTION["ui"]
        return {"selection_version": SELECTION["selection_version"],
                "primary_provider": cfg["primary_provider"],
                "rendered_providers": list(rendered if rendered is not None
                                           else cfg["rendered_providers"]),
                "button_copy": cfg["button_copy"], "notices": cfg["notices"],
                "authority": "references/map-link-selection.json"}

    def adapted(self, rows=None):
        targets = rows if rows is not None else {"t-1": dict(target(), **{
            "map_link_by_provider": mls.select_all_providers(
                "t-1", target(), sel=SELECTION, policy=POLICY, lookup=LOOKUP)})}
        return {"map_targets": targets}

    def test_projection_keeps_only_the_rendered_providers(self):
        adapted = self.adapted()
        marker = sr._project_reader_map_links(adapted, self.ui())
        container = adapted["map_targets"]["t-1"]["map_link_by_provider"]
        self.assertEqual(sorted(container), sorted(SELECTION["ui"]["rendered_providers"]),
                         "读者载荷里出现的 provider 必须等于登记值（§8.1 的可判定义）")
        self.assertNotIn("apple", container, "读者拿不到的按钮，读者也不该为它付字节")
        self.assertEqual(marker["stripped_providers"], {"apple": 1})
        self.assertEqual(sorted(marker), sorted(set(marker)), "marker 键必须稳定可重放")
        for field in DATA_MODEL["map_link_per_provider_container"][
                "reader_payload_projection"]["marker_fields_required"]:
            self.assertIn(field, marker, "%s 没登记进 marker，审计看不出剔了什么" % field)

    def test_rendered_record_is_byte_for_byte_the_selector_output(self):
        """投影只删不改：留下的那条记录必须与选择器输出逐字段相同。"""
        source = mls.select_all_providers("t-1", target(), sel=SELECTION, policy=POLICY,
                                          lookup=LOOKUP)
        adapted = self.adapted({"t-1": dict(target(), map_link_by_provider=copy.deepcopy(source))})
        sr._project_reader_map_links(adapted, self.ui())
        left = adapted["map_targets"]["t-1"]["map_link_by_provider"]["google"]
        self.assertEqual(json.dumps(left, sort_keys=True),
                         json.dumps(source["google"], sort_keys=True),
                         "投影过程改写了决策内容")

    def test_projection_does_not_touch_the_audit_dataset(self):
        rows = {"t-1": dict(target(), map_link_by_provider=copy.deepcopy(
            mls.select_all_providers("t-1", target(), sel=SELECTION, policy=POLICY,
                                     lookup=LOOKUP)))}
        adapted = self.adapted(copy.deepcopy(rows))
        sr._project_reader_map_links(adapted, self.ui())
        self.assertEqual(sorted(rows["t-1"]["map_link_by_provider"]),
                         sorted(SELECTION["providers"]),
                         "§3.3 的 per-provider 审计面被投影改动了")

    def test_projection_follows_the_config_not_a_hardcoded_provider_name(self):
        both = self.adapted({"t-1": dict(target(), map_link_by_provider=copy.deepcopy(
            mls.select_all_providers("t-1", target(), sel=SELECTION, policy=POLICY,
                                     lookup=LOOKUP)))})
        marker = sr._project_reader_map_links(both, self.ui(rendered=["google", "apple"]))
        self.assertEqual(marker["stripped_providers"], {}, "登记两个 provider 却仍剔 Apple＝硬编码")
        only_apple = self.adapted({"t-1": dict(target(), map_link_by_provider=copy.deepcopy(
            mls.select_all_providers("t-1", target(), sel=SELECTION, policy=POLICY,
                                     lookup=LOOKUP)))})
        marker = sr._project_reader_map_links(only_apple, self.ui(rendered=["apple"]))
        self.assertEqual(sorted(only_apple["map_targets"]["t-1"]["map_link_by_provider"]),
                         ["apple"])
        self.assertEqual(marker["stripped_providers"], {"google": 1},
                         "登记值换成 apple 时，被剔的必须是 google")

    def test_empty_rendered_providers_is_refused_instead_of_guessing(self):
        with self.assertRaises(ValueError):
            sr._project_reader_map_links(self.adapted(), self.ui(rendered=[]))

    def test_real_render_payload_carries_the_projection(self):
        dataset = {"country": "测试国", "country_en": "Testland", "duration_days": 3,
                   "routes": [["测试线路", "3 天", "北部", "a", "b", 1000, "c", "Test Route"]],
                   "route_budgets": {"测试线路": {"total_cny": 1000}},
                   "itinerary": [], "map_targets": {
                       "t-1": dict(target(), map_link_by_provider=copy.deepcopy(
                           mls.select_all_providers("t-1", target(), sel=SELECTION,
                                                    policy=POLICY, lookup=LOOKUP)))}}
        out = Path(tempfile.mkdtemp()) / "v3r_page.html"   # 不往发布树里写临时成品
        sr.render_spa_document(str(out), dataset, media_delivery_mode="linked")
        text = out.read_text(encoding="utf-8")
        hit = re.search(r'<script id="dataset" type="application/json">(.*?)</script>', text, re.S)
        self.assertTrue(hit, "成品里没有内嵌 dataset 载荷")
        payload = json.loads(hit.group(1).replace("\\u003c", "<").replace("\\u003e", ">")
                             .replace("\\u0026", "&"))
        container = payload["map_targets"]["t-1"]["map_link_by_provider"]
        self.assertEqual(sorted(container), sorted(SELECTION["ui"]["rendered_providers"]))
        self.assertEqual(payload["map_link_render_projection"]["stripped_providers"], {"apple": 1})
        self.assertNotIn("maps.apple.com", json.dumps(container, ensure_ascii=False),
                         "被剔的 provider 记录仍以序列化形式留在读者载荷里")

    def test_schema_registers_the_projection_and_its_implementation(self):
        block = DATA_MODEL["map_link_per_provider_container"]["reader_payload_projection"]
        self.assertEqual(block["implementation"], "scripts/spa_renderer.py::_project_reader_map_links")
        self.assertTrue(hasattr(sr, "_project_reader_map_links"), "schema 指的实现不存在")
        self.assertIn("ui.rendered_providers", block["rule"])
        src = inspect.getsource(sr._project_reader_map_links)
        self.assertIn("rendered_providers", src,
                      "投影必须读登记值，不能自己写死 provider 名单")
        self.assertNotIn('"apple"', src, "实现里出现了字面 apple＝第二套判定")
        self.assertTrue(block["must_not_mutate_audit_dataset"])


if __name__ == "__main__":
    unittest.main()
