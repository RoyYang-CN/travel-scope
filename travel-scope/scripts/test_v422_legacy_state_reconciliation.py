# -*- coding: utf-8 -*-
"""v4.2.2 V6-L：legacy 状态收口（把与四维诚实状态矛盾的旧声明降到一致）＋门禁改向不再被旧规则屏蔽。

V6-D 第一次端到端跑（正式生成）暴露了两件事，都不是图片问题：

  1. 加州 205 条 map_target 里 151 条 `canonical_name` 仍是 v4.2.0 造的 'California Venue'，
     而**同一行**的 names.en 里就装着真名（Monterey Bay Aquarium）；205 条全部写着
     verification_status=verified / target_level=verified_coordinate，而 identity_status=UNVERIFIED。
  2. 正式门禁读的是 legacy 字段（require_exact 只认 verified_*），于是 v4.2.2 诚实四维里
     一条 NAMED_SEARCH（「搜索此地点（落点未核验）」）都出不去——地图改向被 v4.2.1 门禁屏蔽。

业主 2026-10-30 两条裁决：接回该行自己的名（不做外部查询）；按 V1R 收窄旧规则。
本文件把落地后的边界钉住：只降级不升格、只接回有来源的名、原值留在该行 migration 台账里、
W2 的隔离记录一条不少；可出货模式集合只在登记里写一份，门禁读它。

全部用构造行，不读历史 run、不读 .temp 证据、不写发布树。
"""
from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
ROOT = SCRIPTS.parent

import data_model                   # noqa: E402
import map_contract                 # noqa: E402
import map_link_selector as mls     # noqa: E402

SEL_PATH = ROOT / "references" / "map-link-selection.json"
SEL = json.loads(SEL_PATH.read_text(encoding="utf-8"))
RECON = SEL["legacy_state_reconciliation"]
DELIVERABLE = SEL["deliverable_link_modes"]["modes"]


def honest_row(**override):
    """一条完整、自相矛盾尽可能少的行：默认是「未核验但名字有来源」的出货形态。"""
    row = {
        "target_id": "t-1",
        "destination": "蒙特雷与卡梅尔",
        "canonical_name": "Monterey Bay Aquarium",
        "names": {"en": "Monterey Bay Aquarium", "zh": "蒙特雷湾水族馆"},
        "display_name": "Monterey Bay Aquarium",
        "entity_type": "named_entity",
        "target_level": "search_candidate",
        "verification_status": "unverified",
        "identity_status": "UNVERIFIED",
        "google_resolution_status": "NOT_OBSERVED",
        "coordinate_status": "VERIFIED",
        "coords": "36.6181231,-121.9015121",
        "google_url": "https://www.google.com/maps/search/?api=1&query=Monterey+Bay+Aquarium",
        "quarantine": [],
        "unresolved_fields": [],
        "country_code": "US",
        "category": "attraction",
    }
    row.update(override)
    return row


def with_selection(row, key="蒙特雷与卡梅尔|蒙特雷湾水族馆"):
    """把行喂给现行选择器，把它自己该写的 v4.2.2 字段填回去（不手抄结论）。

    和迁移器的装配一致：单值 link_* 取 primary_provider 的结论，容器由
    select_all_providers 一次装配——只填一半的夹具会让收口多写一次容器，测的就不是产品行为。
    """
    container = mls.select_all_providers(key, row)
    primary = str(SEL.get("primary_provider") or "google")
    merged = dict(row)
    for field, value in container[primary].items():
        merged[field] = value
    merged["map_link_by_provider"] = container
    return merged


class RegistryTests(unittest.TestCase):
    def test_reconciliation_rule_is_registered_before_it_is_implemented(self):
        for key in mls.RECONCILE_REQUIRED_KEYS:
            self.assertTrue(RECON.get(key), "legacy_state_reconciliation 缺 %s" % key)
        self.assertIn("map_link_selector.py::reconcile_legacy_state", RECON["implemented_by"])

    def test_missing_registry_key_blocks_instead_of_guessing(self):
        broken = copy.deepcopy(SEL)
        broken["legacy_state_reconciliation"].pop("verification_status_after")
        with self.assertRaises(mls.SelectionConfigError):
            mls.reconcile_legacy_state("k", honest_row(), sel=broken)
        missing_block = copy.deepcopy(SEL)
        missing_block.pop("legacy_state_reconciliation")
        with self.assertRaises(mls.SelectionConfigError):
            mls.reconcile_legacy_state("k", honest_row(), sel=missing_block)

    def test_deliverable_modes_are_registered_once_and_read_by_the_gate(self):
        self.assertEqual(sorted(DELIVERABLE),
                         ["NAMED_SEARCH", "PUBLISHER_ENTITY_LINK"])
        source = (SCRIPTS / "map_contract.py").read_text(encoding="utf-8")
        self.assertIn('"deliverable_link_modes"', source,
                      "可出货模式如果在门禁里再写一份字面量，登记一改门禁就静默按旧集合判")


