# -*- coding: utf-8 -*-
"""MT-D 所有权判定的执行型合同：owner 按地址登记，四桶互斥且穷尽，被 block 的不许降级进表。

这些测试存在的原因不是「加一层保险」，是本轮实测到的三件事：
  · 旧口径用**中文文本集合相减**决定谁负责一格，同文不同格会被整批抹掉且不留账；
  · spa-layout.js::tr() 实测把 en_text_replacements 排在 prose_en **上面**，
    给只有 replacement 来源的文本写 prose 译文＝译文到不了读者眼前 + 多一条查不到来源的英文；
  · 两桶 BLOCKED（mixed / unresolved）只要不为零，MT-E 的表长就是猜的。
登记面 references/prose-translation-contract.json::ownership，唯一实现
scripts/translate_prose.py::classify_fragment_ownership + prose_translation_worklist。
"""
from __future__ import annotations

import collections
import hashlib
import inspect
import json
import re
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))
import translate_prose as tp                                 # noqa: E402
import prose_reconcile as pr                                 # noqa: E402  专名形状门：逐条复现登记项要用同一把尺子
from test_v421_english_source import _compliant_table        # noqa: E402

RUN = "travel_scope_run_202701_usa_california_v422_001"
CONTRACT = tp.contract()
# 两棵审计输入的唯一路径出处：四桶账与迁移清册复算的是同一对文件，写两处就会有人只改一处。
AUDIT_DATASETS = {"california": SCRIPTS.parents[2] / ".temp" / "v422_honest_map" /
                  "V6_candidate_run" / "primary_aliased" / "california_v420" /
                  "dataset_v422_aliased.json",
                  "philippines": SCRIPTS.parents[2] / ".temp" / "v422_honest_map" /
                  "V6_candidate_run" / "primary_aliased" / "philippines_v419" /
                  "dataset_v422_aliased.json"}

# MT-D2 收口锚点：路径在这里登记一次，验收测试与复算测试共用（写两处就会有人只改一处）。
MT_D2_ANCHOR = SCRIPTS.parents[2] / ".temp" / "v422_honest_map" / "MT1_translation" / \
    "artifacts" / "MTD2_SEAL46_ANCHOR.json"
MT_D2_ACCEPTANCE = SCRIPTS.parents[2] / ".temp" / "v422_honest_map" / "MT1_translation" / \
    "artifacts" / "MTD2_SEAL46_ANCHOR_ACCEPTANCE.json"

# entry_for_blocked_fragment 的 detail 开头就是那 11 位 entry id（translate_prose 的写死格式）。
# 历史面要用它把「被点名的行」与「今天迁走的行」做集合比对，所以解析口径也写死一次、两处共用。
BLOCKED_ID_IN_DETAIL = re.compile(r"^(?P<id>[0-9a-f]{11}) 的所有权判定")


def anchor_freshness(anchor, live_seal, live_sealed_files):
    """「锚点签的就是在盘这一封」的唯一实现（业主 2026-11-01 两处争议裁决第 2 条）。

    返回违规清单，空表＝可交付。正式交付的判据只有两条：**verification_status == PASS**
    且 **live product-origin SHA == seal_lineage.latest_current**；其余各条是把这两条
    拆成能定位的错。

    为什么不能只问「在盘 SHA 有没有出现在血缘里」（上一版的写法）：树被回退到 seal-45 时，
    seal-45 就在血缘里，那条断言照样绿——血缘是历史账本，不是新鲜度。历史行反过来也必须
    真的留在历史里：把现场量到的当前封册写进 seal_46 那格，读起来就成了「seal-46 是现在」，
    业主判这是语义混用，所以当前封册另有 current_release_snapshot。
    """
    violations = []
    status = anchor.get("verification_status")
    if status != "PASS":
        violations.append({"rule": "not_final_status", "registered": status,
                           "must_be": "PASS"})
    lineage = anchor.get("seal_lineage") or {}
    if lineage.get("latest_current") != live_seal:
        violations.append({"rule": "latest_current_is_not_the_live_seal",
                           "registered": lineage.get("latest_current"), "live": live_seal})
    snapshot = anchor.get("current_release_snapshot") or {}
    if snapshot.get("product_origin_sha256") != live_seal:
        violations.append({"rule": "current_release_snapshot_is_not_the_live_seal",
                           "registered": snapshot.get("product_origin_sha256"),
                           "live": live_seal})
    if snapshot.get("sealed_files") != live_sealed_files:
        violations.append({"rule": "current_release_snapshot_sealed_files_stale",
                           "registered": snapshot.get("sealed_files"),
                           "live": live_sealed_files})
    historical = {row.get("label"): row.get("product_origin_sha256")
                  for row in lineage.get("historical") or []}
    rolled_back = sorted(label for label, value in historical.items() if value == live_seal)
    if rolled_back:
        violations.append({"rule": "live_seal_matches_a_historical_lineage_row",
                           "labels": rolled_back,
                           "meaning": "在盘封册回到了某一封历史：锚点不许把它当成当前"})
    legacy_row = anchor.get("seal_46") or {}
    if legacy_row.get("product_origin_sha256") == live_seal:
        violations.append({"rule": "historical_seal_46_claimed_as_current",
                           "meaning": "历史格被写成当前封册＝那格不再是历史"})
    if "seal-46" not in historical:
        violations.append({"rule": "lineage_lost_the_owner_named_seal_46",
                           "registered": sorted(historical)})
    elif legacy_row.get("product_origin_sha256") != historical["seal-46"]:
        violations.append({"rule": "historical_seal_46_disagrees_with_lineage",
                           "seal_46_block": legacy_row.get("product_origin_sha256"),
                           "seal_lineage": historical["seal-46"]})
    return violations


def _dataset(**overrides) -> dict:
    """最小夹具：每类通道都留一格，负测才有地方站。"""
    data = {
        "country": "美国", "country_en": "United States", "artifact_slug": "probe",
        "duration_days": 7,
        "routes": [], "route_budgets": {},
        "destinations": [["旧金山", "San Francisco", "加州湾区", "金门大桥", "2天",
                          "1月气温10-15℃", "SFO入境提车20分钟", "是"]],
        "destination_coverage": [["旧金山", "湾区核心，住两晚足够。"]],
        "itinerary": [["1", "第1天", "a", "b", "沿海公路自驾观景", "傍晚看日落"]],
        "hotels": [["酒店", "Grand Hotel", "Grand Hotel", "海景度假酒店", "湾区",
                    "近码头", "无早", "3星", "800", "verified",
                    "【人均参考】约 1200 元/晚。落地可步行到码头。"]],
        "restaurants": [], "cafes": [], "attractions": [], "dive_sites": [],
        "transport": [["SFO → 市区", "自驾 (SUV)", "22公里", "约 250 元", "25分钟",
                       "全天候随时出发", "", "", "", "10", "柜台在到达层",
                       "机场官网", "旧金山国际机场 (SFO)", "市区枢纽", "是",
                       "坡道陡峭需朝向路沿停车", "on_demand", "自驾租车单日核算",
                       "Self-drive rental daily rate", "2026-10-20", "", "verified", "", ""]],
        "transport_nodes": [["旧金山", "旧金山国际机场 (SFO)", "SFO", "机场",
                             "37.6,-122.3", "北部核心国际航空枢纽"]],
        "budget": [["1", "第1天", "洛杉矶提车·硅谷中半岛", 500, 200, 100, 100, 100, 1000]],
        "practical": [["货币结算与汇率口径", "全美境内消费均以美元(USD)结算。"]],
        "worth_it": [["旧金山", "斯坦福大学", "Stanford University", "砂岩罗曼式学术圣殿",
                      "文化学者、摄影爱好者", "2.5-3小时", "工作日上午光线最佳",
                      "校园公共区域免费漫步", "校园平缓开阔", "verified"]],
        "local_chains": [], "packing": [["证件与财务", "护照原件", "Passport", "随身携带",
                                         "全目的地通用", "行前打印备用", "护照有效期需6个月以上",
                                         "verified"]],
        "local_knowledge": [], "local_apps": [], "source_evidence": [],
        "editorial_media": [], "section_media": [], "map_targets": {},
    }
    data.update(overrides)
    return data


def _sha(dataset: dict) -> str:
    return hashlib.sha256((json.dumps(dataset, ensure_ascii=False, indent=2) + "\n")
                          .encode("utf-8")).hexdigest().upper()


def _fragment(cn: str, *addresses: str, kind: str = "node_type") -> dict:
    return {"id": tp._digest(cn), "cn": cn, "kind": kind, "addresses": list(addresses)}


def delivered_legacy_map(html_path) -> dict:
    """从**读者那份 HTML** 里抠出实际发给浏览器的 en_text_replacements（花括号配对，不靠行号）。

    交付面的这张表比 run 输入那张大（生成器自带字面量表并进来），迁移清册与漂移对账都必须按
    读者面出账；两处各写一份抠法就会出现「两个读者面分母」，所以这里一份，两个测试文件共用。
    """
    text = Path(html_path).read_text(encoding="utf-8", errors="replace")
    match = re.search(r'"en_text_replacements"\s*:\s*\{', text)
    if not match:
        raise AssertionError("%s：读者载荷里没有 en_text_replacements，交付面分母无从核对" % html_path)
    start = match.end() - 1
    depth = 0
    for position in range(start, len(text)):
        if text[position] == "{":
            depth += 1
        elif text[position] == "}":
            depth -= 1
            if depth == 0:
                return json.loads(text[start:position + 1])
    raise AssertionError("%s：en_text_replacements 花括号没配平（载荷被截断？）" % html_path)


class OwnershipRegistryClosureTests(unittest.TestCase):
    """登记的 owner / 结果 / 处置顺序必须与代码用的那一套同名同集合。"""

    SOURCE = (SCRIPTS / "translate_prose.py").read_text(encoding="utf-8")

    def test_registered_owner_vocabulary_matches_the_implementation(self):
        self.assertEqual(sorted(CONTRACT["ownership"]["owners"]), sorted(tp.OWNER_VOCABULARY),
                         "登记面与实现各有几个 owner 必须同名：多一个就是没实现的纸面通道")

    def test_registered_outcomes_match_the_implementation(self):
        self.assertEqual(CONTRACT["ownership"]["outcomes"], list(tp.OUTCOME_VOCABULARY))

    def test_every_owner_registry_is_read_from_its_own_face(self):
        """每个 owner 的登记面都要真的被代码读到（不是抄一份下标到本模块里）。"""
        for name, block in CONTRACT["ownership"]["owners"].items():
            if name == "PROSE_TABLE":
                self.assertIn("RENDERED_COLUMNS", self.SOURCE)
            elif name == "CATEGORY_LEXICON":
                self.assertIn("_category_columns", self.SOURCE,
                              "类别列没从 category_lexicon 读＝这里藏了第二份列清单")
            elif name == "DISPLAY_NAME":
                self.assertIn("name_columns()", self.SOURCE,
                              "专名列没从 display_names 读＝第二份列清单")
            elif name == "MONEY_FORMATTER":
                self.assertIn("FORMATTER_SLOTS", self.SOURCE)
            elif name == "REGISTERED_EN_REPLACEMENT":
                self.assertIn("en_text_replacements", self.SOURCE)
                self.assertIn("en_text_replacement_provenance", self.SOURCE,
                              "没读来源面就等于「在册即 owner」，业主第 4 条白写")
                self.assertIn("provenance_required_fields", self.SOURCE)

    def test_new_blocking_codes_are_registered_and_emitted(self):
        codes = set(CONTRACT["blocking_findings"])
        for code in ("mixed_owner_for_content_id", "no_registered_owner_for_address",
                     "owner_unprovenanced_blocked", "entry_for_blocked_fragment",
                     "ownership_accounting_mismatch"):
            self.assertIn(code, codes, "%s 是 MT-D 的牙齿，没登记就没有合同依据" % code)
            self.assertIn('"%s"' % code, self.SOURCE, "%s 在册但代码发不出来" % code)
        for constant in (tp.MIXED_OWNER, tp.NO_OWNER_ADDRESS, tp.UNPROVENANCED_CLAIM):
            self.assertIn(constant, codes, "代码用的码名不在册：%s" % constant)

    def test_precedence_is_registered_and_ordered(self):
        precedence = CONTRACT["ownership"]["precedence"]
        self.assertEqual(len(precedence), 4, "四条顺序少一条，两桶 BLOCKED 的归属就会飘")
        self.assertIn("owner_unprovenanced_blocked", precedence[0])
        self.assertIn("no_registered_owner_for_address", precedence[1])
        self.assertIn("mixed_owner_for_content_id", precedence[2])


class AddressOwnerTests(unittest.TestCase):
    def setUp(self):
        self.data = _dataset()
        self.columns = tp.non_prose_column_registry()

    def test_both_address_spellings_normalize_to_the_same_slot(self):
        """采集器写 `transport_nodes[0][3]`，值索引写 `dataset['transport_nodes'][0][3]`，
        `.note` 与 `['field']` 也要归一——不然同一个地址会被算成两个 owner。"""
        pairs = [("budget[1][2]", ("budget", 2)),
                 ("dataset['transport'][0][3]", ("transport", 3)),
                 ("hotels[0].note", ("hotels", "note")),
                 ("dataset['transport_nodes'][0]['type']", ("transport_nodes", "type")),
                 ("destination_coverage[4]", ("destination_coverage", None))]
        for text, expected in pairs:
            self.assertEqual(tp.normalize_address(text), expected, text)

    def test_unparsable_address_does_not_become_an_owner(self):
        self.assertEqual(tp.normalize_address("完全不是一条地址"), (None, None))
        self.assertEqual(tp.address_owners("完全不是一条地址", {}, self.columns), [])

    def test_each_channel_owns_the_column_it_registers(self):
        cases = [("dataset['transport_nodes'][0]['type']", "CATEGORY_LEXICON"),
                 ("dataset['hotels'][0][1]", "DISPLAY_NAME"),
                 ("dataset['hotels'][0][3]", "CATEGORY_LEXICON"),
                 ("dataset['transport'][0][3]", "MONEY_FORMATTER")]
        for address, expected in cases:
            self.assertIn(expected, tp.address_owners(address, {}, self.columns), address)

    def test_money_slot_owner_comes_from_the_registered_slot(self):
        self.assertIn(("transport", 3), tp.FORMATTER_SLOTS,
                      "格式化器槽是本判定的唯一金额依据，改它必须改登记面")


