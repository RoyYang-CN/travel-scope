# -*- coding: utf-8 -*-
"""v4.2.2 V6-R：显式 alias_of 合同 + 正式 run 血缘阻断的执行型牙齿。

业主 2026-10-31 窄指令的六条要求逐条对应到这里：

  §1 205 = 200 canonical + 5 alias，配对逐项登记，运行时不按坐标/名称猜测；canonical 的按钮可以
         覆盖登记的 alias，但报告仍逐行列出 205 行。
  §2 正式/live run 缺 map_link_selection.selection_version 或版本错误 ⇒ 阻断；NOT_APPLICABLE 只留给
         非正式兼容路径（历史产物、夹具）。
  §3 正例 + 负例：别名环 / 目标不存在 / URL·状态不一致 / 未登记同址双键 / 缺失或错误的 selection 版本。
  §4 重跑 CA 205·PH 198 的 dataset→DOM→href 全量对账与两次确定性重放（端到端在 v6d 工具里跑，
         本文件守住在册等式与逐条校验）。
  §5 不许把 alias 写成 NONE、不许删行、不许加重复按钮、不许改分母。

V6-R1（同日追加指令）把等价判据收紧，本文件同步三件事：`canonical_name / display_name / names /
link_notices / evidence` 进指纹（五个字段各一条负测：漂移 ⇒ CONFLICT 且不获豁免，缺口重新按
HREF_MISSING 阻断）；排除面只剩 target_id / alias_of / 三条内嵌自身行路径的迁移审计轨迹，逐项带
理由与实测；对象/数组的比较走 `normalized_field_value`（规范化 JSON，键序无关、数组保序、
「缺格」≠「空值」），并有 AST 测试禁止退回 `str(dict)`。夹具也照真实形状改：五组配对的差别在
行键与 target_id，**不在名字**。

约定：本文件不写发布树产物；真实数据面缺失时直接报错而不是静默跳过。
"""
from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
ROOT = SCRIPTS.parent
PROJ = ROOT.parents[1]                    # D:/文档/项目开发/Travel-Scope（.temp 与发布根同级）
ALIASED = PROJ / ".temp" / "v422_honest_map" / "V6_candidate_run" / "primary_aliased"

import map_gate_v422 as mg422           # noqa: E402
import map_link_selector as mls          # noqa: E402
import visual_qa as vq                   # noqa: E402

SELECTION = mls.load_selection()
GATE = mg422.load_gate()
CONTRACT = mg422.alias_contract(GATE)
COUNTRY = str(CONTRACT.get("scope_field") or "country")
PROVENANCE = {"selection_version": str(SELECTION["selection_version"])}


def target(key: str, href: str = "", name: str = "", **over) -> dict:
    """一条 NAMED_SEARCH 目标。`href` 显式传入时，同址双键的两行才能真的共用一颗按钮。

    `name` 单独给名字：V6-R1 之后 `display_name / canonical_name / names` 都进 alias 指纹，
    夹具必须能表达「行键不同但名字相同」这个真实形状（五组配对实测就是这个形状）。
    """
    shown = name or key
    url = href or "https://www.google.com/maps/search/?api=1&query=%s" % key.replace(" ", "%20")
    row = {
        "target_id": key, "entity_type": "named_entity", "category": "attraction",
        "criticality": "STANDARD", "display_name": shown, "names": {"en": shown, "cn": shown},
        "canonical_name": shown, "country_code": "US", "destination_scope": "旧金山",
        "coords": "37.33,-122.00",
        "identity_status": "UNVERIFIED", "coordinate_status": "VERIFIED",
        "google_resolution_status": "NOT_OBSERVED", "address_status": "UNVERIFIED",
        "resolver_used": False, "lineage_group": "", "evidence": [], "link_notices": [],
        "policy_version": "v4.2.2", "evaluated_at": "2026-10-31T00:00:00+08:00",
        "link_builder_version": "v4.2.2",
        "link_selection_version": str(SELECTION["selection_version"]),
        "map_query_name_source": "canonical_name",
        "target_level": "search_candidate", "link_mode": "NAMED_SEARCH",
        "map_link_url": url, "google_url": url,
        "map_link_by_provider": {
            "google": {"link_mode": "NAMED_SEARCH", "map_link_url": url},
            "apple": {"link_mode": "NAMED_SEARCH",
                      "map_link_url": url.replace("google.com/maps/search/?api=1&query=",
                                                  "maps.apple.com/?q=")},
        },
    }
    row.update(over)
    return row


