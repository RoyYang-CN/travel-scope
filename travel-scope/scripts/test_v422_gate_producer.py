# -*- coding: utf-8 -*-
"""v4.2.2 V5-A — 门禁报告的产出者身份（V0-L17 / V0-L08）。

V0 登记的缺口是一句很硬的话：冻结 run 里存的 formal_data_gate／delivery-gate 报告写 PASS，
同一输入用现行代码复算却是 FAIL（CA 356／PH 201 条）。当时谁都说不清那句 PASS 是谁说的——
报告里没有代码版本、没有封条、没有输入指纹，所以「PASS」可以来自任何一版代码、任何一份输入。

本文件测的就一件事：**没有出处的 PASS 不再算数**。分三层：
1. 合成发布树：盖章/复算的每条分支都能被逼出来（含 CRLF、换封条、手改戳）。
2. 真实发布树：跑一次真的地图门禁，报告必须自带身份且能复算成 TRUSTED。
3. 历史只读 run：那几份当年写 PASS 的报告，现在必须判 UNTRUSTED——这是缺口被堵住的直接证据。

第 2、3 层用真实路径；不跳测、不宽限。缺文件就是 FAIL（本项目反复吃过「检查没跑到」的亏）。
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import shutil
import subprocess

import pyc_hygiene as pyc
import sys
import tempfile
import unittest
from pathlib import Path

import gate_producer as gp

ROOT = Path(__file__).resolve().parent.parent
V2R = Path(r"D:/文档/项目开发/Travel-Scope/.temp/v422_honest_map/V2r_migration")
FROZEN_RUNS = Path(r"D:/文档/项目开发/Travel-Scope/runs")
GATE_MODULES = ("formal_data_gate.py", "delivery_gate.py", "visual_qa.py",
                "local_media_gate.py", "map_gate_v422.py")


def sha(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest().upper()


class SyntheticTree:
    """一棵最小发布树：product-origin.json + 两个脚本 + 一个配置，够用且可控。"""

    def __init__(self):
        self.folder = tempfile.mkdtemp(prefix="v5a_tree_")
        self.root = Path(self.folder)
        (self.root / "scripts").mkdir()
        (self.root / "references").mkdir()
        self.blobs = {
            "scripts/gate_x.py": b"# gate x\nprint('x')\n",
            "scripts/gate_producer.py": (ROOT / "scripts" / "gate_producer.py").read_bytes(),
            "scripts/verify_product.py": (ROOT / "scripts" / "verify_product.py").read_bytes(),
            "references/conf.json": b'{"a": 1}\n',
        }
        self.write_blobs()
        self.input_path = self.root / "dataset.json"
        self.input_path.write_bytes(b'{"x": 1}\n')

    def write_blobs(self):
        for rel, blob in self.tree_bytes().items():
            path = self.root / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(blob)

    def tree_bytes(self):
        return self.blobs

    def seal(self):
        manifest = {"product": "Travel-Scope", "version": "4.2.2", "renderer_id": "r-1",
                    "inventory": sorted(self.blobs),
                    "sha256": {rel: hashlib.sha256(blob).hexdigest().upper()
                               for rel, blob in self.blobs.items()}}
        (self.root / "product-origin.json").write_bytes(
            (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
        return manifest

    def open(self):
        self.seal()
        return self

    def code(self):
        return ["scripts/gate_x.py", "scripts/gate_producer.py"]

    def write_report(self, name="report.json", **over):
        kwargs = {"gate_role": "gate_x", "producing_code": self.code(),
                  "producing_config": ["references/conf.json"],
                  "inputs": {"dataset": str(self.input_path)}, "root": self.root}
        kwargs.update(over)
        return gp.write_stamped_report(self.root / name, {"status": "PASS"}, **kwargs)["report"]

    def close(self):
        shutil.rmtree(self.folder, ignore_errors=True)


class StampRefusalTests(unittest.TestCase):
    """盖章阶段就该拒绝的形状：未封存、不存在、在树外——一个都不许悄悄通过。"""

    def setUp(self):
        self.tree = SyntheticTree().open()

    def tearDown(self):
        self.tree.close()

    def test_unsealed_producer_is_refused(self):
        (self.tree.root / "scripts" / "loose.py").write_bytes(b"# never sealed\n")
        with self.assertRaises(ValueError) as ctx:
            gp.stamp("gate_x", ["scripts/loose.py"], root=self.tree.root)
        self.assertIn("不在封存清册内", str(ctx.exception))

    def test_missing_producer_is_refused(self):
        with self.assertRaises(ValueError) as ctx:
            gp.stamp("gate_x", ["scripts/ghost.py"], root=self.tree.root)
        self.assertIn("不在发布树内", str(ctx.exception))

    def test_producer_outside_the_tree_is_refused(self):
        outside = Path(self.tree.folder).parent / "definitely_outside_gate.py"
        outside.write_text("# not part of the release\n", encoding="utf-8")
        try:
            with self.assertRaises(ValueError) as ctx:
                gp.stamp("gate_x", [str(outside)], root=self.tree.root)
            self.assertIn("必须位于发布树内", str(ctx.exception))
        finally:
            outside.unlink(missing_ok=True)

    def test_missing_input_is_refused_rather_than_dropped(self):
        with self.assertRaises(ValueError) as ctx:
            gp.stamp("gate_x", self.tree.code(), ["references/conf.json"],
                     inputs={"dataset": str(self.tree.root / "nope.json")}, root=self.tree.root)
        self.assertIn("报告声明的输入不存在", str(ctx.exception))

    def test_optional_input_left_out_is_just_not_registered(self):
        collected = gp.collect_inputs({"data": "x.json", "ledger": "", "html": None})
        self.assertEqual(list(collected), ["data"], "空参数应视为『这次没用这个输入』，不是报错也不是假登记")

    def test_stamp_makes_no_network_attempt(self):
        import zero_call_sentinel as sentinel
        with sentinel.guarded("v5a stamp") as window:
            gp.stamp("gate_x", self.tree.code(), ["references/conf.json"],
                     inputs={"dataset": str(self.tree.input_path)}, root=self.tree.root)
        ledger = sentinel.ledger({"scope": "v5a stamp"})
        self.assertEqual(ledger["counts"].get("network_attempts_total", 0), 0,
                         "盖章只读本地文件；出现网络连接尝试说明身份机制自己开了外联口子")


class VerifyReportTests(unittest.TestCase):
    """复算分支：每一种漂移都必须给出登记在册的 code，且干净报告不得误报。"""

    def setUp(self):
        self.tree = SyntheticTree().open()
        self.report = self.tree.write_report()

    def tearDown(self):
        self.tree.close()

    def codes(self, target=None):
        result = gp.verify_report(target if target is not None else self.tree.root / "report.json",
                                  self.tree.root)
        return result, [item.split("|", 1)[0] for item in result["findings"]]

    def test_clean_report_is_trusted_and_written_with_lf(self):
        result, codes = self.codes()
        self.assertEqual(codes, [], result["findings"])
        self.assertEqual(result["trust"], "TRUSTED")
        blob = (self.tree.root / "report.json").read_bytes()
        self.assertNotIn(b"\r\n", blob, "Windows 上 write_text 会把 LF 写成 CRLF：同一输入两份字节")

    def test_identity_digest_ignores_run_time_chatter(self):
        body = dict(self.report["producer"])
        body["run_at_utc"] = "2000-01-01T00:00:00Z"
        body["argv"] = ["something", "else"]
        self.assertEqual(gp._identity_digest(body), self.report["producer"]["identity_sha256"],
                         "重放比对要看身份，不能被时钟和 argv 绊倒")

    def test_code_changed_after_the_report_is_untrusted(self):
        (self.tree.root / "scripts" / "gate_x.py").write_bytes(b"# tampered after PASS\n")
        result, codes = self.codes()
        self.assertEqual(codes, ["PRODUCER_CODE_DIGEST_DIFFERS"], result["findings"])
        self.assertEqual(result["trust"], "UNTRUSTED")

    def test_hand_edited_stamp_field_fails_its_own_digest(self):
        body = json.loads(json.dumps(self.report))
        body["producer"]["seal_sha256"] = "0" * 64
        tampered = self.tree.root / "hand_edited.json"
        tampered.write_bytes(gp.serialize(body))
        result, codes = self.codes(tampered)
        self.assertIn("PRODUCER_IDENTITY_DIGEST_DIFFERS", codes)

    def test_stripped_stamp_is_the_v0_l17_shape(self):
        body = {k: v for k, v in json.loads(json.dumps(self.report)).items() if k != "producer"}
        bare = self.tree.root / "legacy.json"
        bare.write_bytes(gp.serialize(body))
        result, codes = self.codes(bare)
        self.assertEqual(codes, ["PRODUCER_STAMP_ABSENT"], result["findings"])
        self.assertIn("哪版代码", result["findings"][0])

    def test_reseal_makes_every_older_report_stale(self):
        self.tree.blobs["references/conf.json"] = b'{"a": 2}\n'
        self.tree.write_blobs()
        self.tree.seal()
        result, codes = self.codes()
        self.assertIn("PRODUCER_SEAL_SHA_DIFFERS", codes, "封条重铸后旧报告不得继续当证据")
        self.assertIn("PRODUCER_CODE_NOT_MATCHING_SEAL", codes,
                      "报告声明的字节与封条登记的字节不同＝产报告时工作树已经和封存版不一致")

    def test_changed_input_is_reported_as_a_different_input(self):
        self.tree.input_path.write_bytes(b'{"x": 2}\n')
        result, codes = self.codes()
        self.assertEqual(codes, ["PRODUCER_INPUT_DIGEST_DIFFERS"], result["findings"])

    def test_crlf_report_file_is_called_out(self):
        crlf = self.tree.root / "crlf.json"
        crlf.write_bytes((self.tree.root / "report.json").read_bytes().replace(b"\n", b"\r\n"))
        result, codes = self.codes(crlf)
        self.assertIn("PRODUCER_REPORT_BYTES_DIFFER", codes)

    def test_unregistered_emitted_code_becomes_a_finding(self):
        # 构造一个「检查加了、登记没跟」的形态：清掉戳版本，逼出一条未登记前缀的分支。
        body = json.loads(json.dumps(self.report))
        body["producer"]["stamp_version"] = "gate-producer-stamp-0"
        odd = self.tree.root / "old_stamp.json"
        odd.write_bytes(gp.serialize(body))
        result, codes = self.codes(odd)
        self.assertIn("PRODUCER_STAMP_VERSION_UNSUPPORTED", codes)
        self.assertTrue(set(codes) <= set(gp.VERIFY_CODES),
                        "verify 只能产出登记在册的 code：%s" % sorted(set(codes) - set(gp.VERIFY_CODES)))

    def test_missing_file_and_non_json_are_untrusted(self):
        result, codes = self.codes(self.tree.root / "nowhere.json")
        self.assertEqual(codes, ["PRODUCER_REPORT_FILE_MISSING"])
        junk = self.tree.root / "junk.json"
        junk.write_bytes(b"{not json")
        result, codes = self.codes(junk)
        self.assertEqual(codes, ["PRODUCER_REPORT_NOT_JSON"])

    def test_require_trusted_raises_with_the_findings(self):
        body = {k: v for k, v in self.report.items() if k != "producer"}
        with self.assertRaises(ValueError) as ctx:
            gp.require_trusted(body, self.tree.root, context="delivery_gate")
        self.assertIn("PRODUCER_STAMP_ABSENT", str(ctx.exception))
        self.assertIn("delivery_gate", str(ctx.exception))


class RealReleaseTreeTests(unittest.TestCase):
    """真树：现行发布代码跑一次真门禁，报告必须自带可复算的身份。"""

    def test_every_gate_declares_sealed_producers(self):
        inventory = set(json.loads((ROOT / "product-origin.json").read_text(
            encoding="utf-8"))["inventory"])
        for name in GATE_MODULES:
            module = __import__(name[:-3])
            code = list(getattr(module, "PRODUCING_CODE"))
            config = list(getattr(module, "PRODUCING_CONFIG"))
            self.assertTrue(code and config, "%s 必须同时登记代码与配置产出者" % name)
            for rel in code + config:
                self.assertTrue((ROOT / rel).is_file(), "%s 声明了不存在的产出者：%s" % (name, rel))
                self.assertIn(rel, inventory, "%s 的产出者未入封存清册：%s" % (name, rel))
            self.assertIn("scripts/gate_producer.py", code,
                          "%s 的产出者清单必须包含给它盖章的模块本身" % name)

    def test_real_map_gate_report_is_stamped_and_trusted(self):
        dataset = V2R / "primary" / "philippines_v419" / "dataset_v422_selected.json"
        self.assertTrue(dataset.is_file(), "V2R 真实数据缺失，本测试不许静默跳过：%s" % dataset)
        with tempfile.TemporaryDirectory() as folder:
            out = Path(folder) / "gate.json"
            proc = subprocess.run(
                pyc.interpreter([sys.executable, str(ROOT / "scripts" / "map_gate_v422.py"),
                                 "--dataset", str(dataset), "--out", str(out)]),
                capture_output=True, text=True, encoding="utf-8", errors="replace",
                env=pyc.env())
            self.assertEqual(proc.returncode, 1,
                             "无零调用账本时地图门禁必须 FAIL（§8.1），退出码 %s：%s"
                             % (proc.returncode, proc.stderr[-400:]))
            report = json.loads(out.read_text(encoding="utf-8"))
            producer = report["producer"]
            self.assertEqual(producer["gate_role"], "map_gate_v422")
            self.assertEqual(producer["seal_sha256"], sha(ROOT / "product-origin.json"))
            for rel, digest in producer["producing_code"].items():
                self.assertEqual(digest, sha(ROOT / rel),
                                 "报告说的产码字节与树上现值不符：%s（测试与报告打架）" % rel)
            self.assertEqual(producer["inputs"]["dataset"]["sha256"], sha(dataset))
            result = gp.verify_report(out, ROOT)
            self.assertEqual(result["findings"], [], result["findings"])
            self.assertEqual(result["trust"], "TRUSTED")

    def test_real_reports_are_written_with_lf_not_crlf(self):
        dataset = V2R / "primary" / "philippines_v419" / "dataset_v422_selected.json"
        with tempfile.TemporaryDirectory() as folder:
            out = Path(folder) / "gate.json"
            subprocess.run(pyc.interpreter(
                [sys.executable, str(ROOT / "scripts" / "map_gate_v422.py"),
                 "--dataset", str(dataset), "--out", str(out)]),
                capture_output=True, text=True, encoding="utf-8", errors="replace",
                env=pyc.env())
            self.assertNotIn(b"\r\n", out.read_bytes())

    def test_frozen_historical_pass_reports_are_now_untrusted(self):
        """V0-L17 的直接证据：那几份当年写 PASS 的报告，现在必须判「不可作证据」。"""
        stored = [FROZEN_RUNS / "travel_scope_run_202701_usa_california_v420_001" / "outputs" / "formal_data_gate.json",
                  FROZEN_RUNS / "travel_scope_run_202701_usa_california_v420_001" / "outputs" / "delivery-gate.json",
                  FROZEN_RUNS / "travel_scope_run_202701_usa_california_v420_001" / "evidence" / "visual_qa.json",
                  FROZEN_RUNS / "travel_scope_run_202702_philippines_visayas_v419_001" / "outputs" / "formal_data_gate.json"]
        for path in stored:
            self.assertTrue(path.is_file(), "冻结 run 不见了，无法证明 V0-L17：%s" % path)
            payload = json.loads(path.read_text(encoding="utf-8"))
            result = gp.verify_report(payload, ROOT)
            self.assertEqual(result["trust"], "UNTRUSTED", path)
            codes = [item.split("|", 1)[0] for item in result["findings"]]
            self.assertIn("PRODUCER_STAMP_ABSENT", codes, path)
            self.assertEqual(payload.get("status"), "PASS",
                             "%s 当年写的不是 PASS，用例前提要重看" % path)


class SingleWriterTests(unittest.TestCase):
    """落盘面只有一处：谁再手写 json.dumps 到文件，就是把无主报告放回来的那一步。"""

    def test_gate_modules_write_reports_only_through_gate_producer(self):
        for name in GATE_MODULES:
            body = (ROOT / "scripts" / name).read_text(encoding="utf-8")
            self.assertNotIn("write_text(json.dumps", body,
                             "%s 直接用 write_text 写报告：绕开盖章且会在 Windows 产生 CRLF" % name)
            self.assertIn("gate_producer.write_stamped_report", body,
                          "%s 没有走唯一盖章出口" % name)

    def test_delivery_gate_checks_the_reports_it_consumes(self):
        body = (ROOT / "scripts" / "delivery_gate.py").read_text(encoding="utf-8")
        self.assertIn("gate_producer.verify_report(report_value", body,
                      "delivery_gate 又只看子报告的 status 字段了（V0-L17 的形状）")
        self.assertIn("gate_producer.verify_report(rerun_report", body,
                      "本次重跑的视觉 QA 报告也要有身份，否则等于白跑")


if __name__ == "__main__":
    unittest.main(verbosity=2)