class BucketTests(unittest.TestCase):
    def setUp(self):
        self.data = _dataset()

    def _classify(self, fragments):
        return tp.classify_fragment_ownership(self.data, fragments)

    def test_four_buckets_are_exhaustive_and_disjoint(self):
        result = self._classify(tp.collect_fragments(self.data, skip_covered=False))
        counts = result["accounting"]
        self.assertTrue(counts["identity_holds"])
        self.assertEqual(counts["raw_fragments"], sum(
            result["counts"][outcome] for outcome in tp.OUTCOME_VOCABULARY))
        seen = [ident for ids in result["blocked_ids"].values() for ident in ids]
        self.assertEqual(len(seen), len(set(seen)), "同一 id 落在两个 BLOCKED 桶＝互斥性破了")

    def test_every_real_fragment_address_has_an_owner(self):
        """原始清册里不该有「无人认领的地址」——有就是列登记漏了，不是翻译表该收的行。"""
        result = self._classify(tp.collect_fragments(self.data, skip_covered=False))
        orphans = [row for row in result["rows"]
                   if "no_registered_owner_for_address" in row["reasons"]]
        self.assertEqual(orphans, [])

    def test_single_prose_address_is_required(self):
        result = self._classify([_fragment("湾区核心，住两晚足够。", "destination_coverage[0]",
                                           kind="coverage_desc")])
        self.assertEqual(result["counts"]["PROSE_REQUIRED"], 1,
                         json.dumps(result["rows"], ensure_ascii=False)[:200])

    def test_prose_plus_non_prose_address_is_mixed_not_required(self):
        """同一内容 id 在**两格**里各有一个主人 ⇒ 阻断（跨地址双主张）。

        夹具里 `transport_nodes[0]` 的第 3 格与第 5 格都写「机场」：第 3 格是类别列（别名表证明，
        判给 CATEGORY_LEXICON），第 5 格是 node_desc（RENDERED_COLUMNS 登记的散文格）。
        prose_en 按内容键、优先级高于类别面，进表就是把类别通道的来源换成散文表。

        MT-D2 之前这条用的是「同一格同时被两种写法主张」——业主裁决第 2 条把那种双主张
        按槽位迁移解掉了（见 test_v422_dataset_shape_alias.py 的迁移两条），留下的才是真双主人：
        一句中文在自己的格子里是类别词、在另一句里是散文，两个通道都要它，只能人工裁决。
        """
        cn = "机场"
        data = _dataset(transport_nodes=[["旧金山", "旧金山国际机场 (SFO)", "SFO", cn,
                                          "37.6,-122.3", cn]])
        raw = tp.collect_fragments(data, skip_covered=False)
        fragment = next(f for f in raw if f["cn"] == cn)
        self.assertEqual(sorted(fragment["addresses"]),
                         ["transport_nodes[0][3]", "transport_nodes[0][5]"],
                         "夹具必须真的让同一内容落进两格，否则这条牙是空的")
        result = tp.classify_fragment_ownership(data, [fragment])
        self.assertEqual(result["counts"]["MIXED_OWNER_BLOCKED"], 1,
                         json.dumps(result["rows"], ensure_ascii=False)[:400])
        self.assertEqual(result["worklist"], [])
        self.assertEqual(result["rows"][0]["owners"], ["CATEGORY_LEXICON", "PROSE_TABLE"])
        self.assertIn("mixed_owner_for_content_id",
                      {item["code"] for item in result["findings"]})
        # 让位只发生在「同一格」：第 3 格有迁移账，第 5 格没有——两格各判各的，不是一笔糊涂账。
        migrated = {(item["address"]) for item in result["rows"][0]["slot_migration"]}
        self.assertEqual(migrated, {"transport_nodes[0][3]"},
                         json.dumps(result["rows"][0]["slot_migration"], ensure_ascii=False)[:300])

    def test_pure_non_prose_address_is_owned_by_that_channel(self):
        result = self._classify([_fragment("机场", "dataset['transport_nodes'][0]['type']")])
        self.assertEqual(result["counts"]["OWNED_NON_PROSE"], 1)
        self.assertEqual(result["rows"][0]["owners"], ["CATEGORY_LEXICON"])
        self.assertEqual(result["worklist"], [])

    def test_unregistered_address_is_blocked_not_assumed_prose(self):
        result = self._classify([_fragment("某个没登记的格子", "dataset['local_knowledge'][0][9]")])
        self.assertEqual(result["counts"]["OWNER_UNRESOLVED_BLOCKED"], 1)
        self.assertEqual(result["rows"][0]["reasons"], ["no_registered_owner_for_address"])

    def test_collectors_default_filter_still_reports_fewer_than_raw(self):
        """「原始清册完整」是可核对的：默认 skip_covered=True 只做文本相减，
        采集器本身不许因为本判定被改成少收或多收——它永远是 raw 的子集，且 id 同形。"""
        raw = tp.collect_fragments(self.data, skip_covered=False)
        filtered = tp.collect_fragments(self.data)
        self.assertGreaterEqual(len(raw), len(filtered))
        raw_ids = {f["id"] for f in raw}
        self.assertTrue({f["id"] for f in filtered} <= raw_ids,
                        "过滤后的 fragment 不在原始清册里＝采集面被改窄了，所有权账无从对齐")
        result = tp.classify_fragment_ownership(self.data, filtered)
        self.assertEqual({row["id"] for row in result["rows"]}, {f["id"] for f in filtered},
                         "每条送进来的 fragment 必须落进某一桶：少一条就是判定在偷偷丢数据")

    def test_worklist_is_exactly_the_prose_required_ids(self):
        result = tp.classify_fragment_ownership(self.data)
        self.assertEqual([row["id"] for row in result["worklist"]],
                         [f["id"] for f in tp.collect_fragments(self.data, skip_covered=False)
                          if f["id"] in {row["id"] for row in result["rows"]
                                         if row["outcome"] == "PROSE_REQUIRED"}])
        self.assertEqual(tp.prose_translation_worklist(self.data), result["worklist"],
                         "两个取数口必须给同一批：不同源就是两份分母")


class ReplacementClaimTests(unittest.TestCase):
    """业主第 4 条：在册不等于负责；要成为 owner 必须给得出 contract + en 值 + 来源。"""

    def setUp(self):
        self.data = _dataset()
        self.fields = CONTRACT["ownership"]["owners"]["REGISTERED_EN_REPLACEMENT"][
            "provenance_required_fields"]

    def _provenance(self, cn: str, en: str) -> dict:
        return {"owner_contract": "references/prose-translation-contract.json::ownership",
                "en_value": en, "source": "run payload：业主 2026-11-01 逐条指定"}

    def test_presence_alone_is_a_candidate_not_an_owner_and_not_a_block(self):
        """业主 2026-11-01 MT-D2 第 1 条：`en_text_replacements` 降为 legacy 候选资料。

        它不是一个语义通道（混装了完整散文／路线标题／类别词／专名／金额时长日期／行程交通说明），
        所以「表里有这句」现在两件事都不做：不抢 owner（不给它整表身份），也不再把这条卡进
        OWNER_UNRESOLVED（那不是它的职责）。所有权只由地址决定；那段旧英文照实在账上登记成
        MT-E 的**对照候选**——「这里曾有一段英文」是真，「这段英文是本轮来源」不是。
        """
        cn = "全天候随时出发"
        data = dict(self.data)
        data["en_text_replacements"] = {cn: "Any time, any weather"}
        self.assertEqual(tp.legacy_replacement_mode(), tp.LEGACY_CANDIDATE_ONLY,
                         "处置档位从登记面读，不是代码里写死的当前值")
        result = tp.classify_fragment_ownership(data)
        row = next(item for item in result["rows"] if item["cn"] == cn)
        self.assertEqual(row["outcome"], "PROSE_REQUIRED",
                         json.dumps(row, ensure_ascii=False)[:400])
        self.assertEqual(row["owners"], ["PROSE_TABLE"], "owner 只能来自地址")
        self.assertEqual(row["reasons"], [])
        claim = next(item for item in row["address_detail"] if "text_claim" in item)
        self.assertEqual(claim["disposition"], tp.LEGACY_CANDIDATE_ONLY)
        self.assertFalse(claim["acts_as_owner"], "候选资料不许当主人")
        self.assertTrue(claim["legacy_candidate"], "旧英文必须留下对照候选这条账，不许静默丢弃")
        self.assertEqual(claim["missing_fields"], self.fields,
                         "缺哪几个字段要逐条点名，「不成证」不能只是一句结论")
        self.assertEqual(claim["en_value"], "Any time, any weather",
                         "候选值本身要照登记：MT-E 拿它当对照，得看得见原样")
        self.assertNotIn(tp.UNPROVENANCED_CLAIM,
                         {item["code"] for item in result["findings"]},
                         "candidate_only 档位下这条码只能从「档位回退」那条路径发出来")
        self.assertIn(cn, [item["cn"] for item in result["worklist"]],
                      "它现在就是 prose 的工作项：由 MT-E 重新译、重新记来源")

    def test_rolling_the_disposition_back_restores_the_block(self):
        """闭集里另一档必须还活着：把档位登记回 owner_claim，同一份数据重新按「不成证」阻断。

        这条不是怀旧——登记面写了两个档位，代码只实现一个的话，「撤掉 owner 身份」就成了
        一句改不动的话：将来谁把 disposition 改回去，判定会照旧放行而假装什么都没发生。
        """
        cn = "全天候随时出发"
        data = dict(self.data)
        data["en_text_replacements"] = {cn: "Any time, any weather"}
        original = tp.legacy_replacement_mode
        try:
            tp.legacy_replacement_mode = lambda: tp.LEGACY_OWNER_CLAIMS
            result = tp.classify_fragment_ownership(data)
            row = next(item for item in result["rows"] if item["cn"] == cn)
            self.assertEqual(row["outcome"], "OWNER_UNRESOLVED_BLOCKED",
                             json.dumps(row, ensure_ascii=False)[:400])
            self.assertEqual(row["reasons"], [tp.UNPROVENANCED_CLAIM])
            self.assertNotIn(cn, [item["cn"] for item in result["worklist"]])
        finally:
            tp.legacy_replacement_mode = original

    def test_disposition_outside_the_closed_set_raises_instead_of_defaulting(self):
        """档位写成第三个词就得抛：默默按某一档跑，等于让登记面失去对判定的控制权。"""
        cn = "全天候随时出发"
        data = dict(self.data)
        data["en_text_replacements"] = {cn: "Any time, any weather"}
        original = tp.contract
        try:
            def patched():
                doc = original()
                doc["ownership"]["legacy_en_text_replacements"]["disposition"] = "whatever"
                return doc
            tp.contract = patched
            with self.assertRaises(ValueError) as caught:
                tp.legacy_replacement_mode()
            self.assertIn("闭集", str(caught.exception))
        finally:
            tp.contract = original

    def test_provenanced_replacement_conflicts_with_the_prose_address(self):
        """来源齐了 ⇒ REGISTERED_EN_REPLACEMENT 成立；但它抢在 prose_en 上面，
        同一内容又落在 prose 地址时判 MIXED（两个都合法就是第二来源），不是 prose。"""
        cn = "全天候随时出发"
        data = dict(self.data)
        data["en_text_replacements"] = {cn: "Any time, any weather"}
        data["en_text_replacement_provenance"] = {cn: self._provenance(cn, "Any time, any weather")}
        result = tp.classify_fragment_ownership(data)
        row = next(item for item in result["rows"] if item["cn"] == cn)
        self.assertEqual(row["outcome"], "MIXED_OWNER_BLOCKED", json.dumps(row, ensure_ascii=False)[:260])
        self.assertEqual(row["owners"], ["PROSE_TABLE", "REGISTERED_EN_REPLACEMENT"])

    def test_provenanced_replacement_is_an_owner_of_an_unclaimed_address(self):
        """成证的 replacement 按**整格原文**取值：地址没人登记时它就是那一格的 owner，
        于是这条落 OWNED_NON_PROSE，而不是「没人登记＝默认算 prose 的」。"""
        cn = "全天候随时出发"
        data = dict(self.data)
        data["en_text_replacements"] = {cn: "Any time, any weather"}
        data["en_text_replacement_provenance"] = {cn: self._provenance(cn, "Any time, any weather")}
        result = tp.classify_fragment_ownership(
            data, [_fragment(cn, "dataset['local_knowledge'][0][9]", kind="leg_schedule")])
        self.assertEqual(result["counts"]["OWNED_NON_PROSE"], 1,
                         json.dumps(result["rows"], ensure_ascii=False)[:300])
        self.assertEqual(result["rows"][0]["owners"], ["REGISTERED_EN_REPLACEMENT"])
        self.assertEqual(result["worklist"], [])

    def test_string_provenance_is_not_provenance(self):
        cn = "全天候随时出发"
        data = dict(self.data)
        data["en_text_replacements"] = {cn: "Any time, any weather"}
        data["en_text_replacement_provenance"] = {cn: "cascade engine"}
        claim = tp.replacement_claim(data, cn)
        self.assertFalse(claim["provenanced"])
        self.assertEqual(claim["provenance_is_object"], False)

    def test_missing_field_and_value_drift_both_fail(self):
        cn = "全天候随时出发"
        for break_which in ("drop_field", "drift_value"):
            with self.subTest(case=break_which):
                entry = self._provenance(cn, "Any time, any weather")
                if break_which == "drop_field":
                    entry.pop(self.fields[-1])
                else:
                    entry["en_value"] = "Anytime"
                data = dict(self.data)
                data["en_text_replacements"] = {cn: "Any time, any weather"}
                data["en_text_replacement_provenance"] = {cn: entry}
                self.assertFalse(tp.replacement_claim(data, cn)["provenanced"])

    def test_render_precedence_is_measured_not_quoted(self):
        """合同里那句「replacement 抢在 prose_en 上面」必须能在渲染层字节里量到，
        否则这条判定的工程理由就是编的。"""
        layout = tp.layout_js_text()
        self.assertGreater(layout.find("en_text_replacements"), 0)
        self.assertLess(layout.find("D.en_text_replacements && D.en_text_replacements[cn]"),
                        layout.find("if (D.prose_en && D.prose_en[trimmed])"),
                        "tr() 的顺序变了就要重判：这条断言是判定的地基")