def same_address_pair(canonical_key: str = "旧金山|A CN", alias_key: str = "旧金山|A EN",
                      alias_of: str = "", name: str = "Apple Park 访客中心与屋顶咖啡露台",
                      **alias_over):
    """真实同址双键的形状（V6-R1 实测更正）：**行键与 target_id 不同，名字/状态/href 逐字段相同**。

    以前这对夹具写成「名字也不同」，因为旧判据不比对名字，夹具就顺着判据的形状长。业主把
    `canonical_name / display_name / names` 纳进指纹后重测五组真实配对：这三项两侧完全相同，
    所以夹具必须照真实形状来，否则正例测的是我们并不主张的那种等价关系。
    """
    url = "https://www.google.com/maps/search/?api=1&query=Apple%20Park"
    canonical = target(canonical_key, href=url, name=name)
    alias = target(alias_key, href=url, name=name, alias_of=alias_of, **alias_over)
    return alias, canonical


def pair_dataset(rows: dict, country: str = "美国") -> dict:
    return {"country": country, "map_targets": rows, "map_link_selection": dict(PROVENANCE)}


def dom_row(row: dict) -> dict:
    return {"targetId": row["target_id"], "provider": "google", "href": row["map_link_url"],
            "linkMode": row["link_mode"],
            "text": str(SELECTION["ui"]["button_copy"]["NAMED_SEARCH"]["cn"]),
            "identityStatus": row["identity_status"], "coordinateStatus": row["coordinate_status"],
            "resolutionStatus": row["google_resolution_status"], "entityType": row["entity_type"],
            "criticality": row["criticality"]}


def run_gate(rows: dict, dom_rows: list, country: str = "美国", contract_entries=None) -> list[str]:
    gate = copy.deepcopy(GATE)
    if contract_entries is not None:
        gate["consistency_checks"]["dataset_vs_dom"]["alias_contract"]["entries"] = contract_entries
    return mg422.dom_findings(rows, dom_rows, gate, SELECTION, country)


