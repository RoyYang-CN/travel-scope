# -*- coding: utf-8 -*-
"""MT-D2 第 2 步：transport 形状别名的合同、唯一适配器与负测。

业主 2026-11-01 的处置是「建立登记过的 index↔field 映射，不撤销 RENDERED_COLUMNS」，因为两棵载荷
已经把对应关系证出来了（CA 数组 [0]＝place、[3]＝type；PH 对象直接用 place/type）。
四条硬约束都在这里落成执行型断言：
  · 映射由 JSON 配置驱动并带版本（代码里没有第二份下标表）；
  · 只登记已证明的两对，不许顺手补完整个 schema；
  · 禁止按值猜字段（把 [0] 的内容换成一个类别词，判定结果必须一字不变）；
  · 长度不足／arity 不符／字段换位／对象与数组混杂必须阻断，且判定与 worklist 共用同一个适配器。
"""
from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
ROOT = SCRIPTS.parent
sys.path.insert(0, str(SCRIPTS))
import translate_prose as tp                                  # noqa: E402

ALIAS_PATH = ROOT / "references" / "dataset-shape-alias.json"
CA_DATASET = ROOT.parents[1] / ".temp/v422_honest_map/V6_candidate_run/primary_aliased" / \
    "california_v420/dataset_v422_aliased.json"
PH_DATASET = ROOT.parents[1] / ".temp/v422_honest_map/V6_candidate_run/primary_aliased" / \
    "philippines_v419/dataset_v422_aliased.json"

LIST_ROW = ["旧金山", "旧金山国际机场 (SFO)", "SFO", "机场", "37.6,-122.4", "北部核心枢纽"]
DICT_ROW = {"place": "宿务", "name": "宿务麦克坦国际机场", "name_en": "Mactan-Cebu",
            "coords": "10.3,123.9", "type": "机场", "source_status": "已验证"}


def _dataset(rows) -> dict:
    return {"transport_nodes": copy.deepcopy(rows), "hotels": [], "restaurants": [],
            "cafes": [], "attractions": [], "dive_sites": [], "routes": [], "destinations": [],
            "itinerary": [], "budget": [], "practical": [], "worth_it": [], "local_chains": [],
            "packing": [], "transport": [], "destination_coverage": []}


class AliasRegistryTests(unittest.TestCase):
    def test_alias_file_is_the_only_place_the_pairs_are_written(self):
        doc = json.loads(ALIAS_PATH.read_text(encoding="utf-8"))
        self.assertTrue(str(doc.get("alias_table_version") or "").strip(),
                        "别名表必须带版本：没有版本就无法判断这份对应是哪一轮证明的")
        pairs = {(int(a["index"]), str(a["field"]))
                 for a in doc["datasets"]["transport_nodes"]["aliases"]}
        self.assertEqual(pairs, {(0, "place"), (3, "type")},
                         "只登记两棵载荷共同证明的两对；多一对就是「顺手补完 schema」")

    def test_code_reads_the_alias_table_instead_of_holding_its_own_copy(self):
        source = (SCRIPTS / "translate_prose.py").read_text(encoding="utf-8")
        self.assertIn("dataset-shape-alias.json", source, "别名面没被读＝代码里藏了一份")
        self.assertNotIn('(block, 0): "place"', source)
        self.assertNotIn('"transport_nodes", 3', source.split("FORMATTER_SLOTS =")[1]
                         .split("def ")[0],
                         "在别名面之外手写 transport_nodes 的下标＝第二份换算")

    def test_value_guessing_is_forbidden_in_the_adapter_source(self):
        """适配器只能看行长、键名与行形状；出现「读单元格内容」的手段就是按值猜字段。"""
        import inspect
        body = inspect.getsource(tp.shape_adapter) + inspect.getsource(tp.alias_adjudication) \
            + inspect.getsource(tp.alias_field_by_slot)
        for forbidden in ("CNCJK.search", "re.match", "in row[", "row[0] ==", "row[3] =="):
            self.assertNotIn(forbidden, body,
                             "适配器里出现了按值判断的手段 %r：值像机场不是证据" % forbidden)

    def test_adjudication_is_independent_of_cell_values(self):
        """把 [0] 换成一个类别词、[3] 换成一个城市名，判定必须一字不变——这才叫不按值猜。"""
        plain = _dataset([LIST_ROW])
        swapped = _dataset([["机场", "旧金山国际机场 (SFO)", "SFO", "旧金山",
                             "37.6,-122.4", "北部核心枢纽"]])
        self.assertEqual(tp.alias_adjudication("transport_nodes", 0,
                                               tp.non_prose_column_registry()),
                         "DISPLAY_NAME")
        self.assertEqual([row["owners"] for row in
                          tp.classify_fragment_ownership(swapped)["rows"]],
                          [row["owners"] for row in
                           tp.classify_fragment_ownership(plain)["rows"]],
                          "换值就换主人＝按值猜字段，业主明令禁止")


    def test_registered_codes_close_on_both_directions(self):
        """别名表 `block_when` ↔ 合同 `blocking_findings` ↔ 实现发出的码，三面必须同一套。

        单向核对会漏两种坏：登记了但没人发（纸面门），或发了但没登记（下一轮没人知道有这条阻断）。
        MT-D2 第一次跑全量时红的那条就是这个洞——适配器已经发了六个码，登记面只写了伞码。
        """
        doc = json.loads(ALIAS_PATH.read_text(encoding="utf-8"))
        declared = set(doc["datasets"]["transport_nodes"]["block_when"])
        registered = set(tp.contract()["blocking_findings"])
        source = (SCRIPTS / "translate_prose.py").read_text(encoding="utf-8")
        self.assertEqual(declared - registered, set(),
                         "别名表声称会阻断、合同却没登记这些码：%s" % sorted(declared - registered))
        emitted = {code for code in declared if '"%s"' % code in source}
        self.assertEqual(declared - emitted, set(),
                         "登记了码但实现里没有这个字面量（发不出来的码）：%s" % sorted(declared - emitted))
        self.assertIn("dataset_shape_blocked", registered,
                      "伞码必须在册：上游 validate/apply 认的是它，不是六个子码")

    def test_adapter_is_the_only_shape_check_upstream_of_the_writer(self):
        """判定与 worklist 共用**同一个**适配器：分类不许自己再数一遍行长。"""
        import inspect
        body = inspect.getsource(tp.classify_fragment_ownership)
        self.assertIn("shape_adapter(dataset)", body,
                      "分类没走适配器＝两处各写一套形状判断，别名表改了其中一处也不会红")
        for forbidden in ("len(row)", "array_arity"):
            self.assertNotIn(forbidden, body,
                             "分类里自己算形状（%r）就是第二套口径" % forbidden)