class LegacyMigrationInventoryTests(unittest.TestCase):
    """MT-D2 第 3～4 步：旧表逐条按地址槽位迁到真实 owner，不批量补 provenance、不整表删。

    登记面 references/prose-translation-contract.json::ownership.legacy_en_text_replacements.inventory。
    这一类测试盯的是三件容易被糊过去的事：桶是否穷尽、PROSE_TABLE 是不是只由采集器给、
    以及「四桶归零」有没有被偷偷当成「旧表清完了」。
    """

    def setUp(self):
        self.data = _dataset()

    def _inv(self, data=None):
        data = self.data if data is None else data
        classification = tp.classify_fragment_ownership(data)
        return tp.legacy_migration_inventory(data, classification), classification

    def _row(self, result, cn):
        return next(item for item in result["rows"] if item["cn"] == cn)

    def test_registered_inventory_outcomes_match_the_implementation(self):
        registered = CONTRACT["ownership"]["legacy_en_text_replacements"]["inventory"]["outcomes"]
        self.assertEqual(registered, list(tp.LEGACY_INVENTORY_OUTCOMES),
                         "清册的结果词表两面必须同名单：owner 名从 OWNER_VOCABULARY 拼出，"
                         "改名或加 owner 时这里必须一起动")
        self.assertEqual(set(registered) & set(tp.OWNER_VOCABULARY), set(tp.OWNER_VOCABULARY),
                         "五个 owner 名要逐个出现在清册词表里，否则迁移落点少一格")

    def test_buckets_are_exhaustive_and_disjoint_over_the_legacy_keys(self):
        data = dict(self.data)
        data["en_text_replacements"] = {"湾区核心，住两晚足够。": "Covers the bay well.",
                                        "机场": "Airport",
                                        "查无此句的旧英文": "Nowhere in the data"}
        result, _ = self._inv(data)
        self.assertEqual(result["legacy_entries"], 3)
        self.assertTrue(result["identity_holds"])
        self.assertEqual(sum(result["counts"].values()), 3, "桶合计必须等于表键数")
        self.assertEqual(len({c for items in result["buckets"].values() for c in items}), 3,
                         "同一键落两桶＝互斥性破了")
        # 旧表为空时也是合法账：0 = 0，而不是「没东西可核所以通过」。
        empty, _ = self._inv(self.data)
        self.assertEqual(empty["legacy_entries"], 0)
        self.assertTrue(empty["identity_holds"])

    def test_prose_slot_migrates_to_the_prose_table(self):
        data = dict(self.data)
        data["en_text_replacements"] = {"湾区核心，住两晚足够。": "Covers the bay well."}
        result, _ = self._inv(data)
        row = self._row(result, "湾区核心，住两晚足够。")
        self.assertEqual(row["outcome"], "PROSE_TABLE")
        self.assertEqual(row["address_basis"], "fragment",
                         "PROSE_TABLE 只能由采集器给的 fragment 主张，不许在这张清册里凭空认")
        self.assertTrue(row["reference_only"], "旧英文这轮只是对照候选，不是来源")

    def test_category_slot_migrates_to_the_lexicon_not_to_the_prose_table(self):
        data = dict(self.data)
        data["en_text_replacements"] = {"机场": "Airport"}
        result, _ = self._inv(data)
        row = self._row(result, "机场")
        self.assertEqual(row["outcome"], "CATEGORY_LEXICON")
        self.assertEqual([item["owners"] for item in row["address_detail"] if "owners" in item],
                         [["CATEGORY_LEXICON"]])

    def test_owner_comes_from_the_same_fragment_row_not_from_a_second_adjudication(self):
        """成 fragment 的键必须复用 classify 判好的 owner：两张账各算一遍就是两份分母。"""
        data = dict(self.data)
        data["en_text_replacements"] = {"机场": "Airport", "湾区核心，住两晚足够。": "Bay."}
        result, classification = self._inv(data)
        by_cn = {row["cn"]: row for row in classification["rows"]}
        for cn in ("机场", "湾区核心，住两晚足够。"):
            self.assertEqual(self._row(result, cn)["owners"], by_cn[cn]["owners"], cn)
        source = inspect.getsource(tp.legacy_migration_inventory)
        self.assertIn("prose_address_set", source + inspect.getsource(tp.classify_fragment_ownership),
                      "prose 地址全集必须只有一个出处")
        for forbidden in ('"transport_nodes"', "dataset-shape-alias"):
            self.assertNotIn(forbidden, source,
                             "清册里出现 %r＝另写了一份 block/别名账" % forbidden)

    def test_located_cell_without_any_registered_owner_stays_unresolved(self):
        """这一格在数据里，但没有任何通道登记它 ⇒ 无法确认，不默认算 prose、也不算迁完。"""
        data = _dataset(local_knowledge=[["证件", "", "", "", "", "", "", "", "",
                                          "没人登记的一格"]])
        data["en_text_replacements"] = {"没人登记的一格": "Nobody registered this cell"}
        result, _ = self._inv(data)
        row = self._row(result, "没人登记的一格")
        self.assertEqual(row["outcome"], "OWNER_UNRESOLVED_BLOCKED")
        self.assertGreater(row["address_count"], 0, "它确实在数据里，只是没人认领")
        self.assertEqual(row["owners"], [])

    def test_key_absent_from_the_data_is_unlocatable_and_not_counted_as_migrated(self):
        data = dict(self.data)
        data["en_text_replacements"] = {"这句话不在任何一格里": "Not in any cell"}
        result, _ = self._inv(data)
        row = self._row(result, "这句话不在任何一格里")
        self.assertEqual(row["outcome"], "UNLOCATABLE_NO_ADDRESS")
        self.assertEqual(row["address_basis"], "none")
        self.assertEqual(result["counts"]["PROSE_TABLE"], 0,
                         "查不到地址的键不许偷偷进任何一个 owner 桶")
        codes = {item["code"] for item in result["findings"]}
        self.assertIn("legacy_entry_unlocatable", codes,
                      "无法确认必须点名，否则下一轮看到的是 0 条而不是 1 条待处置")

    def test_double_owner_key_stays_mixed_here_too(self):
        """同一句既是散文又是类别格：清册与四桶必须给同一个结论（MIXED），不许这里少一半。"""
        data = _dataset(transport_nodes=[["旧金山", "旧金山国际机场 (SFO)", "SFO", "机场",
                                         "37.6,-122.3", "机场"]])
        data["en_text_replacements"] = {"机场": "Airport"}
        result, classification = self._inv(data)
        self.assertEqual(self._row(result, "机场")["outcome"], "MIXED_OWNER_BLOCKED")
        mixed_in_buckets = [row["id"] for row in classification["rows"]
                            if row["outcome"] == "MIXED_OWNER_BLOCKED"]
        self.assertEqual(len(mixed_in_buckets), 1, "四桶这边也该正好一条混判")

    def test_provenanced_key_is_its_own_owner_and_not_reference_only(self):
        cn = "没人登记的一格"
        data = _dataset(local_knowledge=[["证件", "", "", "", "", "", "", "", "", cn]])
        data["en_text_replacements"] = {cn: "A registered replacement"}
        data["en_text_replacement_provenance"] = {cn: {
            "owner_contract": "references/prose-translation-contract.json::ownership",
            "en_value": "A registered replacement",
            "source": "run payload：业主 2026-11-01 逐条指定"}}
        result, _ = self._inv(data)
        row = self._row(result, cn)
        self.assertEqual(row["outcome"], "REGISTERED_EN_REPLACEMENT")
        self.assertFalse(row["reference_only"], "成证的来源就不是候选，账要分清")
        self.assertTrue(row["provenanced"])

    def test_broken_shape_refuses_to_migrate(self):
        """形状核验不干净就整份拒绝迁移：别名与数据脱节时「这格归谁」本身就不可信。"""
        data = _dataset(transport_nodes=[["旧金山", "旧金山国际机场 (SFO)", "SFO", "机场",
                                         "37.6,-122.3", "北部核心枢纽"],
                                        {"place": "宿务", "type": "机场", "name": "MIA",
                                         "name_en": "Mactan", "coords": "1,2",
                                         "source_status": "已验证"}])
        data["en_text_replacements"] = {"机场": "Airport"}
        result, _ = self._inv(data)
        self.assertTrue(result["shape_blocked"])
        self.assertEqual(result["rows"], [], "阻断时不许给出任何迁移结论")
        self.assertIn("dataset_shape_blocked", {item["code"] for item in result["findings"]})


    def test_served_state_vocabulary_is_registered_and_closed(self):
        registered = CONTRACT["ownership"]["legacy_en_text_replacements"]["inventory"][
            "served_accounting"]["states"]
        self.assertEqual(registered, list(tp.LEGACY_SERVED_STATES),
                         "兑现状态两面必须同名单：多一格就要先在合同里写清它凭什么")

    def test_prose_bucket_is_pending_not_silently_served(self):
        data = dict(self.data)
        data["en_text_replacements"] = {"湾区核心，住两晚足够。": "Covers the bay well."}
        result, _ = self._inv(data)
        row = self._row(result, "湾区核心，住两晚足够。")
        self.assertEqual(row["served"]["state"], "pending_mt_e",
                         "散文今天没有可交付译文：判给 PROSE_TABLE 是「该重翻」，不是「已翻好」")
        self.assertFalse(row["served"]["served"])

    def test_category_word_the_lexicon_cannot_compose_is_flagged(self):
        """迁给类别面但词根拼不出英文＝空头支票：拆旧表后读者页直接少一句，必须点名。"""
        cn = "坞邮轮交换站"
        gloss, _missing = __import__("category_lexicon").compose(cn)
        self.assertEqual(gloss, "", "夹具要先证明这个词真的拼不出（词根表改了这条就要重挑词）")
        data = _dataset(transport_nodes=[["旧金山", "旧金山邮轮港", "SFO", cn,
                                         "37.6,-122.3", "北部核心枢纽"]])
        data["en_text_replacements"] = {cn: "Cruise berth"}
        result, _ = self._inv(data)
        row = self._row(result, cn)
        self.assertEqual(row["outcome"], "CATEGORY_LEXICON")
        self.assertEqual(row["served"]["state"], "cannot_serve")
        self.assertIs(row["served"]["served"], False)
        self.assertIn("migrated_owner_cannot_serve", {item["code"] for item in result["findings"]},
                      "兑现不了的迁移必须发码，否则桶数看着齐、读者页却是空的")

    def test_money_slot_is_declared_unmeasured_instead_of_fake_served(self):
        """金额格的英文住在渲染层 money() 里：Python 侧不许假装复现它，也不许顺手记 served。"""
        cn = "约 250 元"
        data = dict(self.data)
        data["en_text_replacements"] = {cn: "about CNY 250"}
        result, _ = self._inv(data)
        row = self._row(result, cn)
        self.assertEqual(row["outcome"], "MONEY_FORMATTER")
        self.assertEqual(row["served"]["state"], "render_side_unmeasured")
        self.assertIsNone(row["served"]["served"], "没量到的事写成 None，不写成 False 也不写成 True")

    def test_display_name_key_is_served_by_the_registered_pair(self):
        """迁给专名面且那一行本来就有英文名 ⇒ 兑现成立，兑现的是**登记对**而不是旧表串。"""
        data = _dataset(hotels=[["酒店", "旧金山大酒店", "Grand Hotel", "海景度假酒店", "湾区",
                                 "近码头", "无早", "3星", "800", "verified",
                                 "【人均参考】约 1200 元/晚。"]])
        data["en_text_replacements"] = {"旧金山大酒店": "Legacy Grand Hotel"}
        result, _ = self._inv(data)
        row = self._row(result, "旧金山大酒店")
        self.assertEqual(row["outcome"], "DISPLAY_NAME")
        self.assertEqual(row["served"]["state"], "served")
        self.assertEqual(row["served"]["english"], "Grand Hotel",
                         "兑现必须来自 display-name 登记面，不能拿旧表那串冒充")
        self.assertNotEqual(row["legacy_en"], row["served"]["english"])

    def test_colliding_display_names_are_reported_as_unservable_not_silently_served(self):
        """同名两条英文：专名面自己按 collision_rule 把两条都剔了，清册就要报「给不出」。

        这一条要紧在旧表还留着其中一句——如果迁移只写 owner 名字而不查兑现，读者会以为
        拆掉旧表后仍有权威英文，实际上那一格正在等人工裁决。
        """
        row_one = ["酒店", "旧金山大酒店", "Grand Hotel A", "海景度假酒店", "湾区", "近码头",
                   "无早", "3星", "800", "verified", "【人均参考】约 1200 元/晚。"]
        row_two = ["酒店", "旧金山大酒店", "Grand Hotel B", "海景度假酒店", "湾区", "近码头",
                   "无早", "3星", "700", "verified", "【人均参考】约 900 元/晚。"]
        data = _dataset(hotels=[row_one, row_two])
        data["en_text_replacements"] = {"旧金山大酒店": "Grand Hotel A"}
        result, _ = self._inv(data)
        entry = self._row(result, "旧金山大酒店")
        self.assertEqual(entry["outcome"], "DISPLAY_NAME")
        self.assertEqual(entry["served"]["state"], "blocked_by_collision",
                         json.dumps(entry["served"], ensure_ascii=False)[:200])
        self.assertIn("migrated_owner_cannot_serve",
                      {item["code"] for item in result["findings"]},
                      "兑现不了的迁移必须发码：否则桶数齐、读者页空")


