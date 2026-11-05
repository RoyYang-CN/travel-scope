# -*- coding: utf-8 -*-
"""§17.7.1 W1R-B1 ⑧ —— 人工冻结的外部审计向量（直接断言消费端 validate_map_targets()）。

这些期望值是按 §17.7.1 十条门禁的**文字**与 `W1RB1_probe/w1rb1_reproduction.json` 的实测反例手写的，
不来自配置、不来自 classify_reference 的实际输出、也不来自任何生成器：规则与期望值不得由同一个生成器
生产（那是 W1R-B 被驳回的自证循环）。`test_v421_ref_classifier.py` 转录探针矩阵，本模块转录审计判断，
两者互相制衡。

每个向量只问一个问题：这条 map_target 交给消费端，是被放行（allow）还是被拒绝（deny），
拒绝时错误信息里必须出现哪个码。若哪天有人放宽规则，本文件先红。
"""
import copy
import json
import re
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))

import data_model  # noqa: E402
from test_v421_map_contract import POLICY, target  # noqa: E402
CHECKLIST = ROOT.parents[1] / "V4.2.1_ITERATION_CHECKLIST.md"
REPRODUCTION = (ROOT.parents[1] / ".temp/v421_map_phase1/W1RB1_probe"
                / "w1rb1_reproduction.json")

DEFAULT_DISPOSITION = "unreviewed_second_judgment_candidate"
SUBSTRING_DISPOSITION = "pattern_substring_not_a_call_site"


def disposition_violations(inventory):
    """second_judgment_inventory 处置词表的**全部**门牙（唯一实现）；返回违规清单，空表＝过。

    为什么写成纯函数而不是几条 assertIn：负测必须能喂它一份「多了第二个持有人／形状变了／
    说明没指到因」的假台账。只查在盘数据的那种断言证明不了它会拒绝坏数据——它今天绿，
    可能只是因为今天的台账刚好干净（业主 2026-11-01 对「牙齿不够窄」的原话所指）。
    """
    violations = []
    allowed = list(inventory.get("disposition_allowed") or [])
    if allowed != [DEFAULT_DISPOSITION, SUBSTRING_DISPOSITION]:
        violations.append({"rule": "vocabulary_not_the_registered_pair",
                           "registered": allowed,
                           "must_be": [DEFAULT_DISPOSITION, SUBSTRING_DISPOSITION]})
    exception = inventory.get("disposition_substring_exception") or {}
    if exception.get("disposition") != SUBSTRING_DISPOSITION:
        violations.append({"rule": "exception_block_absent",
                           "registered": exception.get("disposition")})
    if not str(exception.get("retirement_rule") or "").strip():
        violations.append({"rule": "exception_has_no_retirement_rule"})
    holders = list(exception.get("holders") or [])
    if holders != ["scripts/pyc_hygiene.py"]:
        violations.append({"rule": "exception_holder_list_changed", "registered": holders,
                           "must_be": ["scripts/pyc_hygiene.py"]})
    entries = inventory.get("semantic_call_sites") or []
    authorities = [item["file"] for item in entries if item.get("is_classifier_authority")]
    if authorities != [inventory["authority"].split("::", 1)[0]]:
        violations.append({"rule": "classifier_authority_not_unique", "found": authorities})
    for item in entries:
        if item.get("is_classifier_authority"):
            continue          # 权威条目不吃这张词表，由上面那条规则单独钉
        name, disposition = item["file"], item.get("disposition")
        if disposition not in allowed:
            violations.append({"rule": "disposition_outside_closed_set",
                               "file": name, "disposition": disposition})
            continue
        if disposition == SUBSTRING_DISPOSITION:
            if name not in holders:
                violations.append({"rule": "second_holder_of_the_substring_disposition",
                                   "file": name,
                                   "holders_are": holders})
            if item.get("counts") != exception.get("pinned_shape"):
                violations.append({"rule": "exception_shape_not_pinned", "file": name,
                                   "counts": item.get("counts"),
                                   "pinned": exception.get("pinned_shape")})
            if sorted(item.get("touches") or []) != sorted(exception.get("pinned_touches") or []):
                violations.append({"rule": "exception_touches_not_pinned", "file": name,
                                   "touches": item.get("touches"),
                                   "pinned": exception.get("pinned_touches")})
            cause = str(exception.get("review_note_must_contain") or "")
            note = str(item.get("v422_review_note") or "")
            if not cause.strip() or cause not in note:
                violations.append({"rule": "exception_note_missing_cause_literal",
                                   "file": name, "required_in_note": cause})
        elif disposition != DEFAULT_DISPOSITION:
            violations.append({"rule": "non_default_value_that_is_not_the_exception",
                               "file": name, "disposition": disposition})
    return violations