class SlotMigrationTests(unittest.TestCase):
    def test_real_inputs_have_clean_shapes(self):
        for path in (CA_DATASET, PH_DATASET):
            if not path.is_file():
                self.skipTest("审计输入不在盘上：%s" % path)
            dataset = json.loads(path.read_text(encoding="utf-8"))
            adapter = tp.shape_adapter(dataset)
            self.assertTrue(adapter["clean"],
                            "%s 的形状核验不过：%s" % (path.name, adapter["blocking"][:2]))

    def test_aliased_slots_migrate_to_the_semantic_channel(self):
        result = tp.classify_fragment_ownership(_dataset([LIST_ROW]))
        by_kind = {row["kind"]: row for row in result["rows"]}
        self.assertEqual(by_kind["node_type"]["owners"], ["CATEGORY_LEXICON"],
                         json.dumps(by_kind["node_type"], ensure_ascii=False)[:300])
        self.assertEqual(by_kind["node_region"]["owners"], ["DISPLAY_NAME"])
        self.assertEqual(result["counts"]["MIXED_OWNER_BLOCKED"], 0)
        self.assertEqual(result["counts"]["PROSE_REQUIRED"],
                         len([row for row in result["rows"]
                              if row["owners"] == ["PROSE_TABLE"]]))

    def test_object_rows_already_registered_need_no_migration(self):
        result = tp.classify_fragment_ownership(_dataset([DICT_ROW]))
        self.assertEqual(result["slot_migrated_rows"], 0,
                         "对象行本来就按字段登记，再换一次形就是重复劳动")

    def test_rendered_columns_keeps_the_column_registered(self):
        """不撤销列登记是业主点名要求的：撤了会把已知结构伪装成「未登记数据」。"""
        self.assertIn(0, tp.RENDERED_COLUMNS["transport_nodes"])
        self.assertIn(3, tp.RENDERED_COLUMNS["transport_nodes"])
        result = tp.classify_fragment_ownership(_dataset([LIST_ROW]))
        for row in result["rows"]:
            if row["kind"] in ("node_region", "node_type"):
                self.assertTrue(row["slot_migration"],
                                "%s 该有一条迁移账：让位必须有记录，不能静默" % row["kind"])


class ShapeBlockingTests(unittest.TestCase):
    def _codes(self, rows):
        adapter = tp.shape_adapter(_dataset(rows))
        return {item["code"] for item in adapter["blocking"]}, adapter

    def test_short_array_row_blocks(self):
        codes, _ = self._codes([["旧金山", "SFO 航站楼"]])
        self.assertIn("array_row_shorter_than_max_alias_index", codes)
        self.assertIn("array_row_arity_mismatch", codes)

    def test_arity_change_alone_blocks_even_when_indexes_exist(self):
        codes, _ = self._codes([LIST_ROW + ["多出来的第七格"]])
        self.assertEqual(codes, {"array_row_arity_mismatch"},
                         "长度从 6 变 7 说明列被插过：位置对应不再成立，但下标本身还在")

    def test_dict_row_missing_aliased_field_blocks(self):
        broken = dict(DICT_ROW)
        broken.pop("type")
        codes, _ = self._codes([broken])
        self.assertEqual(codes, {"dict_row_missing_aliased_field"})

    def test_mixed_row_shapes_block(self):
        codes, _ = self._codes([LIST_ROW, DICT_ROW])
        self.assertEqual(codes, {"mixed_row_shapes_in_one_dataset"},
                         "同一 block 混两种形状：别名只对其中一种成立，混着判会把一列算给两个主人")

    def test_blocked_shape_refuses_to_produce_a_worklist(self):
        """形状坏了不判所有权：宁可整条链停住，也不按错位的主人写盘。"""
        dataset = _dataset([LIST_ROW, DICT_ROW])
        result = tp.classify_fragment_ownership(dataset)
        self.assertIn("dataset_shape_blocked", {item["code"] for item in result["findings"]})
        self.assertTrue(result["accounting"]["identity_holds"],
                        "阻断也要留下完整的四桶账，不然下一轮看不到是谁被卡住")
        table = {"schema_version": "x", "entries": {}}
        report = tp.validate_table(dataset, table)
        self.assertIn("dataset_shape_blocked", {item["code"] for item in report["findings"]},
                      "validate 必须也被形状阻断牵着：判定与写盘分两套口径就是假门")


if __name__ == "__main__":
    unittest.main()