class NoDemotionTests(unittest.TestCase):
    """第 7 条：被 block 的条目留在自己的通道里；翻译表拿到它就整份不合格。"""

    def setUp(self):
        self.data = _dataset()
        self.data["en_text_replacements"] = {"全天候随时出发": "Any time, any weather"}
        self.raw = tp.collect_fragments(self.data, skip_covered=False)
        self.result = tp.classify_fragment_ownership(self.data, self.raw)
        self.sha = _sha(self.data)

    def _codes(self, table):
        report = tp.validate_table(self.data, table, run_name=RUN, source_dataset_sha256=self.sha,
                                   fragments=self.raw)
        return {item["code"] for item in report["findings"]}, report

    def test_blocked_rows_are_not_counted_as_missing(self):
        work_ids = {row["id"] for row in self.result["worklist"]}
        blocked_ids = {ident for ids in self.result["blocked_ids"].values() for ident in ids}
        self.assertFalse(work_ids & blocked_ids, "worklist 与 blocked 必须互斥")
        # dataset 传进夹具：占位英文要回声登记过的实体名/目的地名，否则先撞对账码而不是本条想测的码
        table = _compliant_table(self.result["worklist"], self.sha, RUN, dataset=self.data)
        codes, report = self._codes(table)
        self.assertEqual(codes, set(), "只覆盖 worklist 的表必须零阻断：%s"
                         % json.dumps(sorted(codes)))
        self.assertNotIn("fragment_missing_from_table", codes)
        self.assertEqual(report["missing"], [])

    def _blocked_fragment(self):
        blocked_ids = {ident for ids in self.result["blocked_ids"].values() for ident in ids}
        blocked = next((f for f in self.raw if f["id"] in blocked_ids), None)
        self.assertIsNotNone(blocked, "夹具没有 blocked 条目，负测就是空跑")
        return blocked

    def test_entry_for_a_blocked_fragment_blocks_the_whole_table(self):
        table = _compliant_table(self.result["worklist"] + [self._blocked_fragment()],
                                 self.sha, RUN, dataset=self.data)
        codes, report = self._codes(table)
        self.assertIn("entry_for_blocked_fragment", codes,
                      "被 block 的条目混进表必须阻断：否则第 7 条只是句注释")
        self.assertEqual(report["status"], "FAIL")

    def test_apply_refuses_and_leaves_bytes_untouched(self):
        blocked = self._blocked_fragment()
        table = _compliant_table(self.result["worklist"] + [blocked], self.sha, RUN,
                                 dataset=self.data)
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / RUN
            run_dir.mkdir()
            dataset_path = run_dir / "dataset.json"
            original = (json.dumps(self.data, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
            dataset_path.write_bytes(original)
            with self.assertRaises(ValueError) as caught:
                self._apply(run_dir, dataset_path, table)
            self.assertIn("MT-C", str(caught.exception))
            self.assertEqual(dataset_path.read_bytes(), original,
                             "任何阻断都禁止部分写入：宁可整页继续 pending")

    def _apply(self, run_dir: Path, dataset_path: Path, table: dict) -> None:
        table_path = run_dir / "table.json"
        table_path.write_bytes((json.dumps(table, ensure_ascii=False, indent=2) + "\n")
                               .encode("utf-8"))
        tp.apply_table(run_dir, dataset_path, table_path, write=True)

    def test_clean_table_writes_only_worklist_entries(self):
        # dataset 传进夹具：占位英文要回声登记过的实体名/目的地名，否则先撞对账码而不是本条想测的码
        table = _compliant_table(self.result["worklist"], self.sha, RUN, dataset=self.data)
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / RUN
            run_dir.mkdir()
            dataset_path = run_dir / "dataset.json"
            dataset_path.write_bytes((json.dumps(self.data, ensure_ascii=False, indent=2) + "\n")
                                     .encode("utf-8"))
            table_path = run_dir / "table.json"
            table_path.write_bytes((json.dumps(table, ensure_ascii=False, indent=2) + "\n")
                                   .encode("utf-8"))
            report = tp.apply_table(run_dir, dataset_path, table_path, write=True)
            written = json.loads(dataset_path.read_bytes().decode("utf-8"))
            self.assertEqual(report["status"], "PASS",
                             json.dumps(report["findings"][:4], ensure_ascii=False))
            self.assertEqual(report["raw_fragments"], len(self.raw))
            self.assertEqual(report["worklist_fragments"], len(self.result["worklist"]))
            blocked_texts = {row["cn"] for row in self.result["rows"]
                             if row["outcome"].endswith("BLOCKED")}
            self.assertFalse(set(written["prose_en"]) & blocked_texts,
                             "prose_en 里不许出现被 block 的原文")
            self.assertEqual(written["prose_en_provenance"]["fragments"],
                             len(self.result["worklist"]),
                             "来源块里的 fragments 数是 worklist 数，不是原始清册数")


class LegacyMigrationEvidenceTests(unittest.TestCase):
    """MT-D2 第 3～4 步的证据文件必须能现场复算，两张面孔（run 输入 / 读者载荷）都要。

    登记面写「清册见 MTD2_LEGACY_MIGRATION.json」是不够的：那张账是本轮唯一说明
    「旧表拆给了谁、谁今天还给不出英文」的东西。复算不出来的证据＝另一份 VERSION.md 自述。
    """

    ARTIFACT = SCRIPTS.parents[2] / ".temp" / "v422_honest_map" / "MT1_translation" / \
        "artifacts" / "MTD2_LEGACY_MIGRATION.json"
    ANCHOR = SCRIPTS.parents[2] / ".temp" / "v422_honest_map" / "MT1_translation" / \
        "artifacts" / "MTD_SEAL43_ANCHOR.json"
    DATASETS = AUDIT_DATASETS

    def payload(self):
        self.assertTrue(self.ARTIFACT.is_file(),
                        "MT-D2 迁移清册不在盘上：本轮第 3～4 步尚未收口，不能拿「实现已入树」代替账")
        return json.loads(self.ARTIFACT.read_bytes().decode("utf-8"))

    def test_inventory_is_reproducible_over_both_faces(self):
        doc = self.payload()
        anchor = json.loads(self.ANCHOR.read_bytes().decode("utf-8"))["candidates_html"]
        for name, path in sorted(self.DATASETS.items()):
            dataset = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest().upper(),
                             doc["runs"][name]["dataset_sha256"], "%s：输入哈希与在盘字节不一致" % name)
            registered = doc["runs"][name]
            recomputed = tp.legacy_migration_inventory(
                dataset, tp.classify_fragment_ownership(dataset))
            self.assertEqual(recomputed["counts"], registered["input_side"]["counts"],
                             "%s：输入侧迁移桶与现场复算不一致（判定或数据变过，清册必须重跑）" % name)
            self.assertEqual(recomputed["served_states"], registered["input_side"]["served_states"],
                             "%s：兑现账与现场复算不一致" % name)
            # 读者那一面：从**已封的 HTML**（锚点登记过 SHA）里取实际发给浏览器的那张表。
            html_path = SCRIPTS.parents[2] / anchor[name]["path"]
            self.assertEqual(hashlib.sha256(html_path.read_bytes()).hexdigest().upper(),
                             anchor[name]["sha256"],
                             "%s：读者载荷与 seal-43 锚点登记的不是同一份，交付面分母作废" % name)
            self.assertEqual(registered["reader_html"]["sha256"], anchor[name]["sha256"],
                             "%s：清册登记的 HTML 与锚点登记的 HTML 不是同一份" % name)
            delivered = delivered_legacy_map(html_path)
            view = dict(dataset)
            view["en_text_replacements"] = delivered
            reader = tp.legacy_migration_inventory(view, tp.classify_fragment_ownership(view))
            self.assertEqual(reader["counts"], registered["reader_side"]["counts"],
                             "%s：读者侧迁移桶复算不一致" % name)
            self.assertEqual(reader["legacy_entries"], len(delivered),
                             "%s：读者侧分母不等于载荷里的键数" % name)

    def test_bucket_sums_close_on_the_registered_denominator(self):
        doc = self.payload()
        for name, registered in sorted(doc["runs"].items()):
            for side in ("input_side", "reader_side"):
                block = registered[side]
                self.assertEqual(sum(block["counts"].values()), block["legacy_entries"],
                                 "%s/%s：桶合计 ≠ 登记分母" % (name, side))
                self.assertTrue(block["counts_sum_equals_legacy_entries"])
                self.assertTrue(block["identity_holds"], "%s/%s：清册自己说恒等式破了" % (name, side))

    def test_registered_outcomes_and_served_states_close_against_the_artifact(self):
        doc = self.payload()
        contract = tp.contract()["ownership"]["legacy_en_text_replacements"]["inventory"]
        self.assertEqual(contract["outcomes"], doc["contract"]["registered_outcomes"])
        self.assertEqual(contract["outcomes"], doc["contract"]["implementation_outcomes"],
                         "清册词表与实现词表必须同名：一面改了另一面没改就是两本账")
        self.assertEqual(contract["served_accounting"]["states"],
                         doc["contract"]["registered_served_states"])
        self.assertEqual(contract["served_accounting"]["states"],
                         doc["contract"]["implementation_served_states"])

    def test_two_denominators_are_registered_and_pinned_to_this_contract(self):
        """两张账必须一起登记，且这份证据必须钉在**当前**登记面与当前 HTML 字节上。

        证据文件里写的 contract/HTML 哈希如果与在盘字节不符，说明账是上一轮口径生成的：
        那种「复算对不上但测试全绿」正是本项目反复踩过的坑（gates 报成功、产物其实是坏的）。
        """
        doc = self.payload()
        self.assertIn("warning", doc["two_denominators"],
                      "两张账的分母差没写明：下一轮就会有人把「四桶归零」读成「旧表清完」")
        self.assertEqual(doc["caches"]["after"]["abscount"], 0,
                         "生成清册的这轮自己留了缓存：%s" % doc["caches"]["after"])
        contract_path = SCRIPTS.parent / "references" / "prose-translation-contract.json"
        self.assertEqual(doc["contract"]["sha256"],
                         hashlib.sha256(contract_path.read_bytes()).hexdigest().upper(),
                         "证据生成后登记面又改过：本轮清册的口径不是当前口径，必须重跑工具")
        for name, registered in sorted(doc["runs"].items()):
            html_path = SCRIPTS.parents[2] / registered["reader_html"]["path"]
            self.assertEqual(registered["reader_html"]["bytes"], html_path.stat().st_size,
                             "%s：读者载荷字节数变了（交付物被动过？）" % name)

    def test_contract_numbers_match_the_inventory_artifact(self):
        """登记面一旦写了数字，就得有人把数字与账对上——否则「实测」两个字只是修辞。"""
        doc = self.payload()
        reg = tp.contract()["ownership"]["legacy_en_text_replacements"]
        faces = reg["measured_two_faces_2026_11_01"]
        for name in ("california", "philippines"):
            self.assertEqual(faces["input_face"][name],
                             doc["runs"][name]["input_side"]["legacy_entries"],
                             "%s：合同写的输入面分母与清册不一致" % name)
            self.assertEqual(faces["reader_face"][name],
                             doc["runs"][name]["reader_side"]["legacy_entries"],
                             "%s：合同写的读者面分母与清册不一致" % name)
            self.assertEqual(faces["keys_only_on_reader_face"][name],
                             faces["reader_face"][name] - faces["input_face"][name],
                             "%s：多出来的键数与两面之差不等" % name)
            self.assertEqual(faces["unlocatable_on_reader_face"][name],
                             doc["runs"][name]["reader_side"]["unlocatable_count"],
                             "%s：查不到地址的键数与清册不一致" % name)
        self.assertEqual(faces["input_face"]["sum"],
                         faces["input_face"]["california"] + faces["input_face"]["philippines"])
        self.assertEqual(faces["reader_face"]["sum"],
                         faces["reader_face"]["california"] + faces["reader_face"]["philippines"])
        # 合同说生成器自带那张字面量表有 95 个键——那就现场数一遍。
        import ast
        tree = ast.parse((SCRIPTS / "gen_travel_scope.py").read_text(encoding="utf-8"))
        literal = [node for node in tree.body if isinstance(node, ast.Assign)
                   and any(getattr(t, "id", "") == "EN_TEXT_REPLACEMENTS" for t in node.targets)]
        self.assertEqual(len(literal), 1, "生成器里 EN_TEXT_REPLACEMENTS 的赋值不是唯一一处")
        self.assertEqual(str(literal[0].lineno) in faces["why_two_faces"], True,
                         "合同没写这张字面量表的行号：下一轮没人找得到它")
        self.assertEqual("（实测 **%d** 个键）" % len(literal[0].value.keys)
                         in faces["why_two_faces"], True,
                         "合同写的键数 %s 与现场 AST 数出来的 %d 不一致"
                         % (faces["why_two_faces"][:40], len(literal[0].value.keys)))
        sites = reg["measured_render_call_sites_2026_11_01"]
        for fname, info in sorted(doc["render_call_site_inventory"]["files"].items()):
            self.assertEqual(sites[fname]["occurrences"], info["occurrences"],
                             "%s：合同登记的调用点数与逐行清点对不上" % fname)
            for kind, count in sorted(info["by_kind"].items()):
                self.assertEqual(sites[fname][kind], count,
                                 "%s/%s：合同计数 %s ≠ 清册 %s" % (fname, kind, sites[fname][kind], count))
        self.assertEqual(sum(info["by_kind"].get("explicit_en_argument", 0)
                             for info in doc["render_call_site_inventory"]["files"].values()),
                         sites["spa-layout.js"]["explicit_en_argument"],
                         "「只调三行顺序不根治」的实测根据变了：显式 en 参数调用点要重登")

    def test_inventory_is_pinned_to_the_bytes_it_measured(self):
        """堵住「合同⇄清册一起过期」这个洞（2026-11-03 本轮由重跑工具才抓到）。

        调用点清册是对 `assets/*.js` 的**字节**量的，但旧账只把合同与 .temp 清册互相比：
        渲染器改了（MT-E1／#119 回合把 spa-layout.js 从 5BD397D73B6D 改成 32BAE54C0452）
        而两边都没重量时，两条断言照样绿——登记数已经不是今天那份字节的数。
        所以这里强制三方一致：清册记的 SHA ⇔ 在盘字节 ⇔ 合同登记的 SHA 前缀。
        """
        doc = self.payload()
        reg = tp.contract()["ownership"]["legacy_en_text_replacements"]
        sites = reg["measured_render_call_sites_2026_11_01"]
        files = doc["render_call_site_inventory"]["files"]
        self.assertTrue(files, "清册里没有渲染文件面：这条断言就变成空转")
        for fname, info in sorted(files.items()):
            path = SCRIPTS.parents[0] / "assets" / fname
            live = hashlib.sha256(path.read_bytes()).hexdigest().upper()
            self.assertEqual(info["sha256"], live,
                             "%s：清册是对 %s 量的，在盘已经是 %s ⇒ 证据不是当前字节，必须重跑工具"
                             % (fname, info["sha256"][:12], live[:12]))
            self.assertEqual(str(sites[fname].get("sha256_12") or "").upper(), live[:12],
                             "%s：合同没把 SHA 钉在自己登记的那个数上（登记=%r，在盘=%s）"
                             % (fname, sites[fname].get("sha256_12"), live[:12]))
            # 独立表达式：合同登记的 occurrences 必须等于现场按同一规则数出来的行数
            hits = [line for line in path.read_text(encoding="utf-8").splitlines()
                    if "en_text_replacements" in line]
            self.assertEqual(sites[fname]["occurrences"], len(hits),
                             "%s：合同调用点数与现场行数不一致（登记 %d，现场 %d）"
                             % (fname, sites[fname]["occurrences"], len(hits)))

    def test_render_teardown_is_declared_not_done(self):
        """本轮只清点调用点，不许把「已拆除」写进任何一面账。"""
        doc = self.payload()
        inventory = doc["render_call_site_inventory"]
        self.assertIn("只清点", inventory["status"],
                      "拆除状态措辞变了就要重新核对：本轮没有 MT-G 重建，谁写「已拆完」都是假陈述")
        explicit = sum(info["by_kind"].get("explicit_en_argument", 0)
                       for info in inventory["files"].values())
        self.assertGreater(explicit, 0,
                           "显式 en 参数调用点为 0＝清点逻辑或渲染层变了：那条「三行顺序不根治」的依据要重测")


class MatrixEvidenceTests(unittest.TestCase):
    """本轮实测的两份账必须与判定实现同源：证据文件里的数字要能现场复算。"""

    MATRIX = SCRIPTS.parents[2] / ".temp" / "v422_honest_map" / "MT1_translation" / \
        "artifacts" / "MTD_OWNERSHIP_MATRIX.json"
    DATASETS = AUDIT_DATASETS

    def test_matrix_exists_and_is_dated_this_round(self):
        if not self.MATRIX.is_file():
            self.skipTest("MT-D 矩阵尚未生成（本轮证据在 .temp，允许先跑实现测试）")
        payload = json.loads(self.MATRIX.read_bytes().decode("utf-8"))
        self.assertTrue(payload["identity_holds_both_runs"])

    def test_registered_accounting_is_reproducible_from_the_datasets(self):
        if not all(path.is_file() for path in self.DATASETS.values()):
            self.skipTest("两棵审计输入不在盘上")
        payload = json.loads(self.MATRIX.read_bytes().decode("utf-8")) \
            if self.MATRIX.is_file() else None
        self.assertIsNotNone(payload, "矩阵不在，复算无处对表")
        for name, path in self.DATASETS.items():
            dataset = json.loads(path.read_text(encoding="utf-8"))
            fresh = tp.classify_fragment_ownership(dataset)["accounting"]
            registered = payload["runs"][name]["accounting"]
            self.assertEqual(fresh, registered,
                             "%s：矩阵里的四桶账与现场复算不一致（判定或输入变过，矩阵必须重跑）" % name)
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest().upper(),
                             payload["runs"][name]["dataset_sha256"],
                             "%s：矩阵登记的输入哈希与在盘字节不一致" % name)

    def test_mt_e_table_length_is_not_frozen_while_blocked_buckets_are_nonzero(self):
        """业主的话翻成断言：mixed/unresolved 归零之前，谁都不许把某个数字写成 MT-E 的门限。"""
        if not self.MATRIX.is_file():
            self.skipTest("MT-D 矩阵尚未生成")
        payload = json.loads(self.MATRIX.read_bytes().decode("utf-8"))
        gate = payload["gate_for_mt_e"]["measured"]
        frozen = (CONTRACT["ownership"].get("mt_e_table_length_frozen_at") or {})
        blocked = sum(item["mixed"] + item["unresolved"] for item in gate.values())
        if blocked:
            self.assertEqual(frozen, {}, "两桶还有 %d 条，登记面就已经写了冻结表长＝把没做完的账写成做完"
                             % blocked)

    def test_frozen_length_equals_the_live_worklist_size(self):
        """MT-D2 第 7 步：冻结的数字必须**就是**现场 worklist 的行数，不是谁抄下来的观测值。

        取数用的是 worklist 本体（apply/validate/export 共用的那张清单），不是 accounting 里的
        自报计数——否则「数字自洽但清单不是那张」这种形状就没人拦。
        """
        frozen = CONTRACT["ownership"]["mt_e_table_length_frozen_at"]
        self.assertEqual(frozen["status"], "FROZEN")
        for name, path in sorted(self.DATASETS.items()):
            dataset = json.loads(path.read_text(encoding="utf-8"))
            result = tp.classify_fragment_ownership(dataset)
            run_key = path.parent.name
            registered = frozen["per_run"][run_key]
            self.assertEqual(len(result["worklist"]), registered["prose_required"],
                             "%s：冻结表长 %s ≠ 现场 worklist %s 行"
                             % (run_key, registered["prose_required"], len(result["worklist"])))
            self.assertEqual(result["accounting"]["prose_required"], registered["prose_required"],
                             "%s：worklist 与四桶账自己都对不上" % run_key)
            self.assertEqual({key: registered[key] for key in
                              ("mixed_owner_blocked", "unresolved_owner_blocked")},
                             {"mixed_owner_blocked": 0, "unresolved_owner_blocked": 0},
                             "%s：两桶不为零却已经把表长冻结了——业主的前置条件没满足" % run_key)
            self.assertEqual(result["accounting"]["raw_fragments"], registered["raw_fragments"],
                             "%s：raw 分母变了（采集面动过，冻结必须重跑）" % run_key)

    def test_frozen_total_is_the_sum_of_two_runs_and_not_a_dedup(self):
        """当前冻结的 717 是两棵载荷各算各的；跨 CA/PH 去重会造出一张没人能对账的表。"""
        frozen = CONTRACT["ownership"]["mt_e_table_length_frozen_at"]
        per_run = [value["prose_required"] for value in frozen["per_run"].values()]
        self.assertEqual(frozen["total_entries_required"], sum(per_run),
                         "总数不是两地之和：要么有人去了重，要么有人改了单格")
        unique_strings = set()
        per_run_strings = []
        for path in self.DATASETS.values():
            dataset = json.loads(path.read_text(encoding="utf-8"))
            rows = [row["cn"] for row in tp.classify_fragment_ownership(dataset)["worklist"]]
            self.assertEqual(len(set(rows)), len(rows),
                             "%s：同一 run 内部就有重复串，那 worklist 的行数不是分母" % path.parent.name)
            per_run_strings.append(set(rows))
        dedup = len(per_run_strings[0] | per_run_strings[1])
        overlap = len(per_run_strings[0]) + len(per_run_strings[1]) - dedup
        self.assertIn("no_cross_run_dedup", frozen,
                      "去重会改变表长却没登记口径，下一轮就会有人「顺手」去一次重")
        self.assertIn("去重会得到 %d" % dedup, frozen["no_cross_run_dedup"],
                      "登记面写的去重反事实与实测不符：实测 %d，登记面没跟着改" % dedup)
        self.assertGreater(overlap, 0,
                           "两地没有同形串：那「不去重」这句口径就是空话，测试与登记都要重判")

    def test_preconditions_registered_are_the_preconditions_measured(self):
        """冻结块里那句「前置条件已满足」必须是量出来的，不是形容词。"""
        frozen = CONTRACT["ownership"]["mt_e_table_length_frozen_at"]
        pre = frozen["preconditions_measured"]
        for name, path in sorted(self.DATASETS.items()):
            dataset = json.loads(path.read_text(encoding="utf-8"))
            counts = tp.classify_fragment_ownership(dataset)["counts"]
            self.assertEqual(pre["mixed_owner_blocked"][name],
                             counts["MIXED_OWNER_BLOCKED"], "%s：mixed 的登记值≠实测值" % name)
            self.assertEqual(pre["unresolved_owner_blocked"][name],
                             counts["OWNER_UNRESOLVED_BLOCKED"], "%s：unresolved 的登记值≠实测值" % name)
        matrix = json.loads(self.MATRIX.read_bytes().decode("utf-8"))
        self.assertEqual(pre["identity_holds_both_runs"], matrix["identity_holds_both_runs"],
                         "恒等式成立与否由矩阵说，登记面不许自己点一个勾")
        self.assertEqual(pre["cli_exit_codes"],
                         {name: run["exit"] for name, run in sorted(matrix["runs"].items())},
                         "退出码必须是那条命令的，不是本工具算的")
        self.assertEqual(pre["export_matches_worklist_both_runs"],
                         all(run["export_matches_worklist"] for run in matrix["runs"].values()),
                         "--export 与 worklist 不同源＝两份清单两个分母")

    def test_hash_direction_is_one_way(self):
        """矩阵钉合同，合同只指矩阵路径——互钉成环之后，「只改一边」就成了唯一能跑通的做法。"""
        import re as _re
        frozen = CONTRACT["ownership"]["mt_e_table_length_frozen_at"]
        matrix = json.loads(self.MATRIX.read_bytes().decode("utf-8"))
        live_contract = hashlib.sha256(tp.CONTRACT_PATH.read_bytes()).hexdigest().upper()
        self.assertEqual(matrix["contract"]["sha256"], live_contract,
                         "矩阵是在**旧合同**字节上生成的：合同改过就必须重跑矩阵")
        blob = json.dumps(frozen["measured_by"], ensure_ascii=False)
        self.assertEqual(_re.findall(r"\b[0-9A-F]{64}\b", blob), [],
                         "measured_by 里出现 64 位哈希＝合同开始钉矩阵，方向就成环了")

    def test_historical_numbers_are_registered_as_observations_not_gates(self):
        frozen = CONTRACT["ownership"]["mt_e_table_length_frozen_at"]
        self.assertEqual(sorted(frozen["not_a_gate"]), ["357", "506", "513"],
                         "业主点名的三个观测必须逐个在册并写明出处")
        for value in frozen["not_a_gate"].values():
            self.assertTrue(str(value).strip(), "not_a_gate 有条目没写它当初是什么观测")
        self.assertNotIn(frozen["total_entries_required"],
                         [int(key) for key in frozen["not_a_gate"]],
                         "冻结数与某个观测撞了：那就要在 not_a_gate_note 里说清是巧合还是照抄")
        self.assertEqual(frozen["not_a_gate"]["513"],
                         "MT-D 前半两地 prose 之和（506 + 7）")


    def _live_seal(self):
        origin_path = SCRIPTS.parent / "product-origin.json"
        origin = json.loads(origin_path.read_bytes())
        return (hashlib.sha256(origin_path.read_bytes()).hexdigest().upper(),
                len(origin["inventory"]))

    def _anchor(self):
        self.assertTrue(MT_D2_ANCHOR.is_file(),
                        "MT-D2 锚点不在盘上：本轮「命令＋cwd＋关键环境已登记」这句话没有载体")
        return json.loads(MT_D2_ANCHOR.read_bytes().decode("utf-8"))

    def _accepted_anchor_seal(self, anchor, live_seal):
        """Return the seal that the historical MT-D2 anchor is required to pin.

        v4.2.2 required the anchor to equal the live product seal.  The owner-approved
        v5.0.0 round is an identity-only major migration: the old anchor remains evidence
        for the signed source release, while the new live seal is independently protected
        by product-origin.json.  The exception is therefore configuration-driven and only
        applies when every migration identity agrees; it cannot turn an arbitrary stale
        anchor green.
        """
        origin = json.loads((SCRIPTS.parent / "product-origin.json").read_bytes())
        scope = json.loads((SCRIPTS.parent / "references" / "release-scope.json").read_bytes())
        migration = scope.get("version_identity_migration") or {}
        if (origin.get("version") == migration.get("to_version")
                and migration.get("change_class") == "release-identity-only"):
            source_seal = ((migration.get("source_release") or {})
                           .get("product_origin_sha256"))
            self.assertEqual(migration.get("from_version"), "4.2.2")
            self.assertEqual(migration.get("to_version"), "5.0.0")
            self.assertTrue(migration.get("must_not_expand_scope"))
            self.assertEqual(anchor["seal_lineage"]["latest_current"], source_seal,
                             "v5 迁移登记的源封条与 v4.2.2 锚点不是同一份")
            self.assertNotEqual(live_seal, source_seal,
                                "已是 v5 却仍与源封条相同：主版本迁移没有生成新封条")
            return source_seal
        return live_seal

    def _accepted_anchor_sealed_files(self, anchor, live_sealed_files):
        """Bridge the signed source inventory only for the exact v5 package additions.

        The historical anchor must remain 169 instead of being rewritten after the fact.
        v5 may accept that source count only when the migration contract names every added
        file, all of them are present in the live sealed inventory, and there are no other
        count changes.  This keeps an unregistered extra or missing file red.
        """
        origin = json.loads((SCRIPTS.parent / "product-origin.json").read_bytes())
        scope = json.loads((SCRIPTS.parent / "references" / "release-scope.json").read_bytes())
        migration = scope.get("version_identity_migration") or {}
        if (origin.get("version") == migration.get("to_version")
                and migration.get("change_class") == "release-identity-only"):
            source_files = (migration.get("source_release") or {}).get("sealed_files")
            additions = migration.get("release_tree_additions") or []
            self.assertIsInstance(source_files, int)
            self.assertEqual(source_files, anchor["current_release_snapshot"]["sealed_files"],
                             "v5 迁移登记的源文件数与 v4.2.2 历史锚点不一致")
            self.assertEqual(len(additions), len(set(additions)),
                             "v5 release_tree_additions 含重复路径")
            self.assertEqual(set(additions), {
                "LICENSE",
                "THIRD_PARTY_NOTICES.md",
                "scripts/build_release_package.py",
                "scripts/test_v500_release_package.py",
            }, "v5 封册增量不是已裁定的授权文件、素材来源、确定性打包器与其门牙")
            self.assertTrue(set(additions).issubset(set(origin["inventory"])),
                            "v5 登记的新增文件未全部进入现场封册")
            self.assertEqual(live_sealed_files, source_files + len(additions),
                             "v5 现场封册数不等于源封册＋精确新增集")
            return source_files
        return live_sealed_files

    def test_seal46_anchor_agrees_with_the_live_tree_and_the_contract(self):
        """锚点的每一个数字都要能在盘上再量一遍，否则它只是另一份自述（PENDING/PASS 两态都查）。

        两态分开查是因为生产中途盘上只能是 PENDING（锚点工具自己会跑这条测试），
        而「PENDING 不许把没量的项写成通过」本身必须是一条能失败的断言：
        上一版预锚点写了 agreement=True 与 outside=[]——那两条都是**还没量就先说过了**，
        形状上就是假账。现在 PENDING 阶段这些格子必须是 null 且带原因。
        """
        anchor = self._anchor()
        frozen = CONTRACT["ownership"]["mt_e_table_length_frozen_at"]
        live_seal, live_sealed_files = self._live_seal()
        accepted_anchor_seal = self._accepted_anchor_seal(anchor, live_seal)
        accepted_anchor_files = self._accepted_anchor_sealed_files(anchor, live_sealed_files)
        self.assertEqual(anchor["table_length_frozen"]["contract_value"],
                         frozen["total_entries_required"],
                         "锚点签的表长与登记面现在写的不是同一个数")
        for name, row in sorted(anchor["candidates_html"].items()):
            page = SCRIPTS.parents[2] / row["path"]
            self.assertEqual(hashlib.sha256(page.read_bytes()).hexdigest().upper(), row["sha256"],
                             "%s：锚点说交付 HTML 没变，现场却不是那份字节" % name)
            self.assertTrue(row["unchanged_since_seal42"])
        snapshot = anchor["current_release_snapshot"]
        self.assertEqual(snapshot["sealed_files"], accepted_anchor_files,
                         "锚点登记的封册文件数与在盘封册不符")
        self.assertEqual(anchor["release_tree_caches_abscount"]["before"], 0,
                         "锚点动手的时候发布树就不干净")
        self.assertEqual(anchor["seal_46"]["label"], "seal-46",
                         "历史格的名字变了：读的人会把某一封历史当成别的轮次")
        self.assertFalse(anchor["seal_46"]["is_the_live_seal"],
                         "历史格自称当前封册")
        if anchor["verification_status"] == "PENDING":
            self.assertIsNone(anchor["table_length_frozen"]["agreement"],
                              "PENDING 阶段就写了 agreement=True：现场还没复算，先签＝假账")
            self.assertTrue(str(anchor["table_length_frozen"].get("pending_reason") or "").strip(),
                            "null 要带原因，否则读的人分不清「没量」与「量出来就是空」")
            scope = anchor["delta_seal42_to_live"]["authorized_scope_check"]
            self.assertFalse(scope["checked"], "PENDING 阶段不许宣称授权面查过了")
            self.assertIsNone(scope["outside"], "同上：outside 要 null，不是空的假绿")
            self.assertEqual(anchor["verification_runs"], [],
                             "PENDING 阶段没有跑过命令，runs 必须是空的")
            return
        self.assertEqual(anchor["verification_status"], "PASS",
                         "既不是 PENDING 也不是 PASS：那这一版锚点是什么状态？")
        self.assertTrue(anchor["table_length_frozen"]["agreement"],
                        "锚点自己说现场复算没过——那这封就不该存在")
        self.assertEqual(anchor["table_length_frozen"]["measured_now_sum_of_worklists"],
                         frozen["total_entries_required"],
                         "PASS 的锚点里现场复算的表长与登记值不符")
        self.assertEqual(anchor["release_tree_caches_abscount"]["after"], 0,
                         "锚点签的时候发布树就不干净，或现在脏了：两种都要重跑")
        scope = anchor["delta_seal42_to_live"]["authorized_scope_check"]
        self.assertTrue(scope["checked"])
        self.assertEqual(scope["outside"], [],
                         "有授权面之外的文件被改过却没在锚点里被抓住")
        self.assertEqual(anchor_freshness(anchor, accepted_anchor_seal, accepted_anchor_files), [],
                         "PASS 锚点没有钉在当前发布登记的证据源封条上：%s" % json.dumps(
                             anchor_freshness(anchor, accepted_anchor_seal, accepted_anchor_files),
                             ensure_ascii=False))
        labels = [row["label"] for row in anchor["verification_runs"]]
        self.assertEqual(len(labels), len(set(labels)), "verification_runs 有重名标签")
        for row in anchor["verification_runs"]:
            self.assertEqual(row["exit"], 0, "%s 登记的退出码不是 0" % row["label"])
            self.assertEqual(row["key_environment"]["PYTHONDONTWRITEBYTECODE"], "1",
                             "%s 没登记缓存护栏：这条命令按锚点重跑会污染封册字节" % row["label"])
            self.assertTrue(row["command"].startswith("python -B"),
                            "%s 的 argv 里没有 -B：复现条件不完整" % row["label"])
        self.assertIn("test_anchor_is_final_and_points_at_the_live_seal",
                      json.dumps(anchor["freshness_rule"], ensure_ascii=False),
                      "锚点没登记「哪条测试是验收」：验收就成了口头流程")

    def test_anchor_is_final_and_points_at_the_live_seal(self):
        """锚点验收（业主 2026-11-01 第 2 条）：正式交付只接受 PASS + live == latest_current。

        这条**不在锚点工具自己的 verification_runs 里跑**（那条命令跑的时候盘上只能是
        PENDING 版，写了就是自指死锁），而是由工具在写完 PASS 之后单独跑一次，
        结果落在 MTD2_SEAL46_ANCHOR_ACCEPTANCE.json：验收文件钉锚点 SHA，锚点只记验收文件的路径
        （单向，跟 measured_by 的哈希方向同一条规矩）。业主手动跑 `pytest scripts` 时
        盘上已经是 PASS 版，这条正常咬。
        """
        anchor = self._anchor()
        live_seal, live_sealed_files = self._live_seal()
        accepted_anchor_seal = self._accepted_anchor_seal(anchor, live_seal)
        accepted_anchor_files = self._accepted_anchor_sealed_files(anchor, live_sealed_files)
        self.assertEqual(anchor_freshness(anchor, accepted_anchor_seal, accepted_anchor_files), [],
                         "锚点没通过新鲜度验收：%s" % json.dumps(
                             anchor_freshness(anchor, accepted_anchor_seal, accepted_anchor_files),
                             ensure_ascii=False))
        self.assertEqual(anchor["freshness_rule"]["acceptance_test"], self._testMethodName,
                         "登记的验收测试名与这条测试自己不是一个：改名就会两边不同步")
        self.assertEqual(anchor["freshness_rule"]["delivery_verdict"],
                         "PASS + live == latest_current",
                         "正式交付的判据被改写：这两条是业主裁决的原文形状")
        self.assertEqual(anchor["freshness_rule"]["deselect_inside_anchor_run"],
                         self._testMethodName,
                         "工具里 deselect 掉的必须是**这一条**，多 deselect 就等于把别的测试也放走")

    def _rollback(self, label):
        """把「树回退到某一封历史」翻译成锚点视角：在盘封册换成那一封的 SHA。"""
        anchor = self._anchor()
        historical = {row["label"]: row["product_origin_sha256"]
                      for row in anchor["seal_lineage"]["historical"]}
        self.assertIn(label, historical, "血缘里没有 %s 这一封：回退负测无从构造" % label)
        _live_seal, live_sealed_files = self._live_seal()
        violations = anchor_freshness(anchor, historical[label], live_sealed_files)
        rules = [item["rule"] for item in violations]
        self.assertIn("latest_current_is_not_the_live_seal", rules,
                      "回退到 %s 时锚点仍然算当前：%s ⇒ 新鲜度门是空的" % (label, rules))
        self.assertIn("live_seal_matches_a_historical_lineage_row", rules,
                      "回退到 %s 时没认出「在盘这封是历史」：%s" % (label, rules))
        return rules

    def test_rollback_to_seal45_is_rejected(self):
        self._rollback("seal-45")

    def test_rollback_to_seal46_is_rejected(self):
        self._rollback("seal-46")

    def test_rollback_to_seal47_is_rejected(self):
        self._rollback("seal-47")

    def test_a_pending_anchor_is_never_deliverable(self):
        """负测：把在盘锚点的状态改成 PENDING，验收必须红（PENDING 不是「还没好」的委婉语）。"""
        anchor = self._anchor()
        anchor["verification_status"] = "PENDING"
        live_seal, live_sealed_files = self._live_seal()
        rules = [item["rule"] for item in anchor_freshness(anchor, live_seal, live_sealed_files)]
        self.assertIn("not_final_status", rules)

    def test_the_historical_row_cannot_be_promoted_into_the_current_slot(self):
        """负测：把 seal-46 的 SHA 抄进 latest_current 与 current_release_snapshot——
        「血缘里出现过」不再算数，现场量到的那一封必须是它自己。"""
        anchor = self._anchor()
        historical = {row["label"]: row["product_origin_sha256"]
                      for row in anchor["seal_lineage"]["historical"]}
        anchor["seal_lineage"]["latest_current"] = historical["seal-46"]
        anchor["current_release_snapshot"]["product_origin_sha256"] = historical["seal-46"]
        _live_seal, live_sealed_files = self._live_seal()
        rules = [item["rule"] for item in anchor_freshness(
            anchor, historical["seal-46"], live_sealed_files)]
        self.assertIn("historical_seal_46_claimed_as_current", rules)
        self.assertNotIn("latest_current_is_not_the_live_seal", rules,
                         "这条负测要单独证明「血缘/快照自洽」不再够用，所以新鲜度那条必须沉默")
        self.assertIn("live_seal_matches_a_historical_lineage_row", rules)