def row(**override):
    """One honest background evidence row on a registered contract-fixture source."""
    base = {"source_type": "official_entity_page",
            "source_url_or_ref": "https://grandhotel.example/cebu",
            "retrieved_at": "2026-10-26", "supported_fields": ["display_name", "address"],
            "lineage_group": "lg-av-1", "content_digest": "sha256:abc", "usage_scope": "identity",
            "status": "complete", "address": "Oslob, Cebu City, 6000"}
    base.update(override)
    return base


def verified(**over):
    """identity_status=VERIFIED over one evidence row; the vectors below change the row."""
    base = target(identity_status="VERIFIED", address_status="VERIFIED",
                  address="Oslob, Cebu City, 6000", evidence=[row()])
    base.update(over)
    return base


# ------------------------------------------------------------------ hand-written audit vectors
# source:  §17.7.1 每一条正文；ref = 该项在清册里的编号
VECTORS = [
    # ① 坐标必须整段锚定，且 kind=coordinate 不得没有域内定位符
    ("AV-01", "①", "deny", ["LINK_DECLARED_URL_SHAPE_INVALID"],
     verified(link_mode="PUBLISHER_ENTITY_LINK",
              evidence=[row(source_type="publisher_entity_page",
                            declared_link_url="https://www.google.com/maps/@evil/@10.3,123.9,14z",
                            link_url_provider="google",
                            source_url_or_ref="https://grandhotel.example/cebu")]),
     "第一个 @ 片段是垃圾时，不得再去第二个 @ 后面找坐标并接受"),
    ("AV-02", "①", "deny", ["LINK_DECLARED_URL_SHAPE_INVALID"],
     verified(link_mode="PUBLISHER_ENTITY_LINK",
              evidence=[row(source_type="publisher_entity_page",
                            declared_link_url="https://www.google.com/maps/@10.3,123.9evil",
                            link_url_provider="google")]),
     "坐标后的尾随垃圾不得被忽略"),
    ("AV-03", "①", "deny", ["LINK_DECLARED_URL_SHAPE_INVALID"],
     verified(link_mode="PUBLISHER_ENTITY_LINK",
              evidence=[row(source_type="publisher_entity_page",
                            declared_link_url="https://www.google.com/maps/place/hotel/@evil/@1.0,2.0",
                            link_url_provider="google")]),
     "实体路径里带坏 @ 片段必须整体判 malformed，不得退回“实体页加装饰”"),
    ("AV-04", "①", "deny", ["LINK_DECLARED_URL_SHAPE_INVALID"],
     verified(link_mode="PUBLISHER_ENTITY_LINK",
              evidence=[row(source_type="publisher_entity_page",
                            declared_link_url="https://www.google.com/maps?ll=91.0,123.0",
                            link_url_provider="google")]),
     "纬度 91 越界不得判为坐标页"),
    ("AV-05", "①", "deny", ["LINK_DECLARED_URL_SHAPE_INVALID"],
     verified(link_mode="PUBLISHER_ENTITY_LINK",
              evidence=[row(source_type="publisher_entity_page",
                            declared_link_url="https://www.openstreetmap.org/mapjunk#map=15/10.3/123.9",
                            link_url_provider="osm")]),
     "未知路径 + #map= 片段是伪装，不得由片段造出 kind=coordinate"),

    # ② entity selector 必须检查全部值，且结果与顺序无关
    ("AV-06", "②", "deny", ["LINK_DECLARED_URL_SHAPE_INVALID"],
     verified(link_mode="PUBLISHER_ENTITY_LINK",
              evidence=[row(source_type="publisher_entity_page",
                            declared_link_url="https://www.google.com/maps?cid=1234567890123456789"
                                              "&cid=bad",
                            link_url_provider="google")]),
     "重复值里有一个坏值必须拒绝"),
    ("AV-07", "②", "deny", ["LINK_DECLARED_URL_SHAPE_INVALID"],
     verified(link_mode="PUBLISHER_ENTITY_LINK",
              evidence=[row(source_type="publisher_entity_page",
                            declared_link_url="https://www.google.com/maps?cid=bad&cid="
                                              "1234567890123456789",
                            link_url_provider="google")]),
     "同一对参数的反序必须得到同样的判定，不得一真一假"),
    ("AV-08", "②", "deny", ["LINK_DECLARED_URL_SHAPE_INVALID"],
     verified(link_mode="PUBLISHER_ENTITY_LINK",
              evidence=[row(source_type="publisher_entity_page",
                            declared_link_url="https://www.google.com/maps?cid=1234567890123456789"
                                              "&cid=9876543210987654321",
                            link_url_provider="google")]),
     "一个 URL 不得同时命名两个实体"),
    ("AV-09", "②", "deny", ["LINK_DECLARED_URL_SHAPE_INVALID"],
     verified(link_mode="PUBLISHER_ENTITY_LINK",
              evidence=[row(source_type="publisher_entity_page",
                            declared_link_url="https://www.google.com/maps?cid=1234567890123456789"
                                              "&q=grand+hotel",
                            link_url_provider="google")]),
     "entity selector 与 search selector 的未登记组合必须拒绝"),
    ("AV-10", "②", "deny", ["LINK_DECLARED_URL_SHAPE_INVALID"],
     verified(link_mode="PUBLISHER_ENTITY_LINK",
              evidence=[row(source_type="publisher_entity_page",
                            declared_link_url="https://www.google.com/maps/search/hotel?"
                                              "cid=1234567890123456789",
                            link_url_provider="google")]),
     "搜索路径 + 实体查询同族冲突不得按实体放行"),

    # ③ OSM 只有 node/way/relation 是地点
    ("AV-11", "③", "deny", ["LINK_DECLARED_URL_SHAPE_INVALID"],
     verified(link_mode="PUBLISHER_ENTITY_LINK",
              evidence=[row(source_type="publisher_entity_page",
                            declared_link_url="https://www.openstreetmap.org/user/12345",
                            link_url_provider="osm")]),
     "用户页不是地点实体"),
    ("AV-12", "③", "deny", ["IDENTITY_STABLE_REF_INVALID"],
     verified(evidence=[row(source_type="licensed_open_data_entity",
                            source_url_or_ref="https://www.openstreetmap.org/changeset/999",
                            source_entity_ref="osm:changeset/999")]),
     "changeset 编号不得进入身份证据或 osm_ref 血缘"),

    # ④ 外部 URL 不再默认成实体页
    ("AV-13", "④", "deny", ["EVIDENCE_SOURCE_UNCLASSIFIABLE"],
     verified(evidence=[row(source_url_or_ref="https://applemaps.com/place/x")]),
     "未登记域名（仿冒 provider 的名字）不得因为“路径够长”就被当实体页"),
    ("AV-14", "④", "deny", ["EVIDENCE_SOURCE_UNCLASSIFIABLE"],
     verified(evidence=[row(source_url_or_ref="https://www.tripadvisor.com/PrivacyPolicy")]),
     "隐私页不是凭据来源"),
    ("AV-15", "④", "deny", ["EVIDENCE_SOURCE_UNCLASSIFIABLE"],
     verified(evidence=[row(source_url_or_ref="https://www.tripadvisor.com/robots.txt")]),
     "robots.txt 不是凭据来源"),
    ("AV-16", "④", "deny", ["EVIDENCE_SOURCE_UNCLASSIFIABLE"],
     verified(evidence=[row(source_url_or_ref="https://www.tripadvisor.com/RegistrationLogin")]),
     "登录页不是凭据来源"),
    ("AV-17", "④", "deny", ["EVIDENCE_SOURCE_UNCLASSIFIABLE"],
     verified(evidence=[row(source_url_or_ref="https://www.tripadvisor.com/Restaurants-Cebu")]),
     "登记过的主机上，未登记的列表页形状同样不得充当实体页"),
    ("AV-18", "④", "allow", [],
     verified(evidence=[row(source_type="official_directory_entity_page",
                            source_url_or_ref="https://www.tripadvisor.com/"
                            "Restaurant_Review-philippines-abaca-baking-company-reviews.html")]),
     "冻结输入里实测到的实体路径形状必须仍然可用，否则收口就成了空拒绝"),

    # ⑤ 数据集/开放数据来源类型不得只凭 source_type 背书
    ("AV-19", "⑤", "deny", ["EVIDENCE_SOURCE_UNCLASSIFIABLE", "IDENTITY_STABLE_REF_INVALID"],
     verified(evidence=[row(source_type="licensed_open_data_entity", source_url_or_ref="garbage",
                            source_entity_ref="wikidata:Q42")]),
     "这就是审计实测到的端到端反例：曾经零错误进入 VERIFIED"),
    ("AV-20", "⑤", "deny", ["EVIDENCE_INCOMPLETE", "IDENTITY_STABLE_REF_INVALID"],
     verified(evidence=[row(source_type="licensed_open_data_entity", source_url_or_ref="",
                            source_entity_ref="wikidata:Q42")]),
     "空出处同样不得放行"),
    ("AV-21", "⑤", "deny", ["EVIDENCE_HOMEPAGE_ONLY", "IDENTITY_STABLE_REF_INVALID"],
     verified(evidence=[row(source_type="licensed_open_data_entity",
                            source_url_or_ref="https://philippines.travel/",
                            source_entity_ref="wikidata:Q42")]),
     "根页出处不得背书稳定引用"),
    ("AV-22", "⑤", "deny", ["IDENTITY_STABLE_REF_INVALID"],
     verified(evidence=[row(source_type="licensed_open_data_entity",
                            source_url_or_ref="dataset:osm_extracts#way/123456",
                            source_entity_ref="osm:way/123456")]),
     "本轮 registered_dataset_ids 为空，dataset: 出处必须报未登记而不是放行"),
    ("AV-23", "⑤", "allow", [],
     verified(evidence=[row(source_type="licensed_open_data_entity",
                            source_url_or_ref="https://www.openstreetmap.org/way/123456",
                            source_entity_ref="osm:way/123456",
                            lineage_group="lg-osm-123456")]),
     "OSM 对象页 + 同一对象的 osm_ref 是合法正路，收口不能把它一起关掉"),

    # ⑥ 发布方命名空间必须精确主机匹配并逐条登记
    ("AV-24", "⑥", "deny", ["IDENTITY_STABLE_REF_INVALID"],
     verified(evidence=[row(publisher_entity_id="co.uk:cebu-1")]),
     "多级公共后缀 co.uk 不是登记命名空间"),
    ("AV-25", "⑥", "deny", ["EVIDENCE_SOURCE_UNCLASSIFIABLE", "IDENTITY_STABLE_REF_INVALID"],
     verified(evidence=[row(source_url_or_ref="https://cebu.grandhotel.example/stay",
                            publisher_entity_id="grandhotel.example:cebu-1")]),
     "子域名伪造：出处主机不在登记清单，先于血缘判定被拒"),
    ("AV-26", "⑥", "deny", ["IDENTITY_STABLE_REF_INVALID"],
     verified(evidence=[row(source_url_or_ref="https://otherhotel.example/cebu",
                            publisher_entity_id="grandhotel.example:cebu-1")]),
     "两个都已登记的主机互相冒名，必须报血缘矛盾"),
    ("AV-27", "⑥", "allow", [],
     verified(evidence=[row(source_type="publisher_entity_page",
                            publisher_entity_id="grandhotel.example:cebu-1")]),
     "精确主机一致的命名空间引用必须仍然成立"),

    # ⑦ 死代码与陈旧封存值
    ("AV-28", "⑦", "deny", [], None, "W1R-A 的两个死常量必须已从实现里删除（见 DeadCodeTests）"),

    # ② 的正路：单一合法 selector 仍要能用
    ("AV-29", "②", "allow", [],
     verified(link_mode="PUBLISHER_ENTITY_LINK",
              evidence=[row(source_type="publisher_entity_page",
                            declared_link_url="https://www.google.com/maps/place/grand-hotel-cebu"
                                              "/@10.3,123.9,17z/data=!3m1!4b1",
                            link_url_provider="google")]),
     "真实 Google 实体链（含合法 @ 片段与 data= 后缀）不得被误伤"),
]