class ReconcileNameTests(unittest.TestCase):
    def test_fabricated_name_is_relinked_from_the_row_s_own_source(self):
        row = honest_row(canonical_name="California Venue")
        fixed, actions = mls.reconcile_legacy_state("k", row)
        self.assertEqual(fixed["canonical_name"], "Monterey Bay Aquarium")
        reasons = [item["reason"] for item in actions]
        self.assertIn("RELINK_FROM_NAMES_EN", reasons)
        ledger = fixed["migration"]["legacy_state_reconciliation"]["fields"]["canonical_name"]
        self.assertEqual(ledger["before"], "California Venue",
                         "接回之后必须还能看见原来那条假名，否则审计面就丢了缺陷记录")

    def test_name_without_any_source_is_never_invented(self):
        row = honest_row(canonical_name="California Venue", names={}, display_name="")
        fixed, actions = mls.reconcile_legacy_state("k", row)
        self.assertEqual(fixed["canonical_name"], "California Venue")
        self.assertFalse([a for a in actions if a["field"] == "canonical_name"],
                         "没有来源字段可接时必须保持原样，由门禁继续报错——改数据不能替读者编名字")

    def test_input_row_is_never_mutated(self):
        row = honest_row(canonical_name="California Venue",
                         target_level="verified_coordinate", verification_status="verified",
                         source_url="https://www.google.com/maps/search/?api=1&query=California+Venue")
        row["quarantine"] = [{"reason_code": RECON["self_attestation_reason_code"],
                              "note": "W2 实测"}]
        before = copy.deepcopy(row)
        mls.reconcile_legacy_state("k", row)
        self.assertEqual(row, before, "入参被改了：调用方手里的原始行必须是那份未被降级的审计数据")

    def test_reconciling_twice_changes_nothing(self):
        row = with_selection(honest_row(canonical_name="California Venue",
                                        target_level="verified_coordinate",
                                        verification_status="verified"))
        once, first = mls.reconcile_legacy_state("k", row)
        twice, second = mls.reconcile_legacy_state("k", once)
        self.assertEqual(second, [], "第二次还在改就说明规则不稳定，重放必然逐字节不一致")
        self.assertTrue(first)


class ReconcileStateTests(unittest.TestCase):
    def promoted(self):
        row = honest_row(target_level="verified_coordinate", verification_status="verified")
        return with_selection(row)

    def test_contradictory_legacy_claim_is_downgraded_not_rewritten_upward(self):
        row = self.promoted()
        fixed, actions = mls.reconcile_legacy_state("k", row)
        fields = {item["field"]: item for item in actions}
        self.assertEqual(fixed["target_level"], RECON["level_vocabulary_after"]["named_search"])
        self.assertEqual(fixed["verification_status"], RECON["verification_status_after"])
        self.assertIn("DOWGRADE_TO_HONEST_LEVEL", fields["target_level"]["reason"])
        self.assertTrue(fixed["target_level"] not in map_contract.VERIFIED_LEVELS,
                        "降级后不得仍自称已核验档位")

    def test_verified_identity_keeps_its_legacy_level(self):
        row = honest_row(identity_status="VERIFIED", target_level="verified_coordinate",
                         verification_status="verified")
        row = with_selection(row)
        fixed, actions = mls.reconcile_legacy_state("k", row)
        self.assertEqual([a["field"] for a in actions], ["google_url"],
                         "身份已核验的行只允许被对齐 legacy URL 镜像（同一个决定的两种写法必须一致）；"
                         "状态、档位、核验声明一条都不许被动——无差别降级就是把数据改成门禁想要的样子")
        for field in ("identity_status", "target_level", "verification_status",
                      "coordinate_status", "google_resolution_status"):
            self.assertEqual(fixed[field], row[field], "%s 被改动就是拿改数据冒充核验" % field)

    def test_self_attested_source_url_dropped_only_when_w2_quarantined_it(self):
        url = "https://www.google.com/maps/search/?api=1&query=Monterey+Bay+Aquarium"
        quarantined = honest_row(google_url=url, source_url=url,
                                 quarantine=[{"reason_code":
                                             RECON["self_attestation_reason_code"]}])
        fixed, actions = mls.reconcile_legacy_state("k", quarantined)
        self.assertEqual(fixed["source_url"], "")
        self.assertIn("DROP_SELF_ATTESTED_SOURCE_URL", [a["reason"] for a in actions])

        quiet = honest_row(google_url=url, source_url=url, quarantine=[])
        fixed2, actions2 = mls.reconcile_legacy_state("k", quiet)
        self.assertEqual(fixed2["source_url"], url,
                         "没被隔离在案的自证链不能悄悄删掉：留着它让门禁报错才是可审计的结果")
        self.assertNotIn("DROP_SELF_ATTESTED_SOURCE_URL", [a["reason"] for a in actions2])