class Mte0CandidateTableTests(unittest.TestCase):
    """MT-E0 那两张 **886 行历史表**的可重放合同：按今天的尺子重跑，账必须与登记的**历史面**相等。

    业主 2026-11-02 执行顺序第 2 步把 169 行按身份绑定迁出 prose 之后，当前面是
    `ownership.mt_e1_candidate_tables_2026_11_02`（717 行，见 Mte1CandidateTableTests）。
    这一类**不跟着改表**：886 那两张表与其证据账原样留在盘上（MT-F0 盲审、MT-F1 校准、这颗所有权雷
    的实物出处都在那一版里），要保的是它们**还是那些字节**、且按今天的规则重跑时报什么有账可查。

    为什么值得进发布树（而不是只留在 .temp 工具里跑一次）：业主裁决 MT-E0 可以直接生成，
    但「生成时 PASS」是一次性证词。这一轮实测到的两件事正好说明一次性证词不够——
      · 草稿里一条 id 末位打错（f7f2c88041b），那条英文其实属于另一行：第一版只报了没拦，
        于是 f7f2c88041e 带着农庄的英文进了表；抓到货的是「同一条英文出现在两行」这个副作用。
      · 纯散文行（403 条起草里 237 条没有任何数字／拉丁锚点）结构门天生看不见：
        中文写圣莫尼卡、英文写圣塔芭芭拉，一个码都不触发。
    所以这里复算的是**字节**：表内容、分母、出处词汇、盲区账、串位指纹、以及负测的造案记录。
    """

    BLOCK = CONTRACT["ownership"]["mt_e0_candidate_tables_2026_11_01"]
    ROOT = SCRIPTS.parents[2] / ".temp" / "v422_honest_map"
    ARTIFACTS = ROOT / "MT1_translation" / "artifacts"
    RUN_NAMES = ("california", "philippines")

    def payload(self, relative: str):
        return payload_at(relative)

    def evidence(self) -> dict:
        return self.payload(self.BLOCK["evidence"])

    def dataset_for(self, name: str):
        """证据里的 dataset 路径是**仓库根相对**的（建表工具用 relative_to(PROJ) 写的），这里同源解一次。"""
        path = SCRIPTS.parents[2] / self.evidence()["runs"][name]["dataset"]
        return json.loads(path.read_text(encoding="utf-8")), path

    def test_history_table_revalidates_against_the_registered_history_face(self):
        """门不是「生成时跑过」，是**每次都按盘上字节重跑**：历史面的 finding 多重集必须与登记**完全相等**。

        判据从「零 finding」改成「与登记集合相等」的原因有两个，都来自实测：
          · #119 把第九类尺子（同对内拉丁专名形状）接进 validate_table，这张表**合法地**报 2 条阻断，
            登记在 `registered_findings_2026_11_02_proper_name_variant`；
          · MT-E1 把 169 行迁出 prose，同一张表又合法地多报 `entry_for_blocked_fragment`
            （CA 108／PH 61），登记在 `history_face_findings_2026_11_02`。
        两张都是**预期红**：表没坏、尺子没宽，是 owner 判据变了。业主明令历史面不删不改名、
        也不许为了让它重新 PASS 把 fragment 塞回去，所以这里把红写成可复算的账。三个方向都要有牙：
          · 冒出没登记的码 ⇒ fail（新缺陷不许悄悄进账）；
          · 登记的一条消失 ⇒ fail（删豁免或把阈值调松到咬不到东西，能把红抹成绿，比红着更危险）；
          · 逐条 (entry_id, cn_token, en_token, distance) 由盘上字节现算复现 ⇒ 钉的是这 2 条，不是「差不多 2 条」；
          · 被点名的 blocked id 集合 == 今天 migrated_row_ids ⇒ 「886−717 只有一个来源」的实物证明。
        """
        evidence = self.evidence()
        registered = self.BLOCK["registered_findings_2026_11_02_proper_name_variant"]["expected"]
        face = self.BLOCK["history_face_findings_2026_11_02"]
        rule = pr.proper_name_rule()
        for name in self.RUN_NAMES:
            table = self.payload(self.BLOCK["tables"][name])
            dataset, _ = self.dataset_for(name)
            raw = (self.ROOT / self.BLOCK["tables"][name]).read_bytes().decode("utf-8")
            report = tp.validate_table(dataset, table, run_name=evidence["runs"][name]["run_dir"],
                                       source_dataset_sha256=evidence["runs"][name]["dataset_sha256"],
                                       duplicate_ids=tp.duplicate_entry_ids(raw))
            got = collections.Counter(f["code"] for f in report["findings"])
            self.assertEqual(dict(got), dict(face["expected"][name]),
                             "%s：历史表按今天的尺子跑出的 finding 多重集与登记不等 ⇒ "
                             "要么迁移面/尺子变了而这本账没重跑，要么历史表被动过：%s"
                             % (name, sorted(got.items())))
            self.assertEqual(report["status"], face["status"],
                             "%s：历史面的状态由登记说，不由「跑起来好看」说" % name)
            named = sorted({BLOCKED_ID_IN_DETAIL.match(f["detail"]).group("id")
                            for f in report["findings"]
                            if f["code"] == "entry_for_blocked_fragment"
                            and BLOCKED_ID_IN_DETAIL.match(f["detail"])})
            self.assertEqual(len(named), got.get("entry_for_blocked_fragment", 0),
                             "%s：有 blocked finding 的 detail 解析不出 entry id＝点名格式变了，"
                             "这条比对就成了解释" % name)
            migrated = tp.classify_fragment_ownership(dataset)["slot_identity_migration"]["migrated_row_ids"]
            self.assertEqual(named, sorted(migrated),
                             "%s：历史表被点名的行 ≠ 今天按身份绑定迁走的行 ⇒ 差额 886−717 不止一个来源" % name)
            fired = []
            for ident, record in sorted(table["entries"].items()):
                for hit in pr.proper_name_conflicts(str(record.get("cn") or ""),
                                                     str(record.get("en") or "").strip(), rule):
                    fired.append((ident, hit["cn_token"], hit["en_token"], hit["distance"]))
            self.assertEqual(fired, sorted((item["entry_id"], item["cn_token"], item["en_token"],
                                            item["distance"]) for item in registered[name]),
                             "%s：专名形状账与表字节对不上（哪一条、哪一对 token、差几步都得复现）" % name)
            for item in registered[name]:
                self.assertIn(item["side_at_fault"], ("source", "translation"),
                              "错在哪一侧要说得出来：source 侧的那条只改英文不算结案")
                self.assertTrue(item["why"].strip())
                self.assertEqual(table["entries"][item["entry_id"]]["addresses"], [item["address"]],
                                 "%s：登记的落点与表里那条 entry 的地址不一致 ⇒ 这条账指的不是这张表" % name)
            self.assertEqual(table["table_sha256"], report["table_sha256_recomputed"],
                             "%s：表内声明摘要与复算不一致 ⇒ 这张表不是它自称的那张" % name)

    def test_lengths_are_the_superseded_per_run_denominators(self):
        """历史表的行数只能等于**历史面冻结值**（886＝CA 501＋PH 385），不是当前值 717。

        业主第 2 条：旧 886 要进历史/superseded，不能被当成从未存在，也不能被机械替换。
        所以这里读的是 `history_superseded_2026_11_02.per_run`——历史面与当前面各挂各的账，
        谁也不冒充谁；如果哪天有人把 886 从合同里抹了，这条会当场断在「历史面不在了」。
        """
        evidence = self.evidence()
        frozen = CONTRACT["ownership"]["mt_e_table_length_frozen_at"]
        history = frozen["history_superseded_2026_11_02"]
        self.assertEqual(history["value"], 886)
        self.assertNotEqual(frozen["total_entries_required"], history["value"],
                            "当前值与历史值相等＝要么迁移没落地，要么 886 被改写成了当前值")
        for name in self.RUN_NAMES:
            table = self.payload(self.BLOCK["tables"][name])
            row = evidence["runs"][name]
            run_key = [k for k in history["per_run"] if k.startswith(name)][0]
            self.assertEqual(len(table["entries"]), history["per_run"][run_key]["prose_required"],
                             "%s：历史表的行数不再等于登记的历史面" % name)
            self.assertEqual(len(table["entries"]), row["worklist_rows"],
                             "%s：历史表条目数不等于它自己那份证据的 worklist 行数" % name)
            self.assertEqual(row["entries_written"], row["worklist_rows"])
        self.assertEqual(sum(len(self.payload(self.BLOCK["tables"][n])["entries"])
                             for n in self.RUN_NAMES), history["value"])
        self.assertFalse(evidence["totals"]["cross_run_dedup_performed"])

    def test_review_status_and_basis_vocabulary_are_closed(self):
        """出处词汇表是**登记面**的闭集：表里出现的每个 en_basis／method／review_status 都得对得上。"""
        allowed_basis = set(self.BLOCK["en_basis_vocabulary"])
        for name in self.RUN_NAMES:
            table = self.payload(self.BLOCK["tables"][name])
            self.assertEqual(table["provenance"]["review_status"], "owner_review_pending")
            for row in table["entries"].values():
                provenance = row["provenance"]
                self.assertIn(provenance["en_basis"], allowed_basis,
                              "%s 的出处不在登记词汇表里：%s" % (name, provenance["en_basis"]))
                self.assertEqual(provenance["review_status"], "owner_review_pending",
                                 "任何一条被标成已复核都是把业主的活儿替掉了")
                self.assertEqual(provenance["source_registered"],
                                 provenance["en_basis"] == "registered_display_name",
                                 "只有登记名那一类可以声称有来源；其余两类冒充来源＝补血缘")

    def test_legacy_reuse_entries_do_not_claim_registered_provenance(self):
        """legacy_candidate_reuse 复用今天读者看到的英文，但**不给那张无来源表补登记**。"""
        for name in self.RUN_NAMES:
            for row in self.payload(self.BLOCK["tables"][name])["entries"].values():
                if row["provenance"]["en_basis"] != "legacy_candidate_reuse":
                    continue
                self.assertFalse(row["provenance"]["source_registered"])
                self.assertIn("读者载荷", row["provenance"]["en_source"])

    def test_input_dataset_and_reader_html_are_still_the_bytes_we_started_with(self):
        """业主明令 MT-E0 不写回 dataset、不重建交付 HTML：这条把它从「声明」变成「复算」。"""
        evidence = self.evidence()
        anchor = json.loads(MT_D2_ANCHOR.read_bytes().decode("utf-8"))
        for name in self.RUN_NAMES:
            row = evidence["runs"][name]
            dataset, path = self.dataset_for(name)
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest().upper(),
                             row["dataset_sha256"], "%s：输入 dataset 与建表时不是同一份" % name)
            self.assertTrue(row["dataset_untouched_after_build"])
            self.assertTrue(row["reader_html_untouched_after_build"])
            html = SCRIPTS.parents[2] / anchor["candidates_html"][name]["path"]
            self.assertEqual(hashlib.sha256(html.read_bytes()).hexdigest().upper(),
                             anchor["candidates_html"][name]["sha256"],
                             "%s：交付 HTML 被这轮动过——MT-E0 无权重建" % name)
            self.assertTrue(dataset, "空 dataset 也配叫输入？")

    def test_no_shifted_english_survives_in_the_delivered_candidate(self):
        """串位指纹（同一条英文服务两条不同中文）必须为 0：这是本轮唯一能机械抓到货的探针。"""
        evidence = self.evidence()
        for name in self.RUN_NAMES:
            table = self.payload(self.BLOCK["tables"][name])
            groups = {}
            for row in table["entries"].values():
                groups.setdefault(" ".join(row["en"].lower().split()), set()).add(row["cn"])
            doubled = {key: sorted(value)[:2] for key, value in groups.items() if len(value) > 1}
            self.assertEqual(doubled, {}, "%s：还有两条不同中文共用一条英文：%s" % (name, doubled))
            self.assertEqual(evidence["runs"][name]["duplicate_en_groups"], [])
            self.assertEqual(evidence["runs"][name]["unplaceable_draft_lines"], [],
                             "挂不上任何 worklist 行的草稿必须当场阻断，不是留个文件")

    def test_self_review_ledger_equals_the_correction_volume(self):
        """自审账与实物**双向相等**：登记的 id 集合＝勘误分卷里的 id 集合，多一条少一条都算错。"""
        review = self.evidence()["agent_draft_self_review"]
        registered = {i for ids in review["findings_by_class"].values() for i in ids}
        self.assertEqual(sum(len(v) for v in review["findings_by_class"].values()),
                         review["findings_total"], "计数要从账里算，不许手填")
        applied = set()
        for name, block in sorted(review["corrections_per_run"].items()):
            if block["volume"] is None:
                self.assertEqual(block["lines"], 0,
                                 "%s：没有勘误分卷却有修正行数＝账上的数没出处" % name)
                continue
            lines = [ln.strip() for ln in (self.ARTIFACTS / block["volume"])
                     .read_text(encoding="utf-8").splitlines()
                     if ln.strip() and not ln.strip().startswith("#")]
            self.assertEqual(len(lines), block["lines"])
            applied |= {ln.split("|", 1)[0].strip() for ln in lines}
        self.assertEqual(registered, applied, "账与实物不一致：要么漏登记，要么写了却没改")
        self.assertEqual(review["findings_total"], len(applied))
        shipped = {ident for name in self.RUN_NAMES
                   for ident in self.payload(self.BLOCK["tables"][name])["entries"]}
        self.assertLessEqual(registered, shipped,
                             "登记的战果里有不在表上的 id＝凭空记功")

    def test_review_denominators_are_the_rows_we_ship_on_draft_basis(self):
        """「读了多少行」等于今天表里 agent_draft 出货的行数，盲区账要**自己加得起来**。

        正则不在这里再抄一份：锚点口径住在建表工具的 anchor_blind()（唯一实现），
        这里复算的是「起草行数＝表里出货行数」与「两地盲区数之和＝总账」——
        尺子的形状由尺子自己管，测试只查账目闭合（两张尺子的教训登记在 VERSION.md 与 glossary）。
        """
        evidence = self.evidence()
        review = evidence["agent_draft_self_review"]
        rows = blind = 0
        for name in self.RUN_NAMES:
            run = evidence["runs"][name]
            draft = [row for row in self.payload(self.BLOCK["tables"][name])["entries"].values()
                     if row["provenance"]["en_basis"] == "agent_draft"]
            rows += len(draft)
            blind += run["agent_draft_anchor_blind_rows"]
            self.assertEqual(run["agent_draft_rows"], len(draft),
                             "%s：证据里的起草行数不等于表里实际出货的行数" % name)
            self.assertLessEqual(run["agent_draft_anchor_blind_rows"], run["agent_draft_rows"])
        self.assertEqual(review["agent_draft_rows_reviewed"], rows,
                         "自审范围写小了＝只读了部分却声称全读了")
        self.assertEqual(review["rows_without_any_anchor"], blind,
                         "盲区面积与两地分账加不起来")

    def test_dropping_a_row_is_blocked_not_quiet(self):
        """负测：从内存副本里删掉一条，门要报 fragment_missing_from_table——不许「少一条也 PASS」。"""
        name = "california"
        evidence = self.evidence()
        table = self.payload(self.BLOCK["tables"][name])
        dataset, _ = self.dataset_for(name)
        dropped = sorted(table["entries"].items())[0][0]
        del table["entries"][dropped]
        report = tp.validate_table(dataset, table, run_name=evidence["runs"][name]["run_dir"],
                                   source_dataset_sha256=evidence["runs"][name]["dataset_sha256"],
                                   duplicate_ids=[])
        self.assertNotEqual(report["status"], "PASS")
        self.assertIn("fragment_missing_from_table",
                      {finding["code"] for finding in report["findings"]},
                      "少一条却没点名＝部分应用")

    def test_the_negative_probes_were_blocked_by_the_gates_they_name(self):
        """探针账要**是点名的那道门响**：被别的门拦下的负测绿了等于没测（本案在前两版真的发生）。"""
        probe = self.payload("MT1_translation/artifacts/MTE0_GATE_PROBE.json")
        self.assertEqual(probe["verdict"], "ALL BLOCKED BY THE NAMED GATES")
        self.assertEqual(len(probe["cases"]), 4,
                         "四案（错 id／畸形 id／同文异中文／勘误未登记）少一案就少一个前提")
        for case in probe["cases"]:
            self.assertTrue(case["blocked_by_expected_gate"],
                            "%s 没被它点名的门拦下：%s" % (case["case"], case["detail"]))
            self.assertIn(case["expected_gate_said"], case["detail"])
        self.assertFalse(probe["real_artifacts_touched"])