# Corrections recorded at write time (each is a refusal either way; none was flipped to allow):
#   AV-20 empty origin  -> EVIDENCE_INCOMPLETE fires first (a blank required field is the truer
#                          diagnosis than an unclassifiable URL), the refused ref still errors too.
#   AV-21 homepage origin -> EVIDENCE_HOMEPAGE_ONLY is the homepage-specific code.
#   AV-12/24/26        -> IDENTITY_STABLE_REF_INVALID: the row also carries a valid address, so the
#                         combination gate stays satisfied; the refused stable reference is reported
#                         instead of being masked. That masking was itself a W1R-B1 finding.
#   AV-22              -> a `dataset:` origin is a registered-lookup question answered at the lineage
#                         gate (REF_ORIGIN_PENDING_REGISTRATION), not by the URL shape branch.


def codes(errors):
    return [item.split("|", 1)[0] for item in errors]


class AuditVectorTests(unittest.TestCase):
    """§17.7.1 ⑧：消费端 allow/deny 的人工冻结判定。"""

    def test_vector_table_is_hand_pinned(self):
        self.assertGreaterEqual(len(VECTORS), 25, "审计向量不得缩水到象征性数量")
        self.assertEqual(len({item[0] for item in VECTORS}), len(VECTORS), "向量 id 不得重复")
        refs = {item[1] for item in VECTORS}
        for ref in ("①", "②", "③", "④", "⑤", "⑥"):
            self.assertIn(ref, refs, "门禁 %s 必须有对应的消费端向量" % ref)
        denies = [item for item in VECTORS if item[2] == "deny"]
        allows = [item for item in VECTORS if item[2] == "allow"]
        self.assertGreaterEqual(len(denies), 20)
        self.assertGreaterEqual(len(allows), 4,
                                "只测拒绝会掩盖“收口变成空拒绝”的回归")

    def test_each_vector_gets_the_pinned_verdict(self):
        problems = []
        for case_id, ref, want, must_codes, row_target, _why in VECTORS:
            if row_target is None:
                continue
            errors = data_model.validate_map_targets({"t-1": row_target}, POLICY)
            got = codes(errors)
            if want == "deny":
                if not errors:
                    problems.append("%s(%s) 应被拒绝却零错误放行" % (case_id, ref))
                    continue
                for code in must_codes:
                    if not any(item == code or item.startswith(code) for item in got):
                        if not any(code in item for item in errors):
                            problems.append("%s(%s) 缺码 %s，实为 %s" % (case_id, ref, code, got))
            else:
                if errors:
                    problems.append("%s(%s) 应放行却被拒：%s" % (case_id, ref, errors[:3]))
        self.assertEqual(problems, [], json.dumps(problems, ensure_ascii=False)[:2000])

    def test_the_proven_headline_bypass_is_now_refused(self):
        """§17.7.1 ⑤ 的原始反例，逐字重建：曾以 errors=0 进入 VERIFIED。"""
        row = dict(source_type="licensed_open_data_entity", source_url_or_ref="garbage",
                   retrieved_at="2026-10-26", supported_fields=["display_name"],
                   lineage_group="lg-ds", content_digest="sha256:1", usage_scope="identity",
                   status="complete", source_entity_ref="wikidata:Q42",
                   address="Oslob, Cebu City, 6000")
        errors = data_model.validate_map_targets(
            {"t-1": target(identity_status="VERIFIED", evidence=[row])}, POLICY)
        self.assertTrue(errors, "反例又被放行了")
        self.assertTrue(any("EVIDENCE_SOURCE_UNCLASSIFIABLE" in item for item in errors), errors[:3])
        self.assertTrue(any("REF_ORIGIN_UNCLASSIFIABLE" in item or
                            "IDENTITY_REF_KIND_NOT_ENTITY" in item for item in errors), errors[:3])
        if REPRODUCTION.is_file():
            recorded = json.loads(REPRODUCTION.read_text(encoding="utf-8"))["end_to_end"]
            self.assertEqual(recorded["audit_case_dataset_garbage_origin"]["errors"], 0,
                             "复现证据记录的是修复前的 0 错误；若它变了说明证据被回改")

    def test_verdict_language_is_visible_to_the_reader(self):
        errors = data_model.validate_map_targets({"t-1": verified(
            evidence=[row(source_type="licensed_open_data_entity", source_url_or_ref="garbage",
                          source_entity_ref="wikidata:Q42")])}, POLICY)
        joined = " ".join(errors)
        self.assertIn("garbage", joined, "拒绝信息必须带上实际值，读者才知道改哪里")
        self.assertIn("source_url_or_ref", joined)