class AliasPositiveTests(unittest.TestCase):
    def contract_entry(self, alias_key: str, canonical_key: str, alias: dict, canonical: dict) -> dict:
        compared = [str(field) for field in CONTRACT["compared_fields"]]
        providers = [str(item) for item in SELECTION["ui"]["rendered_providers"]]
        _ok, _diff, digest = mg422.alias_identity(alias, canonical, compared, providers, SELECTION)
        return {"alias_key": alias_key, "alias_target_id": alias_key,
                "canonical_key": canonical_key, "canonical_target_id": canonical_key,
                "scope": "美国", "identical_fields_digest": digest}

    def test_canonical_button_covers_the_registered_alias(self):
        alias, canonical = same_address_pair(alias_of="旧金山|A CN")
        rows = {"旧金山|A EN": alias, "旧金山|A CN": canonical}
        entry = self.contract_entry("旧金山|A EN", "旧金山|A CN", alias, canonical)
        findings = run_gate(rows, [dom_row(canonical)], contract_entries=[entry])
        self.assertEqual(findings, [], "登记且逐项一致的 alias 不应再要求一颗自己的按钮：%s" % findings)

    def test_denominator_and_row_count_are_untouched(self):
        """§5：alias 不是删行。205 行仍在 dataset 里，只是期望按钮变成 200。"""
        dataset = json.loads((ALIASED / "california_v420" / "dataset_v422_aliased.json")
                             .read_text(encoding="utf-8"))
        rows = dataset["map_targets"]
        self.assertEqual(len(rows), 205, "分母被动了：alias 合同不允许减少任何一行")
        resolved, findings = mg422.resolve_aliases(rows, GATE, SELECTION, str(dataset["country"]))
        self.assertEqual(findings, [], "在册 5 条配对现算校验必须全过：%s" % findings[:3])
        expected = mg422.expected_dom_links(rows, SELECTION, resolved)
        self.assertEqual(len(resolved), 5)
        self.assertEqual(len(expected), 200)
        self.assertEqual(200 + 5, len(rows), "205 = 200 canonical + 5 alias 的等式必须成立")

    def test_philippines_has_no_alias_and_keeps_198(self):
        dataset = json.loads((ALIASED / "philippines_v419" / "dataset_v422_aliased.json")
                             .read_text(encoding="utf-8"))
        rows = dataset["map_targets"]
        resolved, findings = mg422.resolve_aliases(rows, GATE, SELECTION, str(dataset["country"]))
        self.assertEqual((len(rows), len(resolved), findings), (198, 0, []),
                         "加州的配对不该被拿去判菲律宾（scope 漂移就会报 5 条不存在）")
        self.assertEqual(len(mg422.expected_dom_links(rows, SELECTION, resolved)), 198)

    def test_registry_entries_equal_a_fresh_measurement(self):
        """登记里的每一条都必须还能被现场重测出来，指纹过期就是漂移。"""
        dataset = json.loads((ALIASED / "california_v420" / "dataset_v422_aliased.json")
                             .read_text(encoding="utf-8"))
        rows = dataset["map_targets"]
        compared = [str(field) for field in CONTRACT["compared_fields"]]
        providers = [str(item) for item in SELECTION["ui"]["rendered_providers"]]
        self.assertEqual(len(CONTRACT["entries"]), 5, "登记条目数与实测量不一致")
        for entry in CONTRACT["entries"]:
            alias, canonical = rows.get(entry["alias_key"]), rows.get(entry["canonical_key"])
            self.assertIsNotNone(alias, "%s 已不在 dataset 里，登记过期" % entry["alias_key"])
            self.assertIsNotNone(canonical, "%s 已不在 dataset 里，登记过期" % entry["canonical_key"])
            identical, differing, digest = mg422.alias_identity(
                alias, canonical, compared, providers, SELECTION)
            self.assertTrue(identical, "%s→%s 现在不一致：%s" % (entry["alias_key"],
                                                                entry["canonical_key"], differing))
            self.assertEqual(digest, str(entry["identical_fields_digest"]),
                             "%s 的指纹与现算不符：字段变过就必须重新登记" % entry["alias_key"])
            self.assertEqual(str(alias.get("alias_of") or ""), entry["canonical_key"],
                             "数据行的 alias_of 必须等于登记，两处一起改才算登记")

    def test_alias_row_keeps_its_own_honest_state(self):
        """alias 不是状态洗涤：行的身份/坐标/核验状态仍逐行留在载荷里，报告按 205 行出。"""
        alias = target("旧金山|A EN", alias_of="旧金山|A CN", identity_status="VERIFIED")
        self.assertEqual(alias["identity_status"], "VERIFIED")
        self.assertEqual(alias["link_mode"], "NAMED_SEARCH")
        self.assertTrue(alias["map_link_url"])

    def test_extra_button_for_an_alias_is_still_a_violation(self):
        """§5 不许加重复按钮：alias 自己再长出一颗按钮＝DOM 出现期望集之外的按钮。"""
        alias, canonical = same_address_pair(alias_of="旧金山|A CN")
        rows = {"旧金山|A EN": alias, "旧金山|A CN": canonical}
        compared = [str(field) for field in CONTRACT["compared_fields"]]
        providers = [str(item) for item in SELECTION["ui"]["rendered_providers"]]
        _ok, _d, digest = mg422.alias_identity(alias, canonical, compared, providers, SELECTION)
        entry = {"alias_key": "旧金山|A EN", "canonical_key": "旧金山|A CN", "scope": "美国",
                 "identical_fields_digest": digest}
        findings = run_gate(rows, [dom_row(canonical), dom_row(alias)], contract_entries=[entry])
        self.assertTrue([item for item in findings if item.startswith("GATE_DOM_HREF_UNEXPECTED")],
                        "两颗一样的按钮不是收口，是把同址双键暴露给读者两次：%s" % findings)