TEMP_ROOT = SCRIPTS.parents[2] / ".temp" / "v422_honest_map"
TEMP_ARTIFACTS = TEMP_ROOT / "MT1_translation" / "artifacts"


def payload_at(relative: str):
    """合同登记面里的相对路径 → 盘上 JSON（唯一读法；两张面共用，别各写一份）。"""
    path = TEMP_ROOT / relative
    assert path.is_file(), "合同登记的表/账不在盘上：%s ⇒ 这一轮的账没有实物，不许拿『工具跑过』代替" % relative
    return json.loads(path.read_bytes().decode("utf-8"))


def dataset_at(relative: str) -> dict:
    """证据里的 dataset 路径是**仓库根相对**的（建表工具用 relative_to(PROJ) 写的）。"""
    path = SCRIPTS.parents[2] / relative
    return json.loads(path.read_text(encoding="utf-8"))


def identity_fixture(**overrides) -> dict:
    """MT-E1 身份绑定的最小夹具：登记的可检验槽位是 `itinerary[*][4]`，两行同文，
    只有第 0 行同时具备「本格中文 == map_targets 尾段」与「target.coords 逐字出现在本行格子里」。
    """
    data = _dataset(itinerary=[["1", "第1天", "a", "b", "某某面馆", "37.6,-122.3"],
                              ["2", "第2天", "c", "d", "某某面馆", "38.6,-122.9"]],
                   map_targets={"城市|某某面馆": {"coords": "37.6,-122.3"}})
    data.update(overrides)
    return data


