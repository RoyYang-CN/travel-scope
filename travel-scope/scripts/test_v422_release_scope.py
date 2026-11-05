# -*- coding: utf-8 -*-
"""v5.0.0 继承的有限发布范围执行型牙齿（原 v4.2.2 R3H 合同）。

判据只有一把：`scripts/release_scope.check()`。这里不另算一遍，只做两件事——
① 现场必须绿（在盘的范围登记、两份文档、两棵 run 的真实形状互相咬得住）；
② 每一种坏法都必须被**它自己点名的那条码**拦下（被别的码拦下＝不算证），
   且负测全部在临时副本上做：发布树、正式 run、菲律宾 run 一个字节都不许被测试改动。

为什么负测要造一棵假树而不是改真树：范围判据要读 run 聚合与读者件摘要，
改真树来做负测会先把「登记值与实物相等」这件事弄脏，下一轮就分不清是缺陷还是测试残留。
"""
from __future__ import annotations

import hashlib
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
TREE = SCRIPTS.parent
sys.path.insert(0, str(SCRIPTS))
import release_scope as rs          # noqa: E402

CA_NAME = "travel_scope_run_202701_usa_california_v422_zh_001"
PH_NAME = "travel_scope_run_202702_philippines_visayas_v422_zh_001"
HTML_NAME = "usa-california-travel-guide.html"
PH_HTML_NAME = "philippines-visayas-guide-travel-guide.html"
LIVE_SCOPE = json.loads((TREE / rs.SCOPE_REL).read_bytes().decode("utf-8"))
CODES = set(LIVE_SCOPE["blocking_codes"])
PH_ROWS = 3


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def _write(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes((json.dumps(obj, ensure_ascii=False, indent=1) + "\n").encode("utf-8"))


def build_world(root: Path) -> dict:
    """造一棵「范围合同说得通」的最小世界：两棵 run ＋ references/release-scope.json ＋ 两份文档。

    正对照（clean world 必须 PASS）是这套负测的地板：
    没有它，「每种坏法都报一条码」可能只是「怎么都报错」。
    """
    pkg = root / "pkg"
    ca = pkg / "release_runs" / CA_NAME
    ph = pkg / "release_runs" / PH_NAME
    tree = root / "tree"
    (tree / "references").mkdir(parents=True, exist_ok=True)
    ca_html = ca / "outputs" / HTML_NAME
    ca_html.parent.mkdir(parents=True, exist_ok=True)
    ca_html.write_bytes(b"<html>ca zh formal</html>")
    _write(ca / "dataset.json", {"country": "美国"})
    _write(ca / "media_prepared" / "media-manifest.json",
           {"entries": [{"local_file": "assets/editorial/x%d.jpg" % i,
                         "source": "media_prepared/originals/x%d.jpg" % i,
                         "renditions": [{"label": "w700",
                                         "relpath": "assets/renditions/x%d--w700.jpg" % i}]}
                        for i in range(4)]})
    _write(ph / "manifest.json", {"artifacts_expected": [PH_HTML_NAME],
                                  "completed_stages": ["source_audit", "artifact_generation"],
                                  "source_verification_snapshot_path": None})
    _write(ph / "media_prepared" / "media-manifest.json",
           {"entries": [{"local_file": "assets/editorial/p%d.jpg" % i,
                         "source": "D:/elsewhere/candidate_runs/p%d.jpg" % i,
                         "renditions": [{"label": "w700",
                                         "relpath": "D:/elsewhere/.temp/staging/p%d--w700.jpg" % i}]}
                        for i in range(PH_ROWS)]})
    (ph / "evidence").mkdir(parents=True, exist_ok=True)
    ph_counts = rs.chain_face_counts(ph)
    scope = json.loads(json.dumps(LIVE_SCOPE))
    scope["california_formal_run"] = {"aggregate_sha256": rs.run_aggregate(ca),
                                      "reader_html": {"path": "outputs/" + HTML_NAME,
                                                      "bytes": ca_html.stat().st_size,
                                                      "sha256": sha(ca_html)},
                                      "chain_face": rs.chain_face_counts(ca)}
    scope["philippines_status"]["exclusion_reason_measured_on_disk"] = {
        "declared_artifact_absent_from_outputs": True, "snapshot_file_present": False,
        "media_chain_rows": ph_counts["rows"],
        "media_chain_absolute_source": ph_counts["absolute_source"],
        "media_chain_absolute_relpath": ph_counts["absolute_relpath"]}
    _write(tree / rs.SCOPE_REL, scope)
    for name in ("VERSION.md", "SKILL.md"):
        lines = []
        for needle in LIVE_SCOPE["documentation_requirements"][name]["must_contain"]:
            lines.append(needle)
        lines.append("本版不声明整体 production-certified（production_certified=false）")
        (tree / name).write_bytes(("\n".join(lines) + "\n").encode("utf-8"))
    return {"pkg": pkg, "tree": tree, "ca": ca, "ph": ph, "scope": scope}


class LiveScopeTests(unittest.TestCase):
    """在盘这一份必须绿：范围登记、两份文档、两棵 run 的真实形状互相咬得住。"""

    def codes(self, findings):
        return sorted({f.split("|", 1)[0] for f in findings})

    def test_live_release_scope_check_is_clean(self):
        report = rs.check()
        self.assertEqual(report["findings"], [], report["findings"][:6])
        self.assertEqual(report["status"], "PASS")

    def test_registered_california_artifacts_equal_disk(self):
        report = rs.check()
        measured = report["measured"]
        registered = LIVE_SCOPE["california_formal_run"]
        self.assertEqual(measured["reader_html"]["sha256"], registered["reader_html"]["sha256"])
        self.assertEqual(measured["reader_html"]["bytes"], registered["reader_html"]["bytes"])
        self.assertEqual(measured["run_aggregate_sha256"], registered["aggregate_sha256"])
        self.assertEqual(measured["california_chain_face_offenders"], 0)

    def test_ph_exclusion_reason_still_measurable_on_disk(self):
        facts = rs.check()["measured"]["philippines_facts"]
        self.assertTrue(facts["declared_html_absent"], "PH 声明件现在在盘上？那范围登记要重看")
        self.assertFalse(facts["snapshot_file_present"])
        self.assertGreater(facts["absolute_relpath"], 0)

    def test_scope_file_is_the_only_place_the_numbers_live(self):
        """登记面必须自带闭集码表，且每条都有含义说明——否则下一条实现可以随便造码。"""
        self.assertEqual(len(CODES), len(LIVE_SCOPE["blocking_codes"]))
        self.assertTrue(CODES <= set(LIVE_SCOPE["code_meanings"]),
                        sorted(CODES - set(LIVE_SCOPE["code_meanings"])))
        for field in LIVE_SCOPE["required_fields"]:
            self.assertIn(field, LIVE_SCOPE, "required_fields 点名了却没登记的格子：%s" % field)


class FakeWorldNegativeTests(unittest.TestCase):
    """每一种坏法都必须被它自己点名的码拦下；全部在临时副本上做。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="release_scope_test_")
        self.addCleanup(self._tmp.cleanup)
        self.world = build_world(Path(self._tmp.name))
        self.tree, self.pkg = self.world["tree"], self.world["pkg"]

    def run_check(self, scope=None):
        return rs.check(scope=scope, tree=self.tree, pkg_root=self.pkg)

    def codes(self, findings):
        return sorted({f.split("|", 1)[0] for f in findings})

    def scope_copy(self):
        return json.loads(json.dumps(self.world["scope"]))

    def test_clean_fake_world_passes(self):
        report = self.run_check()
        self.assertEqual(report["findings"], [], "正对照就不过，后面的负测全是空的：%s" % report["findings"][:5])

    def test_missing_scope_file_is_named(self):
        (self.tree / rs.SCOPE_REL).unlink()
        report = rs.check(tree=self.tree, pkg_root=self.pkg)
        self.assertEqual(self.codes(report["findings"]), ["RELEASE_SCOPE_FILE_MISSING"])

    def resync(self, world, scope):
        """改完树之后把 run 聚合登记值跟上。

        聚合是把每个文件的摘要钉在一起，所以任何一次改动都会连带报 RUN_DIGEST_STALE——
        那是这条判据**应该**做的，不是噪声。要单独证一条码就得先补上它，
        否则「只报这一条码」的断言永远测不到目标码本身。
        """
        ca = world["ca"]
        scope["california_formal_run"]["aggregate_sha256"] = rs.run_aggregate(ca)
        html = ca / ("outputs/" + HTML_NAME)
        if html.is_file():
            scope["california_formal_run"]["reader_html"].update(
                {"bytes": html.stat().st_size, "sha256": sha(html)})
        return scope

    def test_field_missing_is_named_per_field(self):
        """每个 required_field 被删都要点自己的名；无连带依赖的那几格还要求「仅此一条码」。"""
        for field in LIVE_SCOPE["required_fields"]:
            bad = self.scope_copy()
            bad.pop(field, None)
            report = self.run_check(scope=bad)
            self.assertIn("RELEASE_SCOPE_FIELD_MISSING", self.codes(report["findings"]),
                          "删了 %s 却没报 FIELD_MISSING：%s" % (field, report["findings"][:4]))
            self.assertTrue(any(f.split("|", 1)[-1] == field for f in report["findings"]),
                            "finding 没点名是哪一格：%s" % report["findings"][:4])
        for field in ("phrase_rules", "packaging", "declared_label"):
            bad = self.scope_copy()
            bad.pop(field, None)
            report = self.run_check(scope=bad)
            self.assertEqual(self.codes(report["findings"]), ["RELEASE_SCOPE_FIELD_MISSING"],
                             "%s 没有连带者，应当只报一条：%s" % (field, report["findings"][:4]))

    def test_certification_overclaim_is_blocked(self):
        for key, value, expect in (
                ("production_certified", True, "release_tier"),
                ("release_tier", "PRODUCTION", "release_tier"),
                ("validated_profile", "en-formal", "validated_profile"),
                ("product_version", "5.0.1", "product_version")):
            bad = self.scope_copy()
            bad[key] = value
            report = self.run_check(scope=bad)
            self.assertEqual(self.codes(report["findings"]), ["RELEASE_SCOPE_OVERCLAIM"],
                             "%s=%r 应只被 OVERCLAIM 拦下：%s" % (key, value, report["findings"][:4]))
            self.assertIn(expect.split("_")[0], report["findings"][0].lower())

    def test_exclusions_cannot_be_quietly_dropped(self):
        for mutator in (
                lambda s: s["scope"].__setitem__("excluded_destinations", []),
                lambda s: s["scope"].__setitem__("excluded_profiles", ["en-audit"])):
            bad = self.scope_copy()
            mutator(bad)
            report = self.run_check(scope=bad)
            self.assertEqual(self.codes(report["findings"]), ["RELEASE_SCOPE_EXCLUSION_MISSING"],
                             report["findings"][:4])

    def test_registered_digest_staleness_is_its_own_code(self):
        bad = self.scope_copy()
        bad["california_formal_run"]["reader_html"]["sha256"] = "0" * 64
        report = self.run_check(scope=bad)
        self.assertEqual(self.codes(report["findings"]), ["RELEASE_SCOPE_DIGEST_STALE"],
                         "摘要不等只该报 DIGEST_STALE：%s" % report["findings"][:4])
        bad2 = self.scope_copy()
        bad2["california_formal_run"]["aggregate_sha256"] = "F" * 64
        report2 = self.run_check(scope=bad2)
        self.assertEqual(self.codes(report2["findings"]), ["RELEASE_SCOPE_RUN_DIGEST_STALE"],
                         "run 聚合不等只该报 RUN_DIGEST_STALE：%s" % report2["findings"][:4])

    def test_chain_face_regression_is_named(self):
        face = self.world["ca"] / "media_prepared" / "media-manifest.json"
        doc = json.loads(face.read_bytes().decode("utf-8"))
        doc["entries"][0]["source"] = "D:/elsewhere/candidate_runs/x0.jpg"
        _write(face, doc)
        report = self.run_check(scope=self.resync(self.world, self.scope_copy()))
        self.assertIn("RELEASE_SCOPE_FACE_NOT_CLEAN", self.codes(report["findings"]),
                      "回退成绝对路径必须被点名：%s" % report["findings"][:4])
        self.assertIn("x0.jpg", report["findings"][0], "finding 要指到那一行：%s" % report["findings"][0])

    def test_audit_artifact_in_formal_output_is_named(self):
        (self.world["ca"] / "outputs" / "guide-en.html").write_bytes(b"<x/>")
        report = self.run_check(scope=self.resync(self.world, self.scope_copy()))
        self.assertEqual(self.codes(report["findings"]),
                         ["RELEASE_SCOPE_FORMAL_OUTPUT_HAS_AUDIT_ARTIFACT"],
                         "审计档进正式目录应只被这一条码拦下：%s" % report["findings"][:4])

    def test_ph_exclusion_reason_going_stale_is_named(self):
        ph = self.world["ph"]
        (ph / "outputs").mkdir(parents=True, exist_ok=True)
        (ph / "outputs" / PH_HTML_NAME).write_bytes(b"<html/>")
        _write(ph / "evidence" / "media-source-snapshot.json", {"records": []})
        report = self.run_check()
        self.assertEqual(self.codes(report["findings"]), ["RELEASE_SCOPE_EXCLUDED_FACT_STALE"],
                         "PH 一旦补齐，排除理由就要红：%s" % report["findings"][:4])

    def test_ph_number_drift_is_also_staleness(self):
        face = self.world["ph"] / "media_prepared" / "media-manifest.json"
        doc = json.loads(face.read_bytes().decode("utf-8"))
        doc["entries"].pop()
        _write(face, doc)
        report = self.run_check()
        self.assertEqual(self.codes(report["findings"]), ["RELEASE_SCOPE_EXCLUDED_FACT_STALE"])
        self.assertIn("media_chain_rows", report["findings"][0], "要说出是哪个数不等：%s"
                      % report["findings"][0])

    def test_doc_phrase_missing_and_overclaim_are_separate_codes(self):
        doc = self.tree / "VERSION.md"
        text = doc.read_bytes().decode("utf-8")
        first = LIVE_SCOPE["documentation_requirements"]["VERSION.md"]["must_contain"][1]
        doc.write_bytes(text.replace(first, "（这里故意没有那句话）").encode("utf-8"))
        self.assertEqual(self.codes(self.run_check()["findings"]), ["RELEASE_SCOPE_DOC_PHRASE_MISSING"])
        doc.write_bytes((text + "\n完整双语正式版\n").encode("utf-8"))
        self.assertEqual(self.codes(self.run_check()["findings"]), ["RELEASE_SCOPE_DOC_OVERCLAIM"])

    def test_affirmative_certification_claim_is_named(self):
        """把 production-certified 写进一句肯定的话里——这正是 DOC-TRUTH 那类事故的形状。"""
        doc = self.tree / "SKILL.md"
        doc.write_bytes((doc.read_bytes().decode("utf-8")
                         + "\nThis release is production-certified.\n").encode("utf-8"))
        report = self.run_check()
        self.assertEqual(self.codes(report["findings"]), ["RELEASE_SCOPE_NEGATED_CLAIM_VIOLATED"],
                         report["findings"][:4])
        self.assertIn("SKILL.md", report["findings"][0])

    def test_negation_line_is_allowed_and_proved_not_blind(self):
        """同一份文档里加一句**否定用法**的同词，必须照样绿——否则尺子只是「见词就杀」。"""
        doc = self.tree / "SKILL.md"
        doc.write_bytes((doc.read_bytes().decode("utf-8")
                         + "\n本文件不声明 production-certified（false）。\n").encode("utf-8"))
        report = self.run_check()
        self.assertEqual(report["findings"], [], "否定句被误杀：%s" % report["findings"][:4])

    def test_every_registered_code_is_reachable_in_a_fresh_world(self):
        """闭集可达性：登记的 12 条码，每一条都要在一棵**干净新造**的世界上被真触发一次。

        上面每条测试各证一码，但都是「我预期它报这条」；这里换成表驱动再走一遍，
        任何一条码触发不了（改名、分支被删、条件写反）都会在这里红，而不是留下一条死码。
        """
        cases = [
            ("RELEASE_SCOPE_FILE_MISSING", lambda w, s: (w["tree"] / rs.SCOPE_REL).unlink()),
            ("RELEASE_SCOPE_FIELD_MISSING", lambda w, s: s.pop("phrase_rules", None)),
            ("RELEASE_SCOPE_OVERCLAIM", lambda w, s: s.__setitem__("production_certified", True)),
            ("RELEASE_SCOPE_EXCLUSION_MISSING",
             lambda w, s: s["scope"].__setitem__("excluded_destinations", [])),
            ("RELEASE_SCOPE_DIGEST_STALE",
             lambda w, s: s["california_formal_run"]["reader_html"].__setitem__("sha256", "0" * 64)),
            ("RELEASE_SCOPE_RUN_DIGEST_STALE",
             lambda w, s: s["california_formal_run"].__setitem__("aggregate_sha256", "F" * 64)),
            ("RELEASE_SCOPE_FACE_NOT_CLEAN", lambda w, s: self._absolutise(w["ca"])),
            ("RELEASE_SCOPE_EXCLUDED_FACT_STALE", lambda w, s: self._heal_ph(w)),
            ("RELEASE_SCOPE_DOC_PHRASE_MISSING",
             lambda w, s: self._cut_phrase(w["tree"] / "VERSION.md", s)),
            ("RELEASE_SCOPE_DOC_OVERCLAIM",
             lambda w, s: self._append(w["tree"] / "SKILL.md", "完整双语正式版")),
            ("RELEASE_SCOPE_NEGATED_CLAIM_VIOLATED",
             lambda w, s: self._append(w["tree"] / "SKILL.md", "This build is production-certified.")),
            ("RELEASE_SCOPE_FORMAL_OUTPUT_HAS_AUDIT_ARTIFACT",
             lambda w, s: (w["ca"] / "outputs" / "guide-en.html").write_bytes(b"<x/>")),
        ]
        registered = set(LIVE_SCOPE["blocking_codes"])
        self.assertEqual({name for name, _ in cases}, registered,
                         "触发表与登记码表不等：缺 %s／多 %s"
                         % (sorted(registered - {n for n, _ in cases}),
                            sorted({n for n, _ in cases} - registered)))
        triggered = []
        for name, mutate in cases:
            tmp = tempfile.TemporaryDirectory(prefix="scope_case_")
            self.addCleanup(tmp.cleanup)
            world = build_world(Path(tmp.name))
            scope = json.loads(json.dumps(world["scope"]))
            mutate(world, scope)
            # FILE_MISSING 只能由「让它自己去读」触发：把 scope 递进去就等于替它把文件补上了。
            report = rs.check(scope=(None if name == "RELEASE_SCOPE_FILE_MISSING" else scope),
                              tree=world["tree"], pkg_root=world["pkg"])
            codes = sorted({f.split("|", 1)[0] for f in report["findings"]})
            self.assertIn(name, codes, "%s 触发不出自己：%s" % (name, report["findings"][:4]))
            triggered.append(name)
        self.assertEqual(sorted(triggered), sorted(registered), "有码没被走到")

    def _absolutise(self, ca: Path):
        face = ca / "media_prepared" / "media-manifest.json"
        doc = json.loads(face.read_bytes().decode("utf-8"))
        doc["entries"][0]["source"] = "D:/elsewhere/candidate_runs/x0.jpg"
        _write(face, doc)

    def _heal_ph(self, world):
        ph = world["ph"]
        (ph / "outputs").mkdir(parents=True, exist_ok=True)
        (ph / "outputs" / PH_HTML_NAME).write_bytes(b"<html/>")
        _write(ph / "evidence" / "media-source-snapshot.json", {"records": []})

    def _cut_phrase(self, doc: Path, scope):
        text = doc.read_bytes().decode("utf-8")
        needle = scope["documentation_requirements"]["VERSION.md"]["must_contain"][1]
        doc.write_bytes(text.replace(needle, "（那句话被删掉了）").encode("utf-8"))

    def _append(self, doc: Path, line: str):
        doc.write_bytes((doc.read_bytes().decode("utf-8") + "\n" + line + "\n").encode("utf-8"))


class ReleaseScopeReaderTests(unittest.TestCase):
    """读侧接口不能被改名：交付门与收口件都按这一组名字调它。"""

    def test_public_helpers_exist(self):
        for name in ("load_scope", "check", "run_aggregate", "chain_face_counts",
                     "chain_face_offenders", "philippine_facts", "sha"):
            self.assertTrue(callable(getattr(rs, name)), name)

    def test_scope_loader_reports_missing_file_instead_of_traceback(self):
        empty = Path(tempfile.mkdtemp(prefix="scope_missing_"))
        self.addCleanup(shutil.rmtree, empty, True)
        with self.assertRaises(ValueError) as caught:
            rs.load_scope(empty / "references")
        self.assertIn("RELEASE_SCOPE_FILE_MISSING", str(caught.exception))


if __name__ == "__main__":
    unittest.main(verbosity=2)