class AliasNegativeTests(unittest.TestCase):
    def entry_for(self, alias_key: str, canonical_key: str, alias: dict, canonical: dict,
                  **over) -> dict:
        compared = [str(field) for field in CONTRACT["compared_fields"]]
        providers = [str(item) for item in SELECTION["ui"]["rendered_providers"]]
        _ok, _diff, digest = mg422.alias_identity(alias, canonical, compared, providers, SELECTION)
        entry = {"alias_key": alias_key, "canonical_key": canonical_key, "scope": "美国",
                 "identical_fields_digest": digest}
        entry.update(over)
        return entry

    def test_cycle_is_blocked_and_grants_no_exemption(self):
        url = "https://www.google.com/maps/search/?api=1&query=Two%20Names"
        # 两行必须「除键以外全等」，否则新判据会先在一致性上失败，测不到回环这一支
        a = target("旧金山|A", href=url, name="同一处 POI", alias_of="旧金山|B")
        b = target("旧金山|B", href=url, name="同一处 POI", alias_of="旧金山|A")
        rows = {"旧金山|A": a, "旧金山|B": b}
        entries = [self.entry_for("旧金山|A", "旧金山|B", a, b),
                   self.entry_for("旧金山|B", "旧金山|A", b, a)]
        findings = run_gate(rows, [], contract_entries=entries)
        cycles = [item for item in findings if item.startswith("GATE_DOM_ALIAS_CYCLE")]
        self.assertTrue(cycles, "互相指向必须当场认出回环")
        self.assertIn("不获豁免", cycles[0])
        # 回环不豁免 ⇒ 两行的按钮期望都还在，DOM 空着就各报一条缺
        self.assertEqual(len([item for item in findings if item.startswith("GATE_DOM_HREF_MISSING")]),
                         2, "回环里的行不能靠对方顶替：%s" % findings)

    def test_self_reference_is_a_cycle_too(self):
        alias, canonical = same_address_pair(alias_of="旧金山|A EN")
        entry = self.entry_for("旧金山|A EN", "旧金山|A EN", alias, alias)
        findings = run_gate({"旧金山|A EN": alias, "旧金山|A CN": canonical}, [dom_row(canonical)],
                            contract_entries=[entry])
        self.assertTrue([item for item in findings if item.startswith("GATE_DOM_ALIAS_CYCLE")])

    def test_missing_target_is_blocked(self):
        alias, canonical = same_address_pair(alias_of="旧金山|A CN")
        entry = self.entry_for("旧金山|A EN", "旧金山|A CN", alias, canonical)
        rows = {"旧金山|A CN": canonical}                    # alias 行不存在
        findings = run_gate(rows, [dom_row(canonical)], contract_entries=[entry])
        self.assertTrue([item for item in findings
                         if item.startswith("GATE_DOM_ALIAS_TARGET_MISSING")],
                        "登记的配对行不在 dataset 里必须报：%s" % findings)

    def test_url_mismatch_is_blocked(self):
        alias, canonical = same_address_pair(alias_of="旧金山|A CN")
        other = "https://www.google.com/maps/search/?api=1&query=Different"
        alias["map_link_url"] = other
        alias["google_url"] = other
        alias["map_link_by_provider"]["google"]["map_link_url"] = other
        entry = self.entry_for("旧金山|A EN", "旧金山|A CN",
                               *same_address_pair(alias_of="旧金山|A CN")[:1], canonical)
        rows = {"旧金山|A EN": alias, "旧金山|A CN": canonical}
        findings = run_gate(rows, [dom_row(canonical)], contract_entries=[entry])
        self.assertTrue([item for item in findings if item.startswith("GATE_DOM_ALIAS_CONFLICT")],
                        "href 变了还按 alias 豁免，等于用一颗按钮盖住两个不同落点：%s" % findings)

    def test_status_mismatch_is_blocked(self):
        alias, canonical = same_address_pair(alias_of="旧金山|A CN", identity_status="VERIFIED")
        honest_alias, _ = same_address_pair(alias_of="旧金山|A CN")
        entry = self.entry_for("旧金山|A EN", "旧金山|A CN", honest_alias, canonical)
        rows = {"旧金山|A EN": alias, "旧金山|A CN": canonical}
        findings = run_gate(rows, [dom_row(canonical)], contract_entries=[entry])
        conflict = [item for item in findings if item.startswith("GATE_DOM_ALIAS_CONFLICT")]
        self.assertTrue(conflict, "状态不一致就不许共用按钮（§1 要求状态完全一致）")
        self.assertIn("identity_status", conflict[0])

    def test_stale_digest_is_blocked(self):
        alias, canonical = same_address_pair(alias_of="旧金山|A CN")
        entry = self.entry_for("旧金山|A EN", "旧金山|A CN", alias, canonical)
        entry["identical_fields_digest"] = "0" * 64
        rows = {"旧金山|A EN": alias, "旧金山|A CN": canonical}
        findings = run_gate(rows, [dom_row(canonical)], contract_entries=[entry])
        self.assertTrue([item for item in findings if item.startswith("GATE_DOM_ALIAS_CONFLICT")],
                        "登记指纹过期＝字段集合后来变过，必须重新测量登记：%s" % findings)

    def test_unregistered_same_address_duplicate_still_blocks(self):
        """§5 的核心牙齿：没登记的同址双键不会因为「长得一样」而自动获得豁免。"""
        alias, canonical = same_address_pair()               # 完全等价但没有登记，也没声明 alias_of
        rows = {"旧金山|A EN": alias, "旧金山|A CN": canonical}
        findings = run_gate(rows, [dom_row(canonical)])
        self.assertTrue([item for item in findings if item.startswith("GATE_DOM_HREF_MISSING")],
                        "运行时按坐标/名称自动并键就是业主明令禁止的猜测：%s" % findings)

    def test_dataset_declares_alias_that_registry_does_not_list(self):
        alias, canonical = same_address_pair(alias_of="旧金山|A CN")
        rows = {"旧金山|A EN": alias, "旧金山|A CN": canonical}
        findings = run_gate(rows, [dom_row(canonical)], contract_entries=[])
        self.assertTrue([item for item in findings if item.startswith("GATE_DOM_ALIAS_UNREGISTERED")],
                        "数据里冒出来的 alias 必须先在登记里出现：%s" % findings)

    def test_registry_lists_pair_that_data_does_not_declare(self):
        alias, canonical = same_address_pair()               # 数据行没写 alias_of
        entry = self.entry_for("旧金山|A EN", "旧金山|A CN",
                               *same_address_pair(alias_of="旧金山|A CN"), )
        rows = {"旧金山|A EN": alias, "旧金山|A CN": canonical}
        findings = run_gate(rows, [dom_row(canonical)], contract_entries=[entry])
        self.assertTrue([item for item in findings if item.startswith("GATE_DOM_ALIAS_NOT_DECLARED")],
                        "登记改了但数据没改＝两处漂移，必须当场报：%s" % findings)