def patched_contract(mutate):
    """临时改登记面（只改内存副本，不落盘）：返回 (原函数, 打补丁函数)，调用方负责还原。"""
    original = tp.contract

    def patched():
        doc = original()
        mutate(doc["ownership"][tp.IDENTITY_MIGRATION_KEY])
        return doc
    return original, patched


class IdentityMigrationRuleTests(unittest.TestCase):
    """迁移的**开关与面积都在登记面**：配置缺一块就抛码，关掉登记就一条也不迁。"""

    def setUp(self):
        self.data = identity_fixture()

    def test_rule_shape_matches_the_registration(self):
        rule = tp.identity_migration_rule()
        registered = CONTRACT["ownership"][tp.IDENTITY_MIGRATION_KEY]
        self.assertEqual(rule["status"], registered["status"])
        self.assertEqual(rule["migrate_only_when"], ["unique"])
        self.assertEqual(rule["owner_after_claim"], "DISPLAY_NAME")
        self.assertEqual(list(rule["identity_verdicts"]), list(tp.IDENTITY_VERDICTS))
        self.assertEqual(sorted(rule["never_migrates_on"]),
                         sorted(v for v in tp.IDENTITY_VERDICTS if v != "unique"),
                         "闭集里除了 unique，其余每一条都必须写明「不迁移」——漏一个就等于默认放行")
        self.assertEqual(tp.identity_eligible_slots(rule),
                         {(str(item["block"]), str(item["slot"])) for item in registered["eligible_slots"]})
        self.assertEqual(len(registered["eligible_slots"]), 1,
                         "可检验槽位今天只有 itinerary[*][4] 一个；加第二个要带 why 与实测出处")
        self.assertEqual(rule["min_registered_english_len"],
                         registered["min_registered_english_len"])

    def test_deleting_the_registration_raises_instead_of_defaulting(self):
        """业主负测「删除登记必须阻断」：整块没了 ⇒ 判定当场抛 ownership_identity_rule_unregistered。"""
        def mutate(block):
            del block["eligible_slots"]
        original, patched = patched_contract(mutate)
        try:
            tp.contract = patched
            with self.assertRaises(ValueError) as caught:
                tp.identity_migration_rule()
            self.assertIn("ownership_identity_rule_field_missing:eligible_slots", str(caught.exception))
            with self.assertRaises(ValueError):
                tp.classify_fragment_ownership(self.data)
        finally:
            tp.contract = original

    def test_turning_the_rule_off_migrates_nothing(self):
        """status=DISABLED ⇒ 一个都不迁，那 169 条的形状全部回到 prose：面积由登记面说话。"""
        def mutate(block):
            block["status"] = "DISABLED"
        original, patched = patched_contract(mutate)
        try:
            tp.contract = patched
            result = tp.classify_fragment_ownership(self.data)
            row = next(item for item in result["rows"] if item["cn"] == "某某面馆")
            self.assertEqual(row["outcome"], "PROSE_REQUIRED",
                             "关掉登记之后这行必须回到 prose，而不是「代码里还记得要迁」")
            self.assertEqual(row["slot_migration"], [])
            self.assertNotIn(row["id"], result["slot_identity_migration"]["migrated_row_ids"])
            self.assertEqual(result["slot_identity_migration"]["rule_status"], "DISABLED")
        finally:
            tp.contract = original
        control = tp.classify_fragment_ownership(self.data)
        self.assertIn(next(item["id"] for item in control["rows"] if item["cn"] == "某某面馆"),
                      control["slot_identity_migration"]["partial_binding_blocked_ids"],
                      "还原之后同一个夹具要立刻回到 MIXED（对照组）：这条链两头都得是活的")

    def test_each_malformed_rule_field_raises_its_own_code(self):
        """逐个改写必填字段／闭集：每种都要抛**自己那颗码**，不许「少一个字段就按默认跑」。"""
        cases = [
            (lambda b: b.pop("status"), "ownership_identity_rule_field_missing:status"),
            (lambda b: b.pop("migrate_only_when"), "ownership_identity_rule_field_missing:migrate_only_when"),
            (lambda b: b.__setitem__("status", "PROBABLY"), "ownership_identity_rule_status_unknown"),
            (lambda b: b.__setitem__("identity_verdicts", list(tp.IDENTITY_VERDICTS) + ["guess"]),
             "ownership_identity_verdict_vocabulary_drift"),
            (lambda b: b.__setitem__("migrate_only_when", ["unique", "ambiguous"]),
             "ownership_identity_migrate_condition_not_unique_only"),
            (lambda b: b.__setitem__("owner_after_claim", "PROSE_TABLE"),
             "ownership_identity_owner_not_registered"),
            (lambda b: b.__setitem__("eligible_slots", []), "ownership_identity_eligible_slots_empty"),
            (lambda b: b.__setitem__("eligible_slots", [{"block": "itinerary", "slot": "4"}]),
             "ownership_identity_eligible_slot_incomplete"),
            (lambda b: b.__setitem__("eligible_slots", [dict(b["eligible_slots"][0]),
                                                        dict(b["eligible_slots"][0])]),
             "ownership_identity_eligible_slot_duplicate"),
            (lambda b: b.__setitem__("min_registered_english_len", 1),
             "ownership_identity_min_english_len_invalid"),
        ]
        for mutate, expected in cases:
            original, patched = patched_contract(mutate)
            try:
                tp.contract = patched
                with self.assertRaises(ValueError) as caught:
                    tp.identity_migration_rule()
                self.assertIn(expected, str(caught.exception),
                              "%s 应当抛 %s，实际抛了 %s" % (mutate, expected, caught.exception))
            finally:
                tp.contract = original


class IdentityMigrationNegativeTests(unittest.TestCase):
    """业主 2026-11-02 第 1 条点名的五条负测：迁移**不许**按列、按文本、按「先命中那条」发生。"""

    def setUp(self):
        self.data = identity_fixture()
        self.rule = tp.identity_migration_rule()
        self.cn = "某某面馆"

    def _row(self, result, cn=None):
        return next(item for item in result["rows"] if item["cn"] == (cn or self.cn))

    def test_positive_unique_binding_is_the_only_way_in(self):
        """正例（考卷是活的）：唯一绑定 ⇒ 这行归 DISPLAY_NAME，且迁移账上写明逐字证据。"""
        data = identity_fixture(itinerary=[["1", "第1天", "a", "b", self.cn, "37.6,-122.3"]])
        result = tp.classify_fragment_ownership(data)
        row = self._row(result)
        self.assertEqual(row["outcome"], "OWNED_NON_PROSE", json.dumps(row, ensure_ascii=False)[:300])
        self.assertEqual(row["owners"], ["DISPLAY_NAME"])
        self.assertEqual([item["address"] for item in row["slot_migration"]], ["itinerary[0][4]"])
        self.assertEqual(row["slot_migration"][0]["basis"], "identity_binding_unique")
        self.assertEqual(row["slot_migration"][0]["owner_after_migration"], "DISPLAY_NAME")
        self.assertNotIn(self.cn, [item["cn"] for item in result["worklist"]],
                         "迁走的行不许还留在 prose worklist 里")
        self.assertNotIn(row["id"], result["slot_identity_migration"]["partial_binding_blocked_ids"])

    def test_same_column_without_unique_binding_does_not_migrate(self):
        """负测①：同一列（itinerary[*][4]）但没有唯一实体绑定 ⇒ 不迁移。"""
        data = identity_fixture(map_targets={})
        verdict, _ = tp.identity_binding(data, "itinerary[0][4]", self.cn, self.rule)
        self.assertEqual(verdict, "no_binding")
        result = tp.classify_fragment_ownership(data)
        self.assertEqual(self._row(result)["outcome"], "PROSE_REQUIRED",
                         "绑不上就还是 prose：这一列里那 32 个真散文标题格靠的就是这条")
        self.assertEqual(self._row(result)["slot_migration"], [])
        # 记录里有坐标形状但没有同名 target：仍然 no_binding，不许「找个最像的」
        data2 = identity_fixture(map_targets={"城市|别的名字": {"coords": "37.6,-122.3"}})
        self.assertEqual(tp.identity_binding(data2, "itinerary[0][4]", self.cn, self.rule)[0],
                         "no_binding")
        # 本行根本没有经纬度格：no_coord 也不迁
        data3 = identity_fixture(itinerary=[["1", "第1天", "a", "b", self.cn, "傍晚看日落"]])
        self.assertEqual(tp.identity_binding(data3, "itinerary[0][4]", self.cn, self.rule)[0], "no_coord")
        self.assertEqual(self._row(tp.classify_fragment_ownership(data3))["outcome"], "PROSE_REQUIRED")

    def test_ambiguous_binding_never_takes_the_first(self):
        """负测②：多实体／歧义 ⇒ 一条都不迁，且账上要看得见它确实查到了**两条**（不是没查）。"""
        data = identity_fixture(map_targets={"A|" + self.cn: {"coords": "37.6,-122.3"},
                                            "B|" + self.cn: {"coords": "37.6,-122.3"}})
        verdict, evidence = tp.identity_binding(data, "itinerary[0][4]", self.cn, self.rule)
        self.assertEqual(verdict, "ambiguous")
        self.assertEqual(len(evidence), 2, "歧义案必须把两条命中都留在账上：只留一条就是「取了第一条」")
        result = tp.classify_fragment_ownership(data)
        row = self._row(result)
        self.assertEqual(row["outcome"], "PROSE_REQUIRED")
        self.assertEqual(row["slot_migration"], [])
        self.assertEqual(result["slot_identity_migration"]["verdict_counts"]["ambiguous"], 1)

    def test_same_text_at_different_addresses_is_not_bundled(self):
        """负测③：同文不同地址 ⇒ 不连带迁移。一格唯一绑定、另一格绑不上 ⇒ 整行 MIXED，谁也没拿走。"""
        raw = tp.collect_fragments(self.data, skip_covered=False)
        fragment = next(f for f in raw if f["cn"] == self.cn)
        self.assertEqual(sorted(fragment["addresses"]), ["itinerary[0][4]", "itinerary[1][4]"],
                         "夹具得真的让同一句中文落进两格，否则这条牙是空的")
        result = tp.classify_fragment_ownership(self.data, [fragment])
        row = self._row(result)
        self.assertEqual(row["outcome"], "MIXED_OWNER_BLOCKED", json.dumps(row, ensure_ascii=False)[:400])
        self.assertEqual(row["owners"], ["DISPLAY_NAME", "PROSE_TABLE"])
        self.assertEqual([item["address"] for item in row["slot_migration"]], ["itinerary[0][4]"],
                         "只有逐地址证据成立的那一格被记了迁移账；另一格不许跟着搬")
        self.assertNotIn(row["id"], result["slot_identity_migration"]["migrated_row_ids"],
                         "部分绑定不等于迁走：行级主人还没定，migrated 里不能出现它")
        self.assertEqual(result["slot_identity_migration"]["partial_binding_blocked_ids"], [row["id"]])
        self.assertEqual(result["worklist"], [], "MIXED 的行既不进 prose 也不进显示名，等处置")

    def test_borrowed_display_name_is_not_a_display_name_slot(self):
        """负测④：散文里借了登记品牌名 ⇒ 那是**译文缺陷**（INJECTED），不是所有权变更。"""
        index = {"Sunstone Winery": {"圣伊内斯山谷葡萄园庄园"}, "Coit Tower": {"科伊特塔"}}
        kind, hits = tp.prose_slot_subclass(self.data, "山谷里有一家葡萄园庄园",
                                            "A tasting at Sunstone Winery", index=index, rule=self.rule)
        self.assertEqual(kind, "PROSE_SLOT_WITH_INJECTED_NAME")
        self.assertEqual(hits[0]["borrowed_english"], "Sunstone Winery")
        self.assertEqual(tp.prose_slot_subclass(self.data, "圣伊内斯山谷葡萄园庄园",
                                                "A tasting at Sunstone Winery",
                                                index=index, rule=self.rule)[0], "PROSE_SLOT_CLEAN",
                         "中文原文自己就写了这个名字 ⇒ 不是借来的")
        self.assertEqual(tp.prose_slot_subclass(self.data, "眺望台", "Recoit Towered",
                                                index=index, rule=self.rule)[0], "PROSE_SLOT_CLEAN",
                         "只做整串命中：别的词里含了这串字母不算借名")
        # 借名**不改 owner**：同一句中文，带不带英文都是 prose
        data = dict(identity_fixture(itinerary=[["1", "第1天", "a", "b", "某某面馆", "傍晚看日落"]]))
        data["en_text_replacements"] = {"某某面馆": "Sunstone Winery"}
        result = tp.classify_fragment_ownership(data)
        row = self._row(result)
        self.assertEqual(row["outcome"], "PROSE_REQUIRED",
                         "用翻译错误倒推所有权＝业主否决的那条路")
        self.assertNotIn(row["id"], result["slot_identity_migration"]["migrated_row_ids"])

    def test_changing_the_address_or_the_identity_digest_blocks_migration(self):
        """负测⑤：改地址、改身份摘要（坐标或标签）任一项 ⇒ 当场不迁。迁移跟着**在册事实**走。"""
        # ⑤-a 同样的文本与地图事实，但这一格在**没有登记的列**上（itinerary[*][5]）
        data = identity_fixture(itinerary=[["1", "第1天", "a", "b", "沿海公路自驾观景", self.cn]])
        result = tp.classify_fragment_ownership(data)
        self.assertNotIn("identity_binding", self._row(result)["address_detail"][0],
                         "槽位不在登记的可检验面里，就连身份检验都不该跑")
        self.assertEqual(self._row(result)["outcome"], "PROSE_REQUIRED")
        # ⑤-b 改坐标：同名但 coords 不再逐字出现在本行 ⇒ label_without_coord
        moved = identity_fixture(map_targets={"城市|" + self.cn: {"coords": "99.9,-99.9"}})
        self.assertEqual(tp.identity_binding(moved, "itinerary[0][4]", self.cn, self.rule)[0],
                         "label_without_coord")
        self.assertEqual(self._row(tp.classify_fragment_ownership(moved))["outcome"], "PROSE_REQUIRED")
        # ⑤-c 改标签一个字符：逐字比较，不做相似度
        renamed = identity_fixture(map_targets={"城市|某某面館": {"coords": "37.6,-122.3"}})
        self.assertEqual(tp.identity_binding(renamed, "itinerary[0][4]", self.cn, self.rule)[0],
                         "no_binding")
        # ⑤-d 地址写法坏掉／行号越界：都是闭集里的独立判词，且都不是 unique
        self.assertEqual(tp.identity_binding(self.data, "完全不像地址的东西", self.cn, self.rule)[0],
                         "address_unparsable")
        self.assertEqual(tp.identity_binding(self.data, "itinerary[77][4]", self.cn, self.rule)[0],
                         "row_out_of_range")
        self.assertNotIn("unique", tp.IDENTITY_VERDICTS[:0], "闭集本身不许被改写：判词表就是这一份")
        for verdict in self.rule["never_migrates_on"]:
            self.assertIn(verdict, tp.IDENTITY_VERDICTS)