class DeadCodeTests(unittest.TestCase):
    """§17.7.1 ⑦：死常量与陈旧封存值不得留在正式实现与回报里。"""

    def test_superseded_constants_are_gone(self):
        source = (HERE / "data_model.py").read_text(encoding="utf-8")
        identifiers = set(re.findall(r"[A-Za-z_][A-Za-z0-9_]*", source))
        for name in ("SEARCH_URL_RE", "BARE_HOMEPAGE_RE", "_host_root", "_hostname"):
            # identifier boundary matters: "shortlink_hostnames" is a config key, not the helper
            self.assertNotIn(name, identifiers, "%s 已无调用，应随 W1R-B1 ⑦ 删除" % name)

    def test_w1rb_report_no_longer_cites_the_intermediate_seal(self):
        report = (ROOT.parents[1] / ".temp/v421_map_phase1/W1RB_contract/w1rb_report.md")
        if not report.is_file():
            self.skipTest("W1R-B 回报不在盘上")
        text = report.read_text(encoding="utf-8")
        # scope: only the layered-conclusion table (section 7) may state an authoritative seal;
        # section 4 legitimately records the intermediate seals produced by resealing three times
        section = text.split("## 7. ")[1] if "## 7. " in text else text
        self.assertIn("6CDA511A0F4D", section, "第 7 节必须给出最终权威封存值")
        self.assertNotIn("932573AD8A69", section,
                         "中间封存值不得作为第 7 节的权威值（§17.7.1 ⑦）")