class GateAlignmentTests(unittest.TestCase):
    """门禁读登记的可出货模式；但 legacy-only 行（没有 v4.2.2 状态）仍按旧规则判。"""

    def target_errors(self, row, require_exact=True):
        return map_contract._target_errors("k", row, require_exact=require_exact,
                                           base_dir=None, is_international=True)

    def test_honest_named_search_ships_under_require_exact(self):
        row = with_selection(honest_row())
        errors = self.target_errors(row)
        self.assertFalse([e for e in errors if "不能作为正式跳转" in e],
                         "诚实具名搜索是可出货状态；旧档位规则在这里屏蔽改向就是窄指令第 6 条禁止的形态")
        self.assertFalse([e for e in errors if "包含中文汉字" in e])

    def test_local_name_in_search_url_is_no_longer_a_map_error(self):
        row = with_selection(honest_row(canonical_name="蓝波海滩度假酒店",
                                        names={"zh": "蓝波海滩度假酒店"},
                                        display_name="蓝波海滩度假酒店",
                                        google_url="https://www.google.com/maps/search/"
                                                   "?api=1&query=蓝波海滩度假酒店%2C+菲律宾"))
        errors = self.target_errors(row)
        self.assertFalse([e for e in errors if "包含中文汉字" in e],
                         "§4 禁止删中文猜英文名，本地正式名称必须能带着出货")

    def test_drifted_selection_state_is_rejected(self):
        row = with_selection(honest_row())
        drifted = dict(row)
        drifted["map_link_url"] = "http://www.google.com/maps/search/?api=1&query=Old+Stale+Link"
        errors = self.target_errors(drifted)
        self.assertTrue([e for e in errors if "map_link_url" in e or "https" in e],
                        "行里存的 URL 与当场重建不同必须报错——改向不得让旧 URL 借壳出货")

    def test_deliverable_mode_without_a_shippable_url_is_rejected(self):
        row = with_selection(honest_row())
        hollow = dict(row)
        hollow["map_link_url"] = ""
        hollow["google_url"] = ""
        errors = self.target_errors(hollow)
        self.assertTrue(errors, "可出货模式却没有 https 出货 URL，不能算通过")

    def test_legacy_only_row_is_still_judged_by_the_old_rule(self):
        row = honest_row(target_level="search_candidate")
        row.pop("link_mode", None)
        errors = self.target_errors(row)
        self.assertTrue([e for e in errors if "不能作为正式跳转" in e],
                        "没有 v4.2.2 选择状态的行（旧 run/夹具）仍按旧合同判，改向不能顺手放行")

    def test_unquarantined_placeholder_name_still_blocks_delivery(self):
        row = with_selection(honest_row(canonical_name="California Venue", quarantine=[]))
        errors = self.target_errors(row)
        self.assertTrue([e for e in errors if "伪造/残留串" in e],
                        "占位名门不因汉字门撤回一起消失")