class TightenedEquivalenceTests(unittest.TestCase):
    """V6-R1：判据只许收紧。五个新入指纹的字段各自有负测，漂移即 CONFLICT 且不获豁免。

    每条负测都验两件事：① `GATE_DOM_ALIAS_CONFLICT` 当场报出是哪个字段；
    ② 这条 alias 回到「DOM 应有自己的按钮」的期望集 ⇒ 同一次对账里必须出现
    `GATE_DOM_HREF_MISSING`。第 ② 条才是失败闭合的 proof：光报错但不收回豁免，
    「登记过一致」就还是能靠一颗按钮盖住两个落点。
    """

    def drift(self, field: str, mutate) -> list[str]:
        alias, canonical = same_address_pair(alias_of="旧金山|A CN",
                                             link_notices=["key_target_unverified"],
                                             evidence=[{"kind": "review", "ref": "evidence/x.txt"}])
        honest_alias, _ = same_address_pair(alias_of="旧金山|A CN",
                                            link_notices=["key_target_unverified"],
                                            evidence=[{"kind": "review", "ref": "evidence/x.txt"}])
        compared = [str(item) for item in CONTRACT["compared_fields"]]
        providers = [str(item) for item in SELECTION["ui"]["rendered_providers"]]
        _ok, _diff, digest = mg422.alias_identity(honest_alias, canonical, compared, providers,
                                                  SELECTION)
        entry = {"alias_key": "旧金山|A EN", "canonical_key": "旧金山|A CN", "scope": "美国",
                 "identical_fields_digest": digest}
        mutate(alias, canonical)
        findings = run_gate({"旧金山|A EN": alias, "旧金山|A CN": canonical},
                            [dom_row(canonical)], contract_entries=[entry])
        conflict = [item for item in findings if item.startswith("GATE_DOM_ALIAS_CONFLICT")]
        self.assertTrue(conflict, "%s 漂移必须当场报 ALIAS_CONFLICT：%s" % (field, findings))
        self.assertIn(field, conflict[0], "%s 的冲突要点了字段名：%s" % (field, conflict[0][:160]))
        missing = [item for item in findings if item.startswith("GATE_DOM_HREF_MISSING")]
        self.assertTrue(missing, "%s 漂移后该 alias 不获豁免，应回到缺按钮阻断：%s"
                        % (field, findings))
        self.assertEqual(len([item for item in missing if "旧金山|A EN" in item]), 1,
                         "缺按钮那一条必须点到 alias 行自己：%s" % missing)
        return findings

    def test_canonical_name_drift_is_blocked(self):
        self.drift("canonical_name", lambda a, c: a.update(canonical_name="另一个正式名"))

    def test_display_name_drift_is_blocked(self):
        self.drift("display_name", lambda a, c: a.update(display_name="另一个显示名"))

    def test_names_dict_drift_is_blocked(self):
        # dict 只改一个子键也要抓得到：这条正是 str(dict) 时代最容易糊过去的形状
        def mutate(alias, _canonical):
            alias["names"]["en"] = "Another English Name"
        self.drift("names", mutate)

    def test_link_notices_drift_is_blocked(self):
        self.drift("link_notices",
                   lambda a, _c: a.update(link_notices=["key_target_unverified",
                                                        "ambiguous_multiple_results"]))

    def test_evidence_drift_is_blocked(self):
        def mutate(alias, _c):
            alias["evidence"] = [{"kind": "review", "ref": "evidence/other.txt"}]
        self.drift("evidence", mutate)

    def test_normalization_object_key_order_is_irrelevant(self):
        a = mg422.normalized_field_value({"en": "x", "cn": "y"})
        b = mg422.normalized_field_value({"cn": "y", "en": "x"})
        self.assertEqual(a, b, "同一份 dict 换个写入顺序不该变成「字段不一致」")

    def test_normalization_array_order_is_relevant(self):
        a = mg422.normalized_field_value(["one", "two"])
        b = mg422.normalized_field_value(["two", "one"])
        self.assertNotEqual(a, b, "link_notices 的次序是读者看到提示的次序，重排算不同")

    def test_normalization_absent_is_not_empty(self):
        absent = mg422.normalized_field_value(mg422._ABSENT)
        for present in ([], {}, None, ""):
            self.assertNotEqual(absent, mg422.normalized_field_value(present),
                                 "「这格不存在」与「存在但为空」是两种状态，不能折成一个值")

    def test_alias_identity_does_not_stringify_containers(self):
        """判据不许退回 str(dict)：那会把键序当值，也会把嵌套差异糊平。"""
        import ast
        import inspect
        source = inspect.getsource(mg422.alias_identity)
        tree = ast.parse(source.strip())
        rendered = ast.dump(tree)
        self.assertIn("normalized_field_value", rendered,
                      "alias_identity 必须走规范化函数，而不是就地 str 拼")
        for forbidden in ("str(alias.get(", "str(canonical.get("):
            self.assertNotIn(forbidden, source, "比较里出现了 %s：规范化实现被绕开了" % forbidden)

    def test_the_five_registered_pairs_pass_the_tighter_rule_in_real_data(self):
        """业主 §3 的事实面：五组真实配对的这五个字段确实相同——量出来，不是登记里写着。"""
        dataset = json.loads((ALIASED / "california_v420" / "dataset_v422_aliased.json")
                             .read_text(encoding="utf-8"))
        rows = dataset["map_targets"]
        fields = ["canonical_name", "display_name", "names", "link_notices", "evidence"]
        for entry in CONTRACT["entries"]:
            alias, canonical = rows[entry["alias_key"]], rows[entry["canonical_key"]]
            for field in fields:
                self.assertEqual(
                    mg422.normalized_field_value(alias.get(field, mg422._ABSENT)),
                    mg422.normalized_field_value(canonical.get(field, mg422._ABSENT)),
                    "%s 的 %s 与 canonical 不同：这条配对在新判据下站不住，"
                    "必须重新测量登记而不是放宽判据" % (entry["alias_key"], field))

    def test_registry_exclusions_are_the_allowed_five_only(self):
        exclusions = {row["field"]: row for row in CONTRACT["not_compared"]}
        self.assertEqual(set(exclusions), {"target_id", "alias_of", "migration", "quarantine",
                                           "unresolved_fields"},
                         "排除面只能是你点名的那五项（外加本轮实测确实逐行不同的审计轨迹）")
        for field, row in exclusions.items():
            self.assertTrue(str(row.get("reason") or "").strip(), "%s 没有逐项理由" % field)
            self.assertTrue(str(row.get("measured_2026_10_31") or "").strip(),
                            "%s 的理由没带实测值" % field)

    def test_registry_compared_fields_cover_the_five(self):
        compared = [str(item) for item in CONTRACT["compared_fields"]]
        self.assertEqual(len(compared), 23, "compared_fields 应是 18 + 5 = 23 项")
        for field in ("canonical_name", "display_name", "names", "link_notices", "evidence"):
            self.assertIn(field, compared, "%s 必须进指纹" % field)
        self.assertEqual(CONTRACT["normalization"]["implemented_by"],
                         "scripts/map_gate_v422.py::normalized_field_value")

    def test_wrong_not_compared_why_is_not_still_in_the_registry(self):
        """旧的没量过的说法只能作为「已撤回」存在，不能还写在正面判据里。"""
        why = str(CONTRACT["not_compared_why"])
        withdrawn = CONTRACT.get("withdrawn_claim") or {}
        self.assertNotIn("本来就在名字", why, "正面判据里不许再断言那条没量过的说法")
        self.assertIn("本来就在名字", str(withdrawn.get("was") or ""),
                      "撤回要有记录：说清旧文字主张过什么")
        self.assertTrue(str(withdrawn.get("why_wrong") or "").strip())
        self.assertTrue(str(withdrawn.get("measured_2026_10_31") or "").strip())
        for phrase in ("canonical_name / display_name / names", "相同", "字典键", "target_id"):
            self.assertIn(phrase, why, "更正后的正面文字要说清哪里相同、哪里真的不同：%s" % phrase)


