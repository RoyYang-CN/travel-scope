# -*- coding: utf-8 -*-
"""v5.0.0 有限发布范围的唯一判据实现（继承 v4.2.2 R3H 范围）。

为什么单独一个模块：范围合同（`references/release-scope.json`）说了什么，只能有一把尺子去核；
测试、交付门与收口件都调这一个实现，否则就像历史上那样——锚点说一套、README 说一套、
文档作者另写一套。「文档措辞与在盘字节是否互相咬得住」这类账，一旦有两个算法就一定会分叉。

判什么（全部读登记面，模块内不藏阈值）：
1. 范围文件在盘、required_fields 齐、闭集值没被写宽（`production_certified` 必须是布尔 false）；
2. 排除项还在：excluded_destinations 含 philippines、excluded_profiles 含 en-formal；
3. 登记的加州实物（读者 HTML 字节＋摘要、run 逐文件聚合、链条面形状）与现场重算逐字相等——
   **登记的面和被登记的面要一起老**；
4. 菲律宾的排除理由今天仍然成立（现场复算）；哪天有人补齐了 PH，这条就会红，逼着人重看范围；
5. VERSION.md／SKILL.md 的必须措辞、绝不许出现的表述、以及「production-certified 只许出现在否定句」；
6. 正式 run 的 outputs 里不许出现审计档／英文产物。
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

TREE = Path(__file__).resolve().parents[1]                 # …/travel-scope-v5.0.0/travel-scope
PKG_ROOT = TREE.parent                                     # …/travel-scope-v5.0.0（release_runs 住这里）
PROJECT_ROOT = TREE.parents[1]                             # …/Travel-Scope（.temp 与清单住这里）
SCOPE_REL = "references/release-scope.json"
FORMAL_RUN = "release_runs/travel_scope_run_202701_usa_california_v422_zh_001"
EXCLUDED_RUN = "release_runs/travel_scope_run_202702_philippines_visayas_v422_zh_001"
AUDIT_MARKERS = ("-en.html", "-en.", "双语", "audit", "review", "research")


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def load_scope(tree: Path | None = None) -> dict:
    path = (tree or TREE) / SCOPE_REL
    if not path.is_file():
        raise ValueError("RELEASE_SCOPE_FILE_MISSING|%s 不在盘上（%s）" % (SCOPE_REL, path))
    return json.loads(path.read_bytes().decode("utf-8"))


def run_aggregate(run_root: Path) -> str:
    table = {p.relative_to(run_root).as_posix(): sha(p) for p in sorted(run_root.rglob("*"))
             if p.is_file()}
    blob = "".join("%s %s\n" % (k, v) for k, v in sorted(table.items())).encode("utf-8")
    return hashlib.sha256(blob).hexdigest().upper()


def chain_face_counts(run_root: Path) -> dict:
    """链条面的唯一计数口径：行数／档位格数／绝对 source／空 source／绝对 relpath。

    登记面（release-scope.json 与 R3F 基线）和这把尺子都读这一个函数——
    第一版我在 .temp 工具里另写了一份计数，结果把「source 与 relpath 合起来的格子数」
    拿去和「只算 source 的登记值」比，量出 36≠18 的假矛盾；同类缺陷不许有第二次。
    """
    path = run_root / "media_prepared" / "media-manifest.json"
    if not path.is_file():
        return {"missing_face": path.name, "rows": 0, "rendition_cells": 0,
                "absolute_source": 0, "empty_source": 0, "absolute_relpath": 0}
    chain = json.loads(path.read_bytes().decode("utf-8"))
    entries = chain.get("entries") or []
    rels = [str(r.get("relpath") or "") for e in entries for r in (e.get("renditions") or [])]
    srcs = [str(e.get("source") or "") for e in entries]
    return {"rows": len(entries), "rendition_cells": len(rels),
            "absolute_source": sum(1 for v in srcs if _is_absolute(v)),
            "empty_source": sum(1 for v in srcs if not v.strip()),
            "absolute_relpath": sum(1 for v in rels if _is_absolute(v))}


def _is_absolute(value) -> bool:
    s = str(value or "")
    return bool(s.strip()) and (":" in s[:3] or s.startswith(("/", "\\")))


def chain_face_offenders(run_root: Path) -> list:
    """点名用的 offender 清单（判「干净不干净」用计数，写账用这个）。"""
    path = run_root / "media_prepared" / "media-manifest.json"
    if not path.is_file():
        return ["链条面缺件:%s" % path.name]
    chain = json.loads(path.read_bytes().decode("utf-8"))
    bad = []
    for entry in chain.get("entries") or []:
        src = str(entry.get("source") or "")
        if not src.strip():
            bad.append("source 为空|%s" % entry.get("local_file"))
        elif _is_absolute(src):
            bad.append("source 绝对|%s" % entry.get("local_file"))
        for rend in entry.get("renditions") or []:
            if _is_absolute(rend.get("relpath")):
                bad.append("relpath 绝对|%s" % entry.get("local_file"))
    return bad


def philippine_facts(pkg_root: Path) -> dict:
    run = pkg_root / EXCLUDED_RUN
    out = {"run_present": run.is_dir()}
    if not run.is_dir():
        return out
    man = json.loads((run / "manifest.json").read_bytes().decode("utf-8"))
    declared = (man.get("artifacts_expected") or [None])[0]
    htmls = sorted(p.name for p in (run / "outputs").glob("*.html")) if (run / "outputs").is_dir() else []
    chain = chain_face_counts(run)
    out.update({"declared_html": declared, "html_on_disk": htmls,
                "declared_html_absent": bool(declared) and declared not in htmls,
                "artifact_generation_claimed": "artifact_generation" in (man.get("completed_stages") or []),
                "snapshot_path": str(man.get("source_verification_snapshot_path")),
                "snapshot_file_present": (run / "evidence" / "media-source-snapshot.json").is_file(),
                "chain_rows": chain["rows"], "absolute_source": chain["absolute_source"],
                "empty_source": chain["empty_source"], "absolute_relpath": chain["absolute_relpath"]})
    return out


def check(scope: dict | None = None, tree: Path | None = None, pkg_root: Path | None = None) -> dict:
    """跑一遍全量核对；返回 findings（每条以码打头）与现场量到的值。

    `tree`＝发布树（范围登记与两份文档在这里）；`pkg_root`＝它的上一层（两棵 run 在那里）。
    两个根分开传，是为了能把整套判据指向一棵副本上跑负测，而不必先骗自己说那是发布树。
    """
    tree = tree or TREE
    pkg_root = pkg_root or PKG_ROOT
    findings, measured = [], {}
    try:
        scope = scope or load_scope(tree)
    except (ValueError, json.JSONDecodeError) as exc:
        return {"status": "FAIL", "findings": ["RELEASE_SCOPE_FILE_MISSING|%s" % exc], "measured": {}}
    for field in scope.get("required_fields") or []:
        if field not in scope:
            findings.append("RELEASE_SCOPE_FIELD_MISSING|%s" % field)
    closed = scope.get("closed_values") or {}
    if scope.get("release_tier") not in (closed.get("release_tier") or ["LIMITED_SCOPE"]):
        findings.append("RELEASE_SCOPE_OVERCLAIM|release_tier=%r 不在闭集 %s"
                        % (scope.get("release_tier"), closed.get("release_tier")))
    if scope.get("production_certified") is not closed.get("production_certified_must_be", False):
        findings.append("RELEASE_SCOPE_OVERCLAIM|production_certified 必须是布尔 %s，实为 %r"
                        % (closed.get("production_certified_must_be", False),
                           scope.get("production_certified")))
    if scope.get("validated_profile") not in (closed.get("validated_profile") or ["zh-formal"]):
        findings.append("RELEASE_SCOPE_OVERCLAIM|validated_profile=%r" % scope.get("validated_profile"))
    if str(scope.get("product_version")) not in (closed.get("product_version") or ["5.0.0"]):
        findings.append("RELEASE_SCOPE_OVERCLAIM|product_version=%r" % scope.get("product_version"))
    excl = scope.get("scope") or {}
    if "philippines" not in (excl.get("excluded_destinations") or []):
        findings.append("RELEASE_SCOPE_EXCLUSION_MISSING|excluded_destinations 少 philippines")
    if "en-formal" not in (excl.get("excluded_profiles") or []):
        findings.append("RELEASE_SCOPE_EXCLUSION_MISSING|excluded_profiles 少 en-formal")

    ca = scope.get("california_formal_run") or {}
    run_root = pkg_root / FORMAL_RUN
    if not run_root.is_dir():
        findings.append("RELEASE_SCOPE_RUN_DIGEST_STALE|正式 run 目录不在盘上")
    else:
        live_agg = run_aggregate(run_root)
        measured["run_aggregate_sha256"] = live_agg
        if str(ca.get("aggregate_sha256") or "").upper() != live_agg:
            findings.append("RELEASE_SCOPE_RUN_DIGEST_STALE|登记 %s… ≠ 现场 %s…（run 被动过或登记没跟上）"
                            % (str(ca.get("aggregate_sha256"))[:12], live_agg[:12]))
        html = ca.get("reader_html") or {}
        html_path = run_root / str(html.get("path") or "")
        if not html_path.is_file():
            findings.append("RELEASE_SCOPE_DIGEST_STALE|登记的读者件不在盘上：%s" % html.get("path"))
        else:
            live_bytes, live_sha = html_path.stat().st_size, sha(html_path)
            measured["reader_html"] = {"bytes": live_bytes, "sha256": live_sha}
            if int(html.get("bytes") or -1) != live_bytes:
                findings.append("RELEASE_SCOPE_DIGEST_STALE|字节 登记 %s ≠ 现场 %s"
                                % (html.get("bytes"), live_bytes))
            if str(html.get("sha256") or "").upper() != live_sha:
                findings.append("RELEASE_SCOPE_DIGEST_STALE|摘要 登记 %s… ≠ 现场 %s…"
                                % (str(html.get("sha256"))[:12], live_sha[:12]))
        offenders = chain_face_offenders(run_root)
        measured["california_chain_face_offenders"] = len(offenders)
        if offenders:
            findings.append("RELEASE_SCOPE_FACE_NOT_CLEAN|%s" % offenders[:4])
        outputs = run_root / "outputs"
        audit_hits = [p.name for p in outputs.iterdir()
                      if p.is_file() and any(m in p.name.lower() for m in AUDIT_MARKERS)] \
            if outputs.is_dir() else []
        if audit_hits:
            findings.append("RELEASE_SCOPE_FORMAL_OUTPUT_HAS_AUDIT_ARTIFACT|%s" % audit_hits[:4])

    facts = philippine_facts(pkg_root)
    measured["philippines_facts"] = facts
    registered = (scope.get("philippines_status") or {}).get("exclusion_reason_measured_on_disk") or {}
    still_excludable = (facts.get("declared_html_absent") is True
                        and facts.get("snapshot_file_present") is False
                        and facts.get("absolute_relpath", 0) > 0)
    if not still_excludable:
        findings.append("RELEASE_SCOPE_EXCLUDED_FACT_STALE|菲律宾的排除理由现场不再成立：%s；"
                        "登记值：%s" % (facts, {k: registered.get(k) for k in
                                              ("declared_artifact_absent_from_outputs",
                                               "snapshot_file_present",
                                               "media_chain_absolute_source")}))
    else:
        # 口径对齐：登记的三个数必须与现场同一把尺子量出的三个数逐字相等。
        for reg_key, live_key in (("media_chain_rows", "chain_rows"),
                                  ("media_chain_absolute_source", "absolute_source"),
                                  ("media_chain_absolute_relpath", "absolute_relpath")):
            if int(registered.get(reg_key) or -1) != int(facts.get(live_key) or -2):
                findings.append("RELEASE_SCOPE_EXCLUDED_FACT_STALE|登记的 PH %s=%s 与现场 %s 不等"
                                % (reg_key, registered.get(reg_key), facts.get(live_key)))

    docs = scope.get("documentation_requirements") or {}
    for name, spec in sorted(docs.items()):
        path = tree / name
        if not path.is_file():
            findings.append("RELEASE_SCOPE_DOC_PHRASE_MISSING|%s 不在盘上" % name)
            continue
        text = path.read_bytes().decode("utf-8").replace("\r\n", "\n")
        for needle in spec.get("must_contain") or []:
            if needle not in text:
                findings.append("RELEASE_SCOPE_DOC_PHRASE_MISSING|%s 缺必须措辞：%s" % (name, needle[:70]))
        for needle in spec.get("must_not_contain") or []:
            if needle in text:
                findings.append("RELEASE_SCOPE_DOC_OVERCLAIM|%s 出现禁止表述：%s" % (name, needle))
    for rule in scope.get("phrase_rules") or []:
        for name in sorted(docs):
            path = tree / name
            if not path.is_file():
                continue
            for n, line in enumerate(path.read_bytes().decode("utf-8").replace("\r\n", "\n")
                                      .split("\n"), 1):
                if rule["phrase"].lower() in line.lower() and not any(
                        t.lower() in line.lower() for t in rule.get("allowable_only_with") or []):
                    findings.append("RELEASE_SCOPE_NEGATED_CLAIM_VIOLATED|%s:%d %r 出现在非否定句：%s"
                                    % (name, n, rule["phrase"], line[:90]))
    return {"status": "PASS" if not findings else "FAIL", "findings": findings,
            "measured": measured,
            "codes_seen": sorted({f.split("|", 1)[0] for f in findings}),
            "declared_label": scope.get("declared_label")}


def main() -> int:
    report = check()
    print(json.dumps(report, ensure_ascii=False, indent=1))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