class DenominatorTests(unittest.TestCase):
    def test_reconciliation_touches_only_registered_fields(self):
        allowed = set(RECON["downgrade_only_fields"]) | set(
            RECON["selection_rederivation"]["fields"])
        row = with_selection(honest_row(canonical_name="California Venue",
                                        target_level="verified_coordinate",
                                        verification_status="verified",
                                        source_url="https://www.google.com/maps/search/"
                                                   "?api=1&query=California+Venue",
                                        quarantine=[{"reason_code":
                                                     RECON["self_attestation_reason_code"]}]))
        fixed, actions = mls.reconcile_legacy_state("k", row)
        self.assertTrue(set(item["field"] for item in actions) <= allowed)
        changed = [key for key in fixed if key not in row or fixed[key] != row[key]]
        self.assertEqual(set(changed) - {"migration"}, allowed & set(changed),
                         "除登记字段与其 provenance 台账外不得有任何改动")

    def test_rebuilt_link_state_is_what_the_gate_then_accepts(self):
        """接回名字后必须连链状态一起重建：门禁要求「存的结论＝当场重算」，半途而废就是漂移。"""
        stale_url = ("https://www.google.com/maps/search/?api=1&query=California%20Venue"
                     "%2C%20California%2C%20United%20States")
        row = with_selection(honest_row(canonical_name="California Venue",
                                        target_level="verified_coordinate",
                                        verification_status="verified"))
        row = dict(row)
        row["map_link_url"] = stale_url            # V2R 当年用假名拼出来的那条旧 URL
        row["map_link_by_provider"]["google"] = dict(
            row["map_link_by_provider"]["google"], map_link_url=stale_url)
        fixed, actions = mls.reconcile_legacy_state("k", row)
        reasons = {item["field"]: item["reason"] for item in actions}
        self.assertEqual(reasons.get("map_link_url"), "REBUILD_LINK_STATE",
                         "名字换了却没重建 URL，读者点开的还是用假名拼出来的旧搜索串")
        self.assertNotIn("California%20Venue", str(fixed["map_link_url"]))
        self.assertNotIn("California Venue",
                         str(fixed["map_link_by_provider"]["google"]["map_link_url"]))
        errors = map_contract._target_errors("k", fixed, require_exact=True,
                                             base_dir=None, is_international=True)
        self.assertEqual(errors, [], "收口后的行必须能被现行正式门禁接受，残余错误都得说得出原因")

    def test_rebuild_is_idempotent_on_the_container(self):
        """容器要幂等：第二次收口不能再改一次，否则重放逐字节一致就无从谈起。"""
        row = with_selection(honest_row(canonical_name="California Venue",
                                        target_level="verified_coordinate",
                                        verification_status="verified"))
        one, first = mls.reconcile_legacy_state("k", row)
        two, second = mls.reconcile_legacy_state("k", one)
        self.assertEqual(second, [], "第二次仍在改：%s" % json.dumps(second, ensure_ascii=False)[:300])
        self.assertEqual(one["map_link_by_provider"], two["map_link_by_provider"])

    def test_rederivation_list_matches_the_selector_writable_fields(self):
        """登记的重建清单与选择器实际可写字段必须一模一样，漏一个字段就是漏重建。"""
        registered = set(RECON["selection_rederivation"]["fields"])
        mirrors = {"%s_url" % provider for provider in SEL["providers"]}
        self.assertEqual(registered, set(mls.WRITABLE_FIELDS) | {"map_link_by_provider"} | mirrors)
        self.assertEqual(set(RECON["selection_rederivation"]["legacy_url_mirrors"]["fields"]),
                         mirrors,
                         "镜像清单必须来自 provider 登记表，而不是在代码或文档里各写一份 google/apple")

    def test_legacy_url_mirror_equals_the_delivered_container_href(self):
        """V6-N：同一目标在产物里只能有一个答案。

        镜像不对齐时（V6-D 实测 403/403 行不一致，加州 5 条旧串还被多个 POI 共用），读者点的 href
        来自容器，而视觉门与审计读的是镜像——两侧对同一目标各执一词，任何一侧的 PASS 都不可信。
        """
        row = with_selection(honest_row(
            google_url="https://www.google.com/maps/search/?api=1&query=Stale%20Fabricated%20Name"))
        fixed, actions = mls.reconcile_legacy_state("k", row)
        delivered = fixed["map_link_by_provider"]["google"]["map_link_url"]
        self.assertEqual(fixed["google_url"], delivered,
                         "legacy 镜像仍与交付 href 不同：假名串还留在产物里")
        self.assertIn("REBUILD_LEGACY_URL_MIRROR",
                      [a["reason"] for a in actions if a["field"] == "google_url"])
        again, second = mls.reconcile_legacy_state("k", fixed)
        self.assertEqual([a for a in second if a["field"] == "google_url"], [],
                         "镜像重建必须幂等，否则重放逐字节一致做不到")

    def test_missing_selection_rederivation_blocks_reconciliation(self):
        broken = copy.deepcopy(SEL)
        broken["legacy_state_reconciliation"].pop("selection_rederivation")
        with self.assertRaises(mls.SelectionConfigError):
            mls.reconcile_legacy_state("k", honest_row(), sel=broken)

    def test_identity_and_resolution_status_are_never_written(self):
        row = with_selection(honest_row(target_level="verified_coordinate",
                                        verification_status="verified"))
        fixed, _ = mls.reconcile_legacy_state("k", row)
        for key in ("identity_status", "google_resolution_status", "coordinate_status"):
            self.assertEqual(fixed[key], row[key], "%s 被改动就是拿改数据冒充核验" % key)


if __name__ == "__main__":
    unittest.main()