class FormalProvenanceTests(unittest.TestCase):
    def test_formal_run_without_provenance_is_blocked(self):
        dataset = pair_dataset({}, )
        dataset.pop("map_link_selection")
        findings = mg422.provenance_findings(dataset, SELECTION, GATE, formal=True)
        self.assertEqual(len(findings), 1)
        self.assertTrue(findings[0].startswith("GATE_DOM_PROVENANCE_MISSING_FORMAL"))
        self.assertIn(str(SELECTION["selection_version"]), findings[0])

    def test_formal_run_with_wrong_version_is_blocked(self):
        dataset = pair_dataset({}, )
        dataset["map_link_selection"] = {"selection_version": "v421-previous"}
        findings = mg422.provenance_findings(dataset, SELECTION, GATE, formal=True)
        self.assertEqual([item.split("|")[0] for item in findings],
                         ["GATE_DOM_PROVENANCE_VERSION_STALE"])

    def test_formal_run_with_current_version_is_clean(self):
        self.assertEqual(mg422.provenance_findings(pair_dataset({}), SELECTION, GATE,
                                                   formal=True), [])

    def test_compatibility_path_keeps_not_applicable(self):
        """非正式（历史产物/夹具）不阻断——上一版数据不该被本版规则判死。"""
        self.assertEqual(mg422.provenance_findings({"map_targets": {}}, SELECTION, GATE,
                                                   formal=False), [])

    def test_formal_marker_is_read_from_the_registry_not_hardcoded(self):
        marker = mg422.selection_provenance_gate(GATE)
        self.assertEqual(marker.get("formal_env_var"), "TRAVEL_SCOPE_FORMAL_RUN")
        import os
        name, value = str(marker["formal_env_var"]), str(marker.get("formal_env_value") or "1")
        saved = os.environ.get(name)
        try:
            os.environ[name] = value
            self.assertTrue(mg422.is_formal_run(GATE))
            os.environ[name] = "0"
            self.assertFalse(mg422.is_formal_run(GATE))
            os.environ.pop(name, None)
            self.assertFalse(mg422.is_formal_run(GATE))
        finally:
            if saved is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = saved