class ForkDebtTests(unittest.TestCase):
    """§17.7.1 ⑨：语义调用点清册必须是量出来的，且条目只减不增（W4/W5 的债务台账）。"""

    def _measure(self):
        inventory = POLICY["second_judgment_inventory"]
        patterns = {name: pattern for name, pattern in inventory["semantic_call_sites_measured"]
                    ["patterns"].items()}
        found = {}
        for path in sorted((ROOT / "scripts").glob("*.py")):
            if path.name.startswith("test_"):
                continue
            body = path.read_text(encoding="utf-8", errors="ignore")
            touches = sorted(name for name, pattern in patterns.items()
                             if re.search(pattern, body, re.IGNORECASE))
            if touches:
                found["scripts/" + path.name] = touches
        return inventory, found

    def test_semantic_inventory_matches_a_fresh_measurement_and_never_grows(self):
        inventory, found = self._measure()
        registered = {item["file"]: sorted(item["touches"])
                      for item in inventory["semantic_call_sites"] if item["touches"]}
        self.assertEqual(set(registered), set(found),
                         "调用点清册与实际代码不符：新增=%s 消失=%s（只允许消失，且消失后必须回写合同）"
                         % (sorted(set(found) - set(registered)),
                            sorted(set(registered) - set(found))))
        drift = {name: (registered[name], found[name]) for name in registered
                 if registered[name] != found[name]}
        self.assertEqual(drift, {}, "已登记文件的语义命中面变化，必须重新登记")

    def test_authority_file_is_the_only_registered_classifier_home(self):
        inventory = POLICY["second_judgment_inventory"]
        authorities = [item["file"] for item in inventory["semantic_call_sites"]
                       if item["is_classifier_authority"]]
        self.assertEqual(authorities, [inventory["authority"].split("::", 1)[0]])
        self.assertEqual(disposition_violations(inventory), [],
                         "处置词表的门牙咬到了：%s" % json.dumps(
                             disposition_violations(inventory), ensure_ascii=False))

    def _holder(self, inventory):
        return next(item for item in inventory["semantic_call_sites"]
                    if item["disposition"] == SUBSTRING_DISPOSITION)

    def _other(self, inventory):
        return next(item for item in inventory["semantic_call_sites"]
                    if not item["is_classifier_authority"]
                    and item["disposition"] != SUBSTRING_DISPOSITION)

    def test_pattern_substring_disposition_is_locked_to_one_holder_and_one_shape(self):
        """在盘台账必须同时过四件事：词表两值、持有人一格、形状钉死、说明指到因。"""
        inventory = POLICY["second_judgment_inventory"]
        exception = inventory["disposition_substring_exception"]
        self.assertEqual(inventory["disposition_allowed"],
                         [DEFAULT_DISPOSITION, SUBSTRING_DISPOSITION],
                         "词表不是业主 2026-11-01 锁定的那两值，或顺序变了（默认值必须排第一）")
        self.assertEqual(exception["holders"], ["scripts/pyc_hygiene.py"],
                         "第二个处置值目前有且只能有这一个持有人：多一格就要业主裁决")
        self.assertEqual(sorted(item["file"] for item in inventory["semantic_call_sites"]
                                if item["disposition"] == SUBSTRING_DISPOSITION),
                         sorted(exception["holders"]),
                         "登记面说的持有人与台账里真用它的文件不是同一批")
        holder = self._holder(inventory)
        self.assertEqual(holder["counts"], exception["pinned_shape"],
                         "例外持有人的测量形状变了就要重登记或收回例外：provider_decision 只允许 1，"
                         "其余四类只允许 0")
        self.assertEqual(holder["counts"]["provider_decision"], 1)
        self.assertEqual(sum(value for key, value in holder["counts"].items()
                             if key != "provider_decision"), 0,
                         "例外只许覆盖那一条子串误报：别的面一旦有命中，它就不再是「纯误报」")
        self.assertEqual(sorted(holder["touches"]), ["provider_decision"])
        self.assertIn(exception["review_note_must_contain"], holder["v422_review_note"],
                      "复核说明没指到那条因（cause_literal）：豁免就成了会写字的地方")
        self.assertEqual(disposition_violations(inventory), [])

    def test_retirement_rule_says_delete_the_exception_not_reuse_it(self):
        """例外是子串扫描器的产物；扫描器改成 AST/token 之后它必须整块消失。"""
        rule = POLICY["second_judgment_inventory"]["disposition_substring_exception"]["retirement_rule"]
        self.assertTrue(re.search(r"AST|token", rule),
                        "退役条款没写触发条件（扫描器改成只扫可执行 AST/token）："
                        "没有触发条件的退役条款＝永久例外")
        for phrase in ("删除", "先例"):
            self.assertIn(phrase, rule,
                          "退役条款必须同时写明**动作**（删除整块例外）与**禁止的事**"
                          "（不许把它当先例扩大复用），缺一半就读成「少用点」：%s" % rule)

    def test_second_holder_of_the_substring_disposition_is_rejected(self):
        """负测：把例外整套原样搬到第二个文件身上——只剩「持有人」这一条规则能拦住它。

        其余四条（形状／touches／说明／词表）全给它复制对了，才证明持有人清单不是装饰。
        """
        inventory = copy.deepcopy(POLICY["second_judgment_inventory"])
        holder, other = self._holder(inventory), self._other(inventory)
        for key in ("counts", "touches", "v422_review_note"):
            other[key] = copy.deepcopy(holder[key])
        other["disposition"] = SUBSTRING_DISPOSITION
        violations = disposition_violations(inventory)
        self.assertEqual([item["rule"] for item in violations],
                         ["second_holder_of_the_substring_disposition"],
                         "%s：复制得一模一样就不该有别的违规，只该被持有人清单抓住"
                         % other["file"])
        self.assertEqual(violations[0]["file"], other["file"])

    def test_pinned_shape_drift_of_the_exception_holder_is_rejected(self):
        """负测：持有人的命中面从 1 涨到 2、或从纯误报变成真有 URL 面，都要红。"""
        for mutate, expected in (
                ({"provider_decision": 2}, "exception_shape_not_pinned"),
                ({"host_extraction": 1}, "exception_shape_not_pinned"),
                ({"provider_decision": 0}, "exception_shape_not_pinned")):
            inventory = copy.deepcopy(POLICY["second_judgment_inventory"])
            holder = self._holder(inventory)
            counts = dict(holder["counts"])
            counts.update(mutate)
            holder["counts"] = counts
            holder["touches"] = sorted(key for key, value in counts.items() if value)
            rules = [item["rule"] for item in disposition_violations(inventory)]
            self.assertIn(expected, rules,
                          "%s 之后门牙没咬：%s" % (mutate, json.dumps(rules, ensure_ascii=False)))

    def test_exception_review_note_without_the_cause_literal_is_rejected(self):
        """负测：说明写「已复核」这类空话时，豁免格子就必须被拒——因要在字面里。"""
        for note in ("已复核，不是调用面。", "", "   ", "见 no_cache 那条"):
            inventory = copy.deepcopy(POLICY["second_judgment_inventory"])
            holder = self._holder(inventory)
            holder["v422_review_note"] = note
            rules = [item["rule"] for item in disposition_violations(inventory)]
            self.assertIn("exception_note_missing_cause_literal", rules,
                          "说明改成 %r 后门牙没咬：%s" % (note, json.dumps(rules)))

    def test_disposition_vocabulary_may_not_gain_a_third_value(self):
        """负测：词表是闭集——加第三个值、删第二个值、换顺序，三种都算放宽。"""
        cases = {
            "加一档「已人工复核」": lambda allowed: allowed.append("manually_reviewed_ok"),
            "删掉例外那一档": lambda allowed: allowed.remove(SUBSTRING_DISPOSITION),
            "把非默认值挪到第一位": lambda allowed: allowed.reverse(),
        }
        for label, mutate in sorted(cases.items()):
            inventory = copy.deepcopy(POLICY["second_judgment_inventory"])
            allowed = list(inventory["disposition_allowed"])
            mutate(allowed)
            inventory["disposition_allowed"] = allowed
            rules = [item["rule"] for item in disposition_violations(inventory)]
            self.assertIn("vocabulary_not_the_registered_pair", rules,
                          "%s 之后门牙没咬：%s" % (label, json.dumps(rules, ensure_ascii=False)))

    def test_literal_fork_register_is_machine_readable(self):
        inventory = POLICY["second_judgment_inventory"]
        self.assertEqual(sorted(inventory["literal_forks"]),
                         sorted(["spa-layout.js", "split-layout.js", "app_contract.py",
                                 "domestic_poi_sources.py", "gen_travel_scope.py",
                                 "map_contract.py", "search_source_evidence.py",
                                 "validate_output.py", "visual_qa.py"]),
                         "9 项字面量债务是 W4/W5 的验收面，不得随手删条目")
        for name, stage in inventory["literal_forks"].items():
            self.assertIn(stage, ("W4", "W5"), "%s 必须标注在哪一轮收编" % name)