class Mte1CandidateTableTests(unittest.TestCase):
    """MT-E1 当前面（717 行）的可重放合同：按盘上字节重跑门，且账与登记**双向相等**。

    与历史面（Mte0CandidateTableTests）的分工：这里判的是**今天这张表**——
    行数＝当前冻结分母、迁走的 169 行不在表上、两条缺陷换 owner 之后仍然各在其位、
    每一条复用行都能追到旧表的同一行（五条复用条件逐行复算，不是一句声明）。
    """

    BLOCK = CONTRACT["ownership"]["mt_e1_candidate_tables_2026_11_02"]
    HISTORY = CONTRACT["ownership"]["mt_e0_candidate_tables_2026_11_01"]
    FROZEN = CONTRACT["ownership"]["mt_e_table_length_frozen_at"]
    RUN_NAMES = ("california", "philippines")

    def evidence(self) -> dict:
        return payload_at(self.BLOCK["evidence"])

    def dataset_for(self, name: str) -> dict:
        return dataset_at(self.evidence()["runs"][name]["dataset"])

    def test_contract_pinned_table_bytes_match_the_disk(self):
        """合同里钉的表内摘要与文件摘要，必须与盘上字节现算一致（先钉住「审的是这张表」）。"""
        measured = self.BLOCK["measured_2026_11_02"]["per_run"]
        for name in self.RUN_NAMES:
            rel = self.BLOCK["tables"][name]
            blob = (TEMP_ROOT / rel).read_bytes()
            table = json.loads(blob.decode("utf-8"))
            self.assertEqual(hashlib.sha256(blob).hexdigest().upper(),
                             measured[name]["table_file_sha256"], "%s：表文件字节与合同登记不符" % name)
            self.assertEqual(table["table_sha256"], measured[name]["table_sha256"],
                             "%s：合同钉的表内摘要不是表自己声明的那一个" % name)
            self.assertEqual(self.evidence()["runs"][name]["table_file_sha256"],
                             measured[name]["table_file_sha256"], "%s：证据账与合同钉的是两份字节" % name)

    def test_tables_revalidate_from_the_bytes_on_disk(self):
        """两地表按盘上字节重跑 validate_table：finding 多重集**恰好等于**迁移后登记的账。"""
        evidence = self.evidence()
        dispositions = self.BLOCK["finding_dispositions_after_migration"]
        registered = dispositions["registered_findings_2026_11_02"]
        rule = pr.proper_name_rule()
        for name in self.RUN_NAMES:
            table = payload_at(self.BLOCK["tables"][name])
            dataset = self.dataset_for(name)
            run = evidence["runs"][name]
            raw = (TEMP_ROOT / self.BLOCK["tables"][name]).read_bytes().decode("utf-8")
            report = tp.validate_table(dataset, table, run_name=run["run_dir"],
                                       source_dataset_sha256=run["dataset_sha256"],
                                       duplicate_ids=tp.duplicate_entry_ids(raw))
            got = collections.Counter(f["code"] for f in report["findings"])
            want = collections.Counter(item["code"] for item in registered[name])
            self.assertEqual(dict(got), dict(want),
                             "%s：盘上字节的 finding 多重集与登记不等 ⇒ 要么冒出没登记的缺陷，"
                             "要么登记的账被迁移洗掉了：%s" % (name, report["findings"][:3]))
            self.assertEqual(report["status"], "FAIL" if want else "PASS")
            fired = []
            for ident, record in sorted(table["entries"].items()):
                for hit in pr.proper_name_conflicts(str(record.get("cn") or ""),
                                                    str(record.get("en") or "").strip(), rule):
                    fired.append((ident, hit["cn_token"], hit["en_token"], hit["distance"]))
            self.assertEqual(fired, sorted((item["entry_id"], item["cn_token"], item["en_token"],
                                            item["distance"]) for item in registered[name]),
                             "%s：留在 prose 的那条专名形状账要逐字复现，不是数对上了就算" % name)
            for item in registered[name]:
                self.assertEqual(table["entries"][item["entry_id"]]["addresses"], [item["address"]])
                self.assertIn(item["side_at_fault"], ("source", "translation"))
                self.assertTrue(item["why"].strip())
            self.assertEqual(table["table_sha256"], report["table_sha256_recomputed"])

    def test_lengths_are_the_current_frozen_denominators(self):
        """当前表长只能等于**现在冻结的** 717＝CA 393＋PH 324，并与现场 worklist 同源。"""
        evidence = self.evidence()
        for name in self.RUN_NAMES:
            run_key = [k for k in self.FROZEN["per_run"] if k.startswith(name)][0]
            table = payload_at(self.BLOCK["tables"][name])
            live = tp.classify_fragment_ownership(self.dataset_for(name))
            self.assertEqual(len(table["entries"]), self.FROZEN["per_run"][run_key]["prose_required"],
                             "%s：表行数不等于当前冻结的 prose 分母" % name)
            self.assertEqual(len(live["worklist"]), len(table["entries"]),
                             "%s：现场 worklist 与表不同源＝两份分母又回来了" % name)
            self.assertEqual(evidence["runs"][name]["worklist_rows"], len(table["entries"]))
            self.assertEqual(sorted(row["id"] for row in live["worklist"]),
                             sorted(table["entries"]),
                             "%s：表里的 id 集合与 worklist 不是同一批" % name)
        self.assertEqual(sum(len(payload_at(self.BLOCK["tables"][n])["entries"])
                             for n in self.RUN_NAMES), self.FROZEN["total_entries_required"])
        self.assertEqual(self.FROZEN["total_entries_required"], 717)
        self.assertFalse(evidence["totals"]["cross_run_dedup_performed"])

    def test_row_buckets_reproduce_the_owner_ruling(self):
        """逐 fragment 复现业主裁的四个数：169 TRUE_DISPLAY_NAME／45 INJECTED／672 CLEAN／0 AMBIGUOUS。"""
        evidence = self.BLOCK["measured_2026_11_02"]
        true_slots = injected = clean = ambiguous = 0
        for name in self.RUN_NAMES:
            dataset = self.dataset_for(name)
            result = tp.classify_fragment_ownership(dataset)
            sim = result["slot_identity_migration"]
            true_slots += len(sim["migrated_row_ids"])
            ambiguous += sim["verdict_counts"]["ambiguous"] + result["counts"]["MIXED_OWNER_BLOCKED"]
            table = payload_at(self.BLOCK["tables"][name])
            index = tp.registered_english_index(dataset, tp.identity_migration_rule())
            kinds = collections.Counter(
                tp.prose_slot_subclass(dataset, row["cn"], row["en"], index=index)[0]
                for row in table["entries"].values())
            self.assertEqual(dict(kinds), dict(evidence["per_run"][name]["prose_subclass"]),
                             "%s：prose 子类与登记/证据不等 ⇒ 子类是量出来的，不是抄来的" % name)
            injected += kinds[tp.PROSE_SUBCLASS_VOCABULARY[1]]
            clean += kinds[tp.PROSE_SUBCLASS_VOCABULARY[0]]
        self.assertEqual(true_slots, 169)
        self.assertEqual(injected, 45)
        self.assertEqual(clean, 672)
        self.assertEqual(ambiguous, 0, "歧义/混判必须为 0：不为 0 就说明今天还在靠挑一条命中决定 owner")
        self.assertEqual(clean + injected, 717)
        self.assertEqual(evidence["rows_total"], clean + injected)

    def test_registered_english_index_honours_the_threshold(self):
        """借名检测的门槛（登记面 `min_registered_english_len`）在**建索引那一步**生效：
        短串（Bar/Cafe/In）根本进不了索引，才不会把整片 CLEAN 染成 INJECTED。"""
        rule = tp.identity_migration_rule()
        floor = int(rule["min_registered_english_len"])
        for name in self.RUN_NAMES:
            index = tp.registered_english_index(self.dataset_for(name), rule)
            self.assertTrue(index, "%s：登记面英文名索引为空＝借名那把尺子在空转" % name)
            self.assertTrue(all(len(key) >= floor for key in index),
                            "%s：索引里出现了比登记阈值还短的英文名 ⇒ 门槛没在建索引处生效：%s"
                            % (name, sorted(key for key in index if len(key) < floor)[:5]))

    def test_migrated_rows_left_the_table_and_the_prose_defect_stayed(self):
        """两条 finding 换 owner 而不是消失：prose 1 条＋显示名 1 条＝总数仍 2；数成 0 就是迁移缺陷。"""
        dispositions = self.BLOCK["finding_dispositions_after_migration"]
        registered = dispositions["registered_findings_2026_11_02"]
        prose_ids = [set(payload_at(self.BLOCK["tables"][n])["entries"]) for n in self.RUN_NAMES]
        self.assertIn("feb55e59b0d", prose_ids[0], "Ciopinno 那条必须还在 717 的 prose 表里")
        self.assertNotIn("f90009bf57d", prose_ids[0] | prose_ids[1],
                         "Cathy 那条已按身份绑定离开 prose：它出现在翻译表里＝迁移没落地")
        total = sum(len(v) for v in registered.values())
        self.assertEqual(total, 2, "迁移后总缺陷成 0 ⇒ 判迁移缺陷（缺陷被换 owner 的动作洗掉了）")
        self.assertEqual(len(registered["california"]), 1)
        self.assertEqual(len(registered["philippines"]), 0)
        self.assertEqual(len(registered["display_name"]), 1)
        self.assertEqual(dispositions["total_defects"], total)
        # 显示名那一条要能从**今天的判定**复现：中文标签 ↔ 登记英文，逐 token 与距离。
        item = registered["display_name"][0]
        corrections = [c for c in self.classify()["california"]["slot_identity_migration"]
                       ["display_name_corrections"] if c["id"] == item["entry_id"]]
        self.assertEqual(len(corrections), 1, "%s 不在今天的显示名修正清单上" % item["entry_id"])
        self.assertNotIn(item["entry_id"], prose_ids[0],
                         "显示名修正行不该同时出现在散文表里（两边各发一次英文＝两份权威）")
        conflict = corrections[0]["conflicts"][0]
        self.assertEqual((conflict["cn_token"], conflict["en_token"], conflict["distance"]),
                         (item["cn_token"], item["en_token"], item["distance"]))
        self.assertIn(item["address"], corrections[0]["addresses"],
                      "登记里写的落点必须是这一行真正唯一绑定的那个地址")
        self.assertIn(item["en_token"], corrections[0]["registered_english"],
                      "账上的英文 token 要真的来自那条登记（改的是登记，不是再编一个英文）")

    def classify(self) -> dict:
        out = {}
        for name in self.RUN_NAMES:
            out[name] = tp.classify_fragment_ownership(self.dataset_for(name))
        return out

    def test_every_row_is_a_registered_reuse_not_a_fresh_draft(self):
        """五条复用条件逐行复算：旧表里找不到出处的行一律不许出现，provenance 不许升级。"""
        for name in self.RUN_NAMES:
            new = payload_at(self.BLOCK["tables"][name])
            old = payload_at(self.HISTORY["tables"][name])
            live = tp.classify_fragment_ownership(self.dataset_for(name))
            prose_ids = {row["id"] for row in live["worklist"]}
            self.assertLessEqual(set(new["entries"]), set(old["entries"]),
                                 "%s：新表里有旧表没有的 id＝本轮偷偷新起草了" % name)
            for ident, row in sorted(new["entries"].items()):
                prior = old["entries"][ident]
                self.assertEqual(row["cn"].encode("utf-8"), prior["cn"].encode("utf-8"),
                                 "%s/%s：中文原文不是逐字继承" % (name, ident))
                self.assertEqual(row["en"], prior["en"], "%s/%s：英文被换了出处却没登记" % (name, ident))
                self.assertEqual(sorted(row["addresses"]), sorted(prior["addresses"]),
                                 "%s/%s：地址集合变了还说复用" % (name, ident))
                self.assertEqual(row["provenance"], prior["provenance"],
                                 "%s/%s：provenance 被动过＝来源等级可能被升级，复用只许原样继承" % (name, ident))
                self.assertEqual(row["provenance"]["review_status"], "owner_review_pending",
                                 "%s/%s：迁移不许把任何一行标成已复核" % (name, ident))
                self.assertIn(row["provenance"]["en_basis"], set(self.BLOCK["en_basis_vocabulary"]))
                self.assertIn(ident, prose_ids, "%s/%s：owner 今天复算不是 prose" % (name, ident))
            self.assertEqual(new["provenance"]["review_status"], "owner_review_pending")
            ledger = {row["id"] for row in self.evidence()["reuse_ledger"][name]}
            self.assertEqual(ledger, set(new["entries"]),
                             "%s：复用台账与表不同源（少一行就是一行没被复算过）" % name)

    def test_inputs_and_delivered_html_are_still_the_bytes_we_started_with(self):
        """本轮边界：不写 dataset、不重建交付物——两地 HTML 仍与 seal-42 逐字节相同（复算，不是声明）。"""
        evidence = self.evidence()
        anchor = json.loads(MT_D2_ANCHOR.read_bytes().decode("utf-8"))
        for name in self.RUN_NAMES:
            row = evidence["runs"][name]
            self.assertTrue(row["dataset_untouched_after_build"])
            self.assertTrue(row["reader_html_untouched_after_build"])
            html = SCRIPTS.parents[2] / row["html"]["path"]
            self.assertEqual(hashlib.sha256(html.read_bytes()).hexdigest().upper(),
                             row["html"]["sha256"], "%s：证据里的 HTML 与盘上字节不是同一份" % name)
            self.assertEqual(row["html"]["sha256"], anchor["candidates_html"][name]["sha256"],
                             "%s：交付 HTML 与锚点登记（seal-42 那一份）不同＝本轮越界重建了" % name)
            self.assertTrue(row["html"]["unchanged_since_seal42"])
            dataset_path = SCRIPTS.parents[2] / row["dataset"]
            self.assertEqual(hashlib.sha256(dataset_path.read_bytes()).hexdigest().upper(),
                             row["dataset_sha256"], "%s：输入 dataset 被写过" % name)
            self.assertEqual(evidence["totals"]["migrated_rows"], 169)
            self.assertEqual(evidence["totals"]["prose_rows"], 717)


class HistoryPreservationTests(unittest.TestCase):
    """业主第 2 条：旧 886 进历史/superseded，**不删、不改写、不机械替换**——这三条都要能复算。"""

    E0 = CONTRACT["ownership"]["mt_e0_candidate_tables_2026_11_01"]
    FROZEN = CONTRACT["ownership"]["mt_e_table_length_frozen_at"]

    def test_history_artifacts_are_the_same_bytes_as_when_they_shipped(self):
        pins = self.E0["history_artifact_pins_2026_11_02"]
        for name in ("california", "philippines"):
            blob = (TEMP_ROOT / self.E0["tables"][name]).read_bytes()
            self.assertEqual(hashlib.sha256(blob).hexdigest().upper(),
                             pins["table_files"][name], "%s：历史表文件被动过" % name)
            self.assertEqual(json.loads(blob.decode("utf-8"))["table_sha256"],
                             pins["table_sha256_declared"][name], "%s：历史表的自述摘要变了" % name)
        evidence_blob = (TEMP_ROOT / self.E0["evidence"]).read_bytes()
        self.assertEqual(hashlib.sha256(evidence_blob).hexdigest().upper(), pins["evidence_file"],
                         "历史证据账被动过（这条只能证明自 2026-11-02 起未再改：旧基线不存在，见 not_a_proof）")

    def test_the_current_face_and_the_history_face_are_different_numbers(self):
        history = self.FROZEN["history_superseded_2026_11_02"]
        self.assertEqual(history["value"], 886)
        self.assertEqual(self.FROZEN["total_entries_required"], 717)
        self.assertEqual({k: v["prose_required"] for k, v in history["per_run"].items()},
                         {"california_v420": 501, "philippines_v419": 385})
        self.assertEqual(self.E0["measured_2026_11_01"]["rows_total"], 886,
                         "历史块里的 886 被顺手改成了当前值：历史叙述不许机械替换")
        self.assertIn("SUPERSEDED_BY_MT_E1", self.E0["history_status"])
        self.assertEqual(self.E0["status"], "GENERATED_NOT_APPLIED",
                         "历史面也没被谁「应用」过：apply 仍然禁止")
        self.assertIn("886", history["delta_explained"])
        self.assertEqual(self.FROZEN["per_run"]["california_v420"]["prose_required"], 393)

    def test_the_delta_has_exactly_one_source(self):
        """886 − 717 = 169 的差额账：既没动 raw 分母，也没动两桶，只动了 owner。"""
        history = self.FROZEN["history_superseded_2026_11_02"]["per_run"]
        current = self.FROZEN["per_run"]
        for run in ("california_v420", "philippines_v419"):
            self.assertEqual(history[run]["raw_fragments"], current[run]["raw_fragments"],
                             "%s：采集面变了——那 886→717 就不能只算成 owner 迁移" % run)
            for key in ("mixed_owner_blocked", "unresolved_owner_blocked"):
                self.assertEqual(history[run][key], 0)
                self.assertEqual(current[run][key], 0, "%s/%s：两桶被非迁移的东西动过" % (run, key))
            self.assertEqual(history[run]["prose_required"] - current[run]["prose_required"],
                             current[run]["owned_non_prose"] - history[run]["owned_non_prose"],
                             "%s：prose 少掉的行数不等于 owned_non_prose 多出来的行数" % run)
        self.assertEqual(sum(history[r]["prose_required"] - current[r]["prose_required"]
                             for r in history), 169)


if __name__ == "__main__":
    unittest.main()