class Section81IntegrationTests(unittest.TestCase):
    class StubPage:
        def __init__(self, rows):
            self.rows = rows

        def evaluate(self, script):
            assert script is vq.MAP_DOM_ROWS_JS
            return self.rows

    def check(self, dataset, rows):
        failures, result = [], {}
        vq.check_map_dom_dataset_consistency(self.StubPage(rows), dataset, failures, result)
        return failures, result["map_dom_dataset_consistency"]

    def test_real_page_reconciles_with_zero_findings_for_both_countries(self):
        """§4 的在册版本：读者页里真正渲染的按钮与 dataset 期望集必须逐国家对上。"""
        import os
        saved = os.environ.get("TRAVEL_SCOPE_FORMAL_RUN")
        os.environ["TRAVEL_SCOPE_FORMAL_RUN"] = "1"
        try:
            for label, expect_rows, expect_buttons in (("california_v420", 205, 200),
                                                        ("philippines_v419", 198, 198)):
                dataset = json.loads((ALIASED / label / "dataset_v422_aliased.json")
                                     .read_text(encoding="utf-8"))
                rows = dataset["map_targets"]
                resolved, _ = mg422.resolve_aliases(rows, GATE, SELECTION, str(dataset["country"]))
                expected = mg422.expected_dom_links(rows, SELECTION, resolved)
                dom_rows = [dom_row(row) for (target_id, _p) in sorted(expected)
                            for row in [rows.get(target_id) or next(
                                r for r in rows.values()
                                if str(r.get("target_id") or "") == target_id)]]
                failures, node = self.check(dataset, dom_rows)
                self.assertEqual(node["enforced"], True, label)
                self.assertEqual(node["dataset_rows"], expect_rows, label)
                self.assertEqual(node["expected_buttons"], expect_buttons, label)
                self.assertEqual(node["findings_total"], 0,
                                 "%s 全量对账不为 0：%s" % (label, node["findings"][:3]))
        finally:
            if saved is None:
                os.environ.pop("TRAVEL_SCOPE_FORMAL_RUN", None)
            else:
                os.environ["TRAVEL_SCOPE_FORMAL_RUN"] = saved

    def test_formal_page_missing_provenance_fails_even_when_not_enforced(self):
        dataset = {"country": "美国", "map_targets": {"a": target("a")},
                   "map_link_selection": {}}
        import os
        saved = os.environ.get("TRAVEL_SCOPE_FORMAL_RUN")
        os.environ["TRAVEL_SCOPE_FORMAL_RUN"] = "1"
        try:
            failures, node = self.check(dataset, [dom_row(dataset["map_targets"]["a"])])
        finally:
            if saved is None:
                os.environ.pop("TRAVEL_SCOPE_FORMAL_RUN", None)
            else:
                os.environ["TRAVEL_SCOPE_FORMAL_RUN"] = saved
        self.assertFalse(node["enforced"], "没有血缘仍然不能假装比对过")
        self.assertTrue([item for item in failures
                         if item.startswith("GATE_DOM_PROVENANCE_MISSING_FORMAL")],
                        "但正式 run 必须为这一条阻断，而不是留一句不适用就走：%s" % failures)


class CodeRegistrationTests(unittest.TestCase):
    NEW_CODES = ["GATE_DOM_ALIAS_TARGET_MISSING", "GATE_DOM_ALIAS_CYCLE", "GATE_DOM_ALIAS_CONFLICT",
                 "GATE_DOM_ALIAS_UNREGISTERED", "GATE_DOM_ALIAS_NOT_DECLARED",
                 "GATE_DOM_PROVENANCE_MISSING_FORMAL", "GATE_DOM_PROVENANCE_VERSION_STALE"]

    def test_new_codes_are_registered_as_blocking_and_in_the_8_1_list(self):
        dom = GATE["consistency_checks"]["dataset_vs_dom"]
        for code in self.NEW_CODES:
            self.assertIn(code, dom["codes"], "%s 必须进 §8.1 一致性名单" % code)
            self.assertEqual(mg422.severity_of(code, GATE), "blocking",
                             "%s 只能是整批阻断：降级它就是把缺口变成提醒" % code)

    def test_alias_contract_is_self_describing(self):
        for key in ("ratified_by", "field", "semantics", "implemented_by", "pairing_provenance",
                    "validation", "compared_fields", "not_compared", "not_compared_why",
                    "normalization", "entries", "scope_field",
                    "must_not_be_closed_by", "measured_2026_10_31"):
            self.assertTrue(CONTRACT.get(key), "alias 合同缺键 %s" % key)
        self.assertEqual(CONTRACT["field"], "alias_of")
        self.assertEqual(len(CONTRACT["must_not_be_closed_by"]), 4,
                         "「不许怎么变绿」少一条就是给下一轮留口子")

    def test_alias_of_is_read_in_exactly_one_place(self):
        """§9 禁止第二套规则：整个发布树里只有 resolve_aliases 消费 alias_of。"""
        readers = []
        for path in sorted((SCRIPTS).glob("*.py")):
            if path.name.startswith("test_"):
                continue
            if "alias_of" in path.read_text(encoding="utf-8"):
                readers.append(path.name)
        self.assertEqual(readers, ["map_gate_v422.py"],
                         "又有人实现一遍 alias 判定：渲染器或 QA 一旦自带配对，登记就成了摆设")

    def test_schema_registers_the_field(self):
        policy = json.loads((ROOT / "references" / "data-model.json").read_text(encoding="utf-8"))
        block = policy["map_target_alias_contract"]
        self.assertEqual(block["field"], "alias_of")
        self.assertIn("must_not_be_inferred", block)
        self.assertNotIn("alias_of", policy["map_target_required_fields"],
                         "把 alias_of 设成必填会让 v4.2.1 只读产物凭空多 403 条违规")


if __name__ == "__main__":
    unittest.main()
