"""One-command final delivery gate for a Travel-Scope run.
Version: V5.0.0
"""



from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sqlite3
import subprocess
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

try:
    import pyc_hygiene as pyc
    from formal_data_gate import audit as audit_formal_data
    from formal_data_gate import registered_reader_face_key
    from image_assets import inspect_image
    from verify_product import verify as verify_release_product
    from run_seal import verify_seal
    from local_media_gate import (
        validate as validate_local_media,
        validate_section_media,
        validate_source_identities,
        asset_digest_sweep,
        attest_delivered_images,
        resolve_run_path,
    )
except ImportError:  # pragma: no cover
    import scripts.pyc_hygiene as pyc
    from scripts.formal_data_gate import audit as audit_formal_data
    from scripts.formal_data_gate import registered_reader_face_key
    from scripts.image_assets import inspect_image
    from scripts.verify_product import verify as verify_release_product
    from scripts.run_seal import verify_seal
    from scripts.local_media_gate import (
        validate as validate_local_media,
        validate_section_media,
        validate_source_identities,
        asset_digest_sweep,
        attest_delivered_images,
        resolve_run_path,
    )

try:  # v4.2.2 V5-A：报告必须带产出者身份（V0-L17）
    import gate_producer
    from formal_data_gate import PRODUCING_CODE as FORMAL_PRODUCING_CODE
    from formal_data_gate import PRODUCING_CONFIG as FORMAL_PRODUCING_CONFIG
except ImportError:  # pragma: no cover
    import scripts.gate_producer as gate_producer
    from scripts.formal_data_gate import PRODUCING_CODE as FORMAL_PRODUCING_CODE
    from scripts.formal_data_gate import PRODUCING_CONFIG as FORMAL_PRODUCING_CONFIG

try:  # v4.2.2 V5-B：汇率登记检查在读者档也必须可达（V0-L05/V0-L07）
    import budget_contract
except ImportError:  # pragma: no cover
    import scripts.budget_contract as budget_contract

try:  # v4.2.2 V5-C：英文汉字残留的唯一口径（V0-L06）
    import en_residue_measure
except ImportError:  # pragma: no cover
    import scripts.en_residue_measure as en_residue_measure

try:  # v4.2.2 V5-D：单文件自包含字节对账（V0-L11）与登记配置（V0-L12 的图片身份对账在 visual_qa 里跑）
    import self_contained_audit
    import single_file_policy
except ImportError:  # pragma: no cover
    import scripts.self_contained_audit as self_contained_audit
    import scripts.single_file_policy as single_file_policy

try:  # ZH-RELEASE-1（业主 2026-11-02 裁 Q1-A）：语言档位是登记事实，判据只在注册处一份
    import spa_renderer
    import source_projection
    import reader_payload_scope
except ImportError:  # pragma: no cover
    import scripts.spa_renderer as spa_renderer
    import scripts.source_projection as source_projection
    import scripts.reader_payload_scope as reader_payload_scope


# 本报告（delivery-gate.json）的产出者：整条链路上会被读到的代码与配置。
PRODUCING_CODE = ("scripts/delivery_gate.py", "scripts/gate_producer.py",
                  "scripts/local_media_gate.py", "scripts/image_assets.py",
                  "scripts/run_seal.py", "scripts/verify_product.py",
                  "scripts/formal_data_gate.py", "scripts/map_gate_v422.py",
                  "scripts/map_contract.py", "scripts/data_model.py",
                  "scripts/budget_contract.py", "scripts/en_residue_measure.py",
                  "scripts/self_contained_audit.py", "scripts/single_file_policy.py",
                  "scripts/spa_renderer.py", "scripts/source_projection.py",
                  "scripts/reader_payload_scope.py")
PRODUCING_CONFIG = ("references/media-policy.json", "references/version-policy.json",
                    "references/provenance-policy.json", "references/renderer-contract.json",
                    "references/run-quality-policy.json", "references/data-model.json",
                    "references/map-gate-v422.json", "references/map-link-selection.json",
                    "references/budget-policy.json", "references/single-file-delivery-policy.json")


def _first(directory: Path, pattern: str) -> Path | None:
    matches = sorted(directory.glob(pattern))
    return matches[0] if matches else None


def _check_english_text(label: str, text: str, banned_phrases: list[str], disallow_tokens: list[str], max_density: float, max_cjk_ratio: float, errors: list[str]) -> None:
    if not text:
        return
    # V5-C（V0-L06）：汉字残留的数法只有一份实现（scripts/en_residue_measure.py）。
    # 这里原来自己写了 `re.findall([\\u4e00-\\u9fff])` + `cjk_chars > 5` 才报——后者等于
    # 允许 5 个汉字静默通过，前者把语言切换按钮上刻意的「中文」也算成残留。
    measured = en_residue_measure.measure(text)
    decision = en_residue_measure.verdict(measured)
    if max_cjk_ratio != decision["limit"]:
        # 调用方传阈值、登记处也存阈值——两边不一致就是第二套规则。把它变成可见错误，而不是静默取其一。
        errors.append("EN 阈值漂移: 调用方传入 %.6f，登记处是 %.6f（阈值只有 run-quality-policy.json 一个来源）"
                      % (max_cjk_ratio, decision["limit"]))
    if decision["breach"]:
        errors.append(
            "英文产物 %s 中文残留超标: 残留 %d/%d = %.2f%% > %.1f%%（原始汉字 %d，其中刻意项 %d=%s；"
            "定位样本 %s）" % (label, measured["leaked_cjk"], measured["chars"],
                              measured["ratio"] * 100, max_cjk_ratio * 100,
                              measured["raw_cjk"], measured["intentional_cjk"],
                              ",".join(measured["intentional_tokens"]) or "-",
                              " | ".join(measured["leaked_samples"][:3]) or "-"))

    for phrase in banned_phrases:
        pat = re.compile(r"\b" + re.escape(phrase) + r"\b", re.IGNORECASE)
        match = pat.search(text)
        if match:
            errors.append(f"英文产物 {label} 命中违规机器生成/占位符套话: '{match.group()}'")
            break

    if re.search(r"\b\d+\s+days?\s+\d+\s+area\b", text, re.IGNORECASE):
        errors.append(f"英文产物 {label} 命中占位符病句模板 (例如 'X days Y area')")

    words = re.findall(r"\b[A-Za-z]+\b", text.lower())
    if words:
        total_words = len(words)
        for token in disallow_tokens:
            token_lower = token.lower()
            token_count = words.count(token_lower)
            density = token_count / total_words
            if density > max_density and token_count >= 15:
                errors.append(f"英文产物 {label} 中单词 '{token}' 异常高频重复 ({token_count} 次, 占比 {density:.2%} > {max_density:.1%})，存在占位词爆发污染")


SPA_PLACEHOLDER_RE = re.compile(r"\b(?:[A-Z][A-Za-z .&'-]{0,40} )?Venue\b")
READER_PROFILE_META_RE_TMPL = r'<meta\s+name="%s"\s+content="([^"]*)"'
DATASET_PAYLOAD_RE = re.compile(r'<script id="dataset" type="application/json">(.*?)</script>',
                                re.DOTALL)


def _spa_html_files(output: Path) -> list[Path]:
    return sorted(output.glob("*-travel-guide.html")) + sorted(output.glob("*重构版.html"))


def _reader_profile_from_bytes(path: Path) -> dict:
    """档位从交付字节里读，不看构建参数：谁写的 meta 才算数（合同 profiles_declare_self）。"""
    text = path.read_text(encoding="utf-8", errors="replace")
    meta_name = str(spa_renderer.reader_language_contract().get("html_meta_name") or "")
    declared = ""
    if meta_name:
        match = re.search(READER_PROFILE_META_RE_TMPL % re.escape(meta_name), text)
        declared = match.group(1) if match else ""
    payload: dict = {}
    hit = DATASET_PAYLOAD_RE.search(text)
    if hit:
        try:
            payload = json.loads(hit.group(1))
        except json.JSONDecodeError as exc:
            payload = {"_parse_error": str(exc)[:200]}
    return {"file": path.name, "meta": declared,
            "payload_profile": str(payload.get("reader_profile") or ""),
            "payload": payload,
            "lang_btn_markup": len(re.findall(r'id="lang-btn"', text)),
            "html_sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def _visual_qa_report_for(output: Path) -> "tuple[Path | None, dict | None]":
    """本次重跑的报告优先，其次才是产物目录里那份 visual-qa.json。"""
    for candidate in (output / "delivery-visual-rerun.json", output / "visual-qa.json"):
        if candidate.is_file():
            try:
                return candidate, json.loads(candidate.read_bytes().decode("utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                return candidate, {"_read_error": str(exc)[:200]}
    return None, None


def _source_ledger_chain(errors: list[str]) -> dict:
    """来源台账正式链的注册面（合同 reader_language.source_ledger_chain）；缺登记就报码，不猜规则。"""
    chain = (spa_renderer.reader_language_contract() or {}).get("source_ledger_chain")
    if not isinstance(chain, dict):
        errors.append("SPA_SOURCE_LEDGER_CHAIN_UNREGISTERED|合同没有 reader_language.source_ledger_chain："
                      "正式链（input dataset→canonical_dataset→source_projection→source_records→DOM）"
                      "与它的核对义务没有登记处，本门不许在没有规则来源的情况下放行")
        return {}
    return chain


# 核对腿的名字（不是码）：码字符串必须逐腿从合同登记里取，一条不许在门里硬写。
PROVENANCE_LEGS = ("absent", "rows", "input_sha", "ledger_digest", "seal_sha")


def _check_zh_formal_ledger_provenance(profiles: list[dict], errors: list[str],
                                       warnings: list[str], chain: dict,
                                       dataset_path: str = "", run_manifest_path: str = "") -> dict:
    """正式件的血缘核对：产物自证 ⇄ 运行 dataset ⇄ 封存记录，三方必须指同一份输入字节。

    业主 2026-11-03 裁 finding_1：真生成器必须从正式输入 dataset 携带 source_evidence_meta，
    正式链走到 DOM 还要**核对输入 SHA**；直调 render_spa_document() 拿不到输入字节，那种件
    造不出自证 ⇒ 在这一腿就被判 ABSENT ⇒ 它只剩 smoke 身份，不算交付证据。
    """
    gate = chain.get("provenance_gate") or {}
    codes = gate.get("codes") or {}
    if not isinstance(codes, dict) or sorted(codes) != sorted(PROVENANCE_LEGS):
        errors.append(
            "SPA_SOURCE_LEDGER_PROVENANCE_RULE_UNREGISTERED|合同 provenance_gate.codes 登记的是 %s，"
            "本门要用的腿是 %s：核对码必须由合同逐腿给出，门里不硬写第二套名单"
            % (sorted(codes) if isinstance(codes, dict) else codes, sorted(PROVENANCE_LEGS)))
        return {"legs": "unregistered"}
    face_key = ""
    try:
        face_key = registered_reader_face_key()
    except Exception as exc:  # ProjectionError/ValueError：登记面坏了就是门的问题，不许静默跳过
        errors.append("SPA_SOURCE_LEDGER_FACE_KEY_UNREGISTERED|读者来源面键名读不出来：%s" % exc)

    dataset_file = Path(dataset_path) if dataset_path else None
    dataset_digest = ""
    dataset_face = None
    if dataset_file is not None and dataset_file.is_file():
        dataset_digest = hashlib.sha256(dataset_file.read_bytes()).hexdigest()
        try:
            raw = json.loads(dataset_file.read_bytes().decode("utf-8"))
            face = raw.get(face_key) if isinstance(raw, dict) else None
            dataset_face = face if isinstance(face, list) else None
        except (OSError, json.JSONDecodeError) as exc:
            errors.append("SPA_SOURCE_LEDGER_DATASET_UNREADABLE|--data %s 读不出来：%s"
                          % (dataset_file, str(exc)[:120]))
    seal_input = ""
    manifest_file = Path(run_manifest_path) if run_manifest_path else None
    if manifest_file is not None and manifest_file.is_file():
        try:
            manifest_value = json.loads(manifest_file.read_bytes().decode("utf-8"))
            seal_input = str(((manifest_value or {}).get("seal") or {}).get("input_sha256")
                             or (manifest_value or {}).get("input_sha256") or "")
        except (OSError, json.JSONDecodeError) as exc:
            errors.append("SPA_SOURCE_LEDGER_MANIFEST_UNREADABLE|--run-manifest %s 读不出来：%s"
                          % (manifest_file, str(exc)[:120]))

    declared_items = []
    for item in profiles:
        label = item["file"]
        payload = item.get("payload") or {}
        declared = payload.get("source_ledger_meta")
        records = payload.get("source_records")
        records_rows = len(records) if isinstance(records, list) else None
        if not isinstance(declared, dict):
            errors.append(
                "%s|[%s] 读者载荷没有 source_ledger_meta 自证块（实测 %r）：这一件不是从正式生成链"
                "装配出来的——直调 render_spa_document() 没有输入字节可指，按合同只算 smoke，"
                "不得作为中文正式交付证据（登记处 reader_language.source_ledger_chain.smoke_call_rule）"
                % (codes["absent"], label, declared))
            continue
        declared_items.append(declared)
        try:
            rows = int(declared.get("dataset_rows"))
        except (TypeError, ValueError):
            rows = None
        if rows is None or rows != records_rows:
            errors.append(
                "%s|[%s] 自证记 dataset_rows=%r，读者载荷里的投影面 source_records 是 %s 行："
                "台账面与投影面不是同一张表，正式链在这一环断了"
                % (codes["rows"], label, declared.get("dataset_rows"), records_rows))
        declared_input = str(declared.get("input_sha256") or "")
        if dataset_digest and declared_input != dataset_digest:
            errors.append(
                "%s|[%s] 自证指名的输入摘要 %s ≠ 现行 --data 文件摘要 %s：产物声称的输入字节"
                "与门禁实际核对的那份不是同一份" % (codes["input_sha"], label,
                                                    declared_input[:12], dataset_digest[:12]))
        if dataset_face is not None:
            for code, detail in source_projection.provenance_problems(declared, dataset_face):
                if code == "provenance_digest_mismatch":
                    errors.append("%s|[%s] %s" % (codes["ledger_digest"], label, detail))
                elif code == "provenance_rows_mismatch":
                    errors.append("%s|[%s] %s" % (codes["rows"], label, detail))
                elif code not in ("provenance_absent",):
                    errors.append("SPA_SOURCE_LEDGER_PROVENANCE_SHAPE_WRONG|[%s] %s：%s"
                                  % (label, code, detail))
        if seal_input and declared_input and declared_input != seal_input:
            errors.append(
                "%s|[%s] 自证的输入摘要 %s ≠ 运行 manifest 封存的 input_sha256 %s："
                "生成时钉死的输入与产物声称的输入不一致（追认改摘要禁止）"
                % (codes["seal_sha"], label, declared_input[:12], seal_input[:12]))
    legs = {"dataset_leg": bool(dataset_digest), "manifest_leg": bool(seal_input),
            "declared": len(declared_items)}
    if not dataset_digest or not seal_input:
        warnings.append(
            "SPA_SOURCE_LEDGER_INPUT_SHA_NOT_CROSS_CHECKED|本次核对缺腿：--data=%r、--run-manifest=%r；"
            "只验了产物自证的内部一致性，没有把它钉到具体输入字节与封存记录上——"
            "这条结论不得被引用成「输入 SHA 已核对」（合同 %s）"
            % (dataset_path or "", run_manifest_path or "",
               "reader_language.source_ledger_chain.provenance_gate.cross_check_inputs"))
    return legs


def _check_zh_formal_evidence(output: Path, profiles: list[dict], errors: list[str],
                              warnings: list[str], dataset_path: str = "",
                              run_manifest_path: str = "") -> str:
    """正式档的替代验证：英文态检查不适用于这份产物，且这里证明它为什么不适用。

    两条独立来源互相核对，避免「门自己发证据自己读」：
    1) 交付字节实测——切换入口的标记、读者载荷里候审英文的键、载荷的来源投影行数；
    2) visual_qa 报回来的浏览器实测——DOM 里 #lang-btn 的节点数、面板行数/统计/分组、
       dataset→投影→DOM 三段对账。
    两边数字必须一致；证据缺失、来自别的产物、或任何一项不合，都记错误并返回 NOT_RUN 形状。
    """
    formal = spa_renderer.formal_reader_profile()
    excluded = [str(key) for key in (spa_renderer.reader_profile_spec(formal)
                                     .get("excluded_payload_keys") or [])]
    for item in profiles:
        if item["meta"] != formal:
            errors.append("SPA_ZH_FORMAL_PROFILE_DISAGREE|%s 的 meta 档位是 %r，不是注册正式档 %r"
                          % (item["file"], item["meta"], formal))
        if item["payload_profile"] != formal:
            errors.append("SPA_ZH_FORMAL_PROFILE_DISAGREE|%s 载荷 reader_profile 是 %r，meta 却是 %r"
                          % (item["file"], item["payload_profile"], item["meta"]))
        if item["lang_btn_markup"]:
            errors.append(
                "SPA_ZH_FORMAL_TOGGLE_PRESENT|%s 的 HTML 里还有 %d 处 id=\"lang-btn\" 标记："
                "正式交付必须删掉切换入口的元素（合同禁止以 CSS 隐藏代替删除）"
                % (item["file"], item["lang_btn_markup"]))
        leaked = sorted(key for key in excluded if key in (item.get("payload") or {}))
        if leaked:
            errors.append(
                "SPA_ZH_FORMAL_EXCLUDED_PAYLOAD_KEY_PRESENT|%s 的读者载荷仍带候审英文显示面键 %s"
                "（注册表 renderer-contract.json::reader_language.profiles[%s].excluded_payload_keys）"
                % (item["file"], leaked, formal))
    ledger_legs = _check_zh_formal_ledger_provenance(
        profiles, errors, warnings, _source_ledger_chain(errors),
        dataset_path=dataset_path, run_manifest_path=run_manifest_path)
    report_path, report = _visual_qa_report_for(output)
    if report is None:
        errors.append(
            "SPA_ZH_FORMAL_EVIDENCE_MISSING|正式档交付目录里没有可读的视觉 QA 报告"
            "（找过 delivery-visual-rerun.json / visual-qa.json）：英文态检查对正式产物不适用"
            "的前提是正式档证据已经验过，两份都没有时本门不许放行，也不许代签一个 PASS")
        return "NOT_RUN(no visual-qa report for the formal artifact)"
    if "_read_error" in (report or {}):
        errors.append("SPA_ZH_FORMAL_EVIDENCE_UNREADABLE|%s 读不出来：%s"
                      % (report_path.name, report["_read_error"]))
        return "NOT_RUN(unreadable visual-qa report)"
    checked = [item for item in report.get("checks") or []
               if isinstance(item, dict) and item.get("renderer") == "travel-scope-spa-v1"
               and "failures" in item]
    if not checked:
        errors.append("SPA_ZH_FORMAL_EVIDENCE_NOT_RUN|%s 里没有一条 SPA 检查："
                      "正式产物从未被浏览器检过，英文态不适用只是推论，不是证据"
                      % report_path.name)
        return "NOT_RUN(no SPA check in visual-qa report)"
    claimed = (report.get("html_sha256") or {}).get("spa")
    live = {item["html_sha256"] for item in profiles}
    if claimed and claimed not in live:
        errors.append(
            "SPA_ZH_FORMAL_EVIDENCE_STALE|%s 检的是 %s，盘上现行产物是 %s："
            "证据不是这一份文件的证据，不得据它放行"
            % (report_path.name, str(claimed)[:12], sorted(x[:12] for x in live)))
        return "NOT_RUN(evidence is not about the shipped bytes)"
    reconciled: list[str] = []
    for item in checked:
        label = item.get("label", "?")
        state = (item.get("reader_profile") or {})
        if state.get("meta_declared") != formal or state.get("payload_declared") != formal:
            errors.append("SPA_ZH_FORMAL_PROFILE_DISAGREE|[%s] 视觉 QA 读到的档位是 meta=%r/payload=%r，"
                          "不是 %r" % (label, state.get("meta_declared"),
                                       state.get("payload_declared"), formal))
        formal_block = item.get("zh_formal") or {}
        if not formal_block:
            errors.append("SPA_ZH_FORMAL_EVIDENCE_MISSING|[%s] 报告没有 zh_formal 证据块："
                          "切换入口与载荷剔除没有被实测（缺证据不等于没问题）" % label)
        else:
            if formal_block.get("lang_btn_count") != 0:
                errors.append("SPA_ZH_FORMAL_TOGGLE_PRESENT|[%s] DOM 里 #lang-btn 有 %s 个"
                              % (label, formal_block.get("lang_btn_count")))
            if formal_block.get("excluded_key_hits"):
                errors.append("SPA_ZH_FORMAL_EXCLUDED_PAYLOAD_KEY_PRESENT|[%s] 载荷仍带 %s"
                              % (label, formal_block.get("excluded_key_hits")))
            # 英文态遍历的记录必须是「明确没跑＋为什么没跑」，不能靠一个恒为假的布尔值放行：
            # zh_formal.english_mode_walk 自己永远是 False（正式档结构性跑不了），拿它当判据＝焊绿的灯。
            # 真正的证据是 check_spa_page 顶层那条 english_mode_walk 记录：ran 必须是 False 且带原因。
            walk = item.get("english_mode_walk")
            if not isinstance(walk, dict) or walk.get("ran") is not False or not walk.get("reason"):
                errors.append("SPA_ZH_FORMAL_EN_WALK_RAN|[%s] 正式档的英文态遍历记录不完整（实测 %r）："
                              "既没有 ran=False＋原因的记录，就不能声称「英文检查不适用是因为没有英文入口」"
                              % (label, walk))
        panel = item.get("source_panel") or {}
        if not panel:
            errors.append("SPA_SOURCE_PANEL_EVIDENCE_MISSING|[%s] 报告没有 source_panel 对账块" % label)
            continue
        if panel.get("ledger_status") != "projected":
            errors.append("SPA_SOURCE_LEDGER_ABSENT|[%s] 来源台账状态是 %r，正式件不得带着缺失的台账出货"
                          % (label, panel.get("ledger_status")))
        numbers = ((panel.get("reconcile") or {}).get("numbers")) or {}
        if not (panel.get("reconcile") or {}).get("ok"):
            errors.append("SPA_SOURCE_ROW_COUNT_DRIFT|[%s] 三段对账不合：%s（口径 source_projection.reconcile）"
                          % (label, (panel.get("reconcile") or {}).get("problems")))
        if not panel.get("dataset_leg_measured"):
            errors.append("SPA_SOURCE_DATASET_ROWS_UNMEASURABLE|[%s] 报告没量到运行 dataset 的来源行数，"
                          "dataset→投影→DOM 只剩两段，正式档不得当作通过" % label)
        if numbers.get("dom") != panel.get("dom_rows") or numbers.get("projected") != panel.get("payload_rows"):
            errors.append("SPA_SOURCE_RECONCILE_NUMBERS_WRONG|[%s] 报告里的对账数字与它自己记的行数不一致："
                          "numbers=%s dom_rows=%s payload_rows=%s"
                          % (label, numbers, panel.get("dom_rows"), panel.get("payload_rows")))
        # 独立复算：交付字节里的读者载荷自己算一遍，不依赖 visual_qa 报回来的数字。
        live_rows = [row for profile_item in profiles
                     for row in ((profile_item.get("payload") or {}).get("source_records") or [])]
        live_counts = source_projection.counts(live_rows) if live_rows else {}
        live_total = sum(live_counts.get("by_status", {}).values())
        live_verified = (live_counts.get("by_status") or {}).get("verified")
        if live_rows and live_total != panel.get("payload_rows"):
            errors.append("SPA_SOURCE_RECONCILE_NUMBERS_WRONG|[%s] 报告记投影 %s 行，交付字节里的读者载荷"
                          "有 %d 行：证据与被检对象不是同一份" % (label, panel.get("payload_rows"), live_total))
        if live_rows and live_verified != panel.get("payload_verified"):
            errors.append("SPA_SOURCE_STAT_WRONG|[%s] 报告记 verified=%s，交付字节的载荷复算是 %s"
                          % (label, panel.get("payload_verified"), live_verified))
        dom_verified = None
        stats = panel.get("dom_stats") or {}
        if "verified" in stats:
            digits = re.sub(r"[^0-9]", "", str(stats.get("verified") or ""))
            dom_verified = int(digits) if digits else None
        if dom_verified is None:
            errors.append("SPA_SOURCE_STAT_MISSING|[%s] 面板没印 [data-se-count=\"verified\"]，"
                          "读者页的来源核验统计无从核对" % label)
        elif panel.get("payload_verified") != dom_verified:
            errors.append("SPA_SOURCE_STAT_WRONG|[%s] 面板印 verified=%s，从载荷逐行复算是 %s："
                          "「0 verified」这类假统计正是 #113 的形状"
                          % (label, dom_verified, panel.get("payload_verified")))
        reconciled.append("%s:dataset=%s/projected=%s/dom=%s/verified=%s"
                          % (label, numbers.get("dataset"), numbers.get("projected"),
                             numbers.get("dom"), panel.get("payload_verified")))
        if item.get("status") != "PASS":
            errors.append("SPA_ZH_FORMAL_CHECK_FAILED|[%s] 视觉 QA 对正式档判 FAIL：%s"
                          % (label, ";".join(str(f).split("|", 1)[0]
                                             for f in (item.get("failures") or [])[:6])))
    if (output / "visual-qa" / "spa-en-text.txt").is_file():
        warnings.append(
            "SPA_EN_TEXT_LEFTOVER_UNDER_FORMAL|%s 下仍有 visual-qa/spa-en-text.txt："
            "正式档不产这份证据，它是历史双语现场的残留，不作为本产物的英文态结论"
            % output.name)
    if errors:
        return "NOT_RUN(formal evidence incomplete: %d error(s))" % len(errors)
    return ("ZH_FORMAL_NOT_APPLICABLE(profile=%s；英文态检查对这份产物不适用，原因不是「没做」而是"
            "「按注册契约正式档没有英文切换入口、载荷里也没有候审英文显示面键」；已实测：切换入口 "
            "DOM 0 个、excluded_payload_keys 零命中、来源三段对账 %s、台账血缘 %s；证据来自 %s 的 %d 条 SPA 检查)"
            % (formal, " | ".join(reconciled) or "-",
               "dataset=%s manifest=%s 自证块=%d" % (ledger_legs.get("dataset_leg"),
                                                     ledger_legs.get("manifest_leg"),
                                                     ledger_legs.get("declared")),
               report_path.name, len(checked)))


def _check_delivery_dir_ships_only_shipping_profiles(output: Path, errors: list[str]) -> None:
    """业主 ZH-4：候审档（合同 shipping=false，如 en-audit）写进任何正式交付目录即阻断。

    判据不写在门里：非出货档位名单从注册表读（references/renderer-contract.json），错误码也从
    那里读（`profiles[档].delivery_dir_rule.code`）。文件名不参与判断——档位必须由交付字节里的
    meta 自己声明，所以一份被改名／被复制的候审件照样被自己的声明咬住。
    """
    contract = spa_renderer.reader_language_contract()
    profiles = contract.get("profiles") or {}
    non_shipping = sorted(name for name, spec in profiles.items()
                          if not isinstance(spec, dict) or spec.get("shipping") is not True)
    if not non_shipping:
        errors.append("SPA_AUDIT_PROFILE_RULE_UNREGISTERED|合同里没有任何 shipping=false 的档位："
                      "「候审档不得进交付目录」这条门没有对象可检，不许当作已放行")
        return
    meta_name = str(contract.get("html_meta_name") or "")
    if not meta_name:
        errors.append("SPA_AUDIT_PROFILE_RULE_UNREGISTERED|合同没有 html_meta_name：无法按字节读档位")
        return
    for path in sorted(output.glob("*.html")):
        text = path.read_text(encoding="utf-8", errors="replace")
        match = re.search(READER_PROFILE_META_RE_TMPL % re.escape(meta_name), text)
        declared = match.group(1) if match else ""
        if declared in non_shipping:
            code = str(((profiles.get(declared) or {}).get("delivery_dir_rule") or {})
                       .get("code") or "SPA_AUDIT_PROFILE_IN_FORMAL_DIR")
            errors.append(
                "%s|%s 声明读者档位 %r（shipping=false）却坐在交付目录 %s 里：候审档产物只许写在 "
                ".temp 审计面，出现在正式目录意味着这份交付件自带英文切换面，与 ZH-1 直接矛盾"
                % (code, path.name, declared, output))


def _check_spa_english_mode(output: Path, errors: list[str], warnings: list[str],
                            dataset_path: str = "", run_manifest_path: str = "") -> str:
    """§15.2: the SPA has no separate -en.html file, so its English state is the
    DOM after the language toggle. visual_qa exports that visible text; the English
    text policy is applied to it here instead of a file that never ships.

    ZH-RELEASE-1（业主 2026-11-02 裁 Q1-A）后按读者档位分支：正式档（注册的 formal_profile）
    根本没有英文切换入口，spa-en-text.txt 在结构上不可能产出——这里改验正式档证据，并把
    「英文态检查不适用」写成看得见的结论；候审档（en-audit）保持原有行为与判词。
    档位没声明或未登记 ⇒ 两套都不放行，报错误。
    """
    _check_delivery_dir_ships_only_shipping_profiles(output, errors)
    profiles = [_reader_profile_from_bytes(path) for path in _spa_html_files(output)]
    if profiles:
        contract = spa_renderer.reader_language_contract()
        registered = set(contract.get("profiles") or {})
        formal = str(contract.get("formal_profile") or "")
        declared = {str(item["meta"]) for item in profiles}
        if not all(declared):
            errors.append(
                "SPA_READER_PROFILE_UNDECLARED|交付字节里没有 %s 声明（档位=%s）："
                "没声明档位的产物等于没人知道自己该被哪套门检查，不得沿用任何一套的结论"
                % (contract.get("html_meta_name"), sorted(declared)))
            return "NOT_RUN(reader profile undeclared)"
        if declared - registered:
            errors.append("SPA_READER_PROFILE_UNREGISTERED|声明的档位 %s 不在注册表里（已登记 %s）"
                          % (sorted(declared - registered), sorted(registered)))
            return "NOT_RUN(reader profile unregistered)"
        if declared == {formal}:
            return _check_zh_formal_evidence(output, profiles, errors, warnings,
                                             dataset_path=dataset_path,
                                             run_manifest_path=run_manifest_path)
    export = output / "visual-qa" / "spa-en-text.txt"
    if not export.is_file():
        errors.append(
            "SPA_EN_EVIDENCE_MISSING|缺少 visual-qa/spa-en-text.txt（SPA 英文态可见文本证据）。"
            "reader/review 档位不产出独立 -en.html，因此英文文本门禁只能以该导出为对象；"
            "证据缺失时禁止任何'英文模式零汉字'类声明"
        )
        return "NOT_RUN(missing spa-en-text.txt)"
    text = export.read_text(encoding="utf-8", errors="replace")
    if not text.strip():
        errors.append("SPA_EN_EVIDENCE_EMPTY|spa-en-text.txt 为空，英文态未真正渲染")
        return "NOT_RUN(empty)"
    policy_path = Path(__file__).resolve().parents[1] / "references/run-quality-policy.json"
    policy = json.loads(policy_path.read_text(encoding="utf-8")) if policy_path.is_file() else {}
    tr_rules = policy.get("translation_rules", {})
    _check_english_text(
        "SPA EN 态",
        text,
        tr_rules.get("banned_synthetic_phrases", []),
        tr_rules.get("disallow_repetitive_tokens", ["area", "spot"]),
        tr_rules.get("max_repetitive_token_density", 0.008),
        tr_rules.get("max_cjk_ratio_in_english_artifacts", 0.001),
        errors,
    )
    hits = sorted({m.group(0) for m in SPA_PLACEHOLDER_RE.finditer(text)})
    if hits:
        errors.append(f"SPA_EN_PLACEHOLDER|英文态出现占位 venue 名 {hits[:6]}，读者会看到假地名")
    numeric = re.findall(r"(?:^|[,/\s])\d{2,4}(?:\s*km)?(?=[,/\s]|$)", text)
    if numeric:
        warnings.append(f"SPA_EN_NUMERIC_TOKEN|英文态出现疑似公里数串 {sorted(set(numeric))[:8]}，需确认是否冒充地名")
    measured = en_residue_measure.measure(text)
    return ("SCANNED(chars=%d, cjk=%d, leaked=%d, intentional=%d, ratio=%.2f%%, raw_ratio=%.2f%%)"
            % (measured["chars"], measured["raw_cjk"], measured["leaked_cjk"],
               measured["intentional_cjk"], measured["ratio"] * 100,
               measured["ratio_unadjusted"] * 100))


def _scan_final_artifacts(artifacts: dict[str, str], errors: list[str], output: Path,
                          warnings: list[str], dataset_path: str = "",
                          run_manifest_path: str = "") -> str:
    policy_path = Path(__file__).resolve().parents[1] / "references/run-quality-policy.json"
    if not policy_path.is_file():
        return
    policy = json.loads(policy_path.read_text(encoding="utf-8"))
    tr_rules = policy.get("translation_rules", {})
    banned_phrases = tr_rules.get("banned_synthetic_phrases", [])
    disallow_tokens = tr_rules.get("disallow_repetitive_tokens", ["area", "spot"])
    max_density = tr_rules.get("max_repetitive_token_density", 0.008)
    max_cjk_ratio = tr_rules.get("max_cjk_ratio_in_english_artifacts", 0.001)

    html_en_path = artifacts.get("html_en")
    if html_en_path and Path(html_en_path).is_file():
        raw_html = Path(html_en_path).read_text(encoding="utf-8", errors="replace")
        clean_html = re.sub(r"<(?:script|style)[^>]*>.*?</(?:script|style)>", " ", raw_html, flags=re.DOTALL | re.IGNORECASE)
        text_content = re.sub(r"<[^>]+>", " ", clean_html)
        _check_english_text("HTML(EN)", text_content, banned_phrases, disallow_tokens, max_density, max_cjk_ratio, errors)

    md_en_path = artifacts.get("md_en")
    if md_en_path and Path(md_en_path).is_file():
        raw_md = Path(md_en_path).read_text(encoding="utf-8", errors="replace")
        _check_english_text("Markdown(EN)", raw_md, banned_phrases, disallow_tokens, max_density, max_cjk_ratio, errors)

    xlsx_en_path = artifacts.get("xlsx_en")
    if xlsx_en_path and Path(xlsx_en_path).is_file():
        try:
            import openpyxl
            wb = openpyxl.load_workbook(xlsx_en_path, read_only=True, data_only=True)
            cell_texts = []
            for sheet in wb.worksheets:
                for row in sheet.iter_rows(values_only=True):
                    for cell in row:
                        if cell is not None and isinstance(cell, str) and cell.strip():
                            cell_texts.append(cell.strip())
            wb.close()
            combined_xlsx_text = " ".join(cell_texts)
            _check_english_text("Excel(EN)", combined_xlsx_text, banned_phrases, disallow_tokens, max_density, max_cjk_ratio, errors)
        except Exception as exc:
            errors.append(f"Excel(EN) 解析扫描失败: {exc}")

    for html_key in ("html_cn", "html_en", "html_bilingual"):
        h_path = artifacts.get(html_key)
        if h_path and Path(h_path).is_file():
            raw_html = Path(h_path).read_text(encoding="utf-8", errors="replace")
            h_matches = re.findall(r'<h1 id="headline">(.*?)</h1>', raw_html, re.DOTALL)
            for hm in h_matches:
                clean_h = re.sub(r'<[^>]+>', ' ', hm).strip()
                if re.search(r'(?<!\d)-Day\b', clean_h):
                    errors.append(f"{html_key} 标题出现裸露连字符 '-Day'，天数提取异常: '{clean_h}'")
                for banned in ("undefined", "null", "NaN"):
                    if banned in clean_h:
                        errors.append(f"{html_key} 标题包含异常占位词 '{banned}': '{clean_h}'")
                words = [w.strip() for w in clean_h.split() if w.strip()]
                for idx in range(len(words) - 1):
                    if len(words[idx]) >= 2 and words[idx] == words[idx+1]:
                        errors.append(f"{html_key} 标题出现连续重复词汇: '{words[idx]}': '{clean_h}'")

    if artifacts.get("html_spa"):
        return _check_spa_english_mode(Path(artifacts["html_spa"]).parent, errors, warnings,
                                       dataset_path=dataset_path,
                                       run_manifest_path=run_manifest_path)
    return "NOT_APPLICABLE(no SPA artifact)"


def _check_local_apps_delivery_parity(dataset_path: Path | None, artifacts: dict[str, str], errors: list[str]) -> None:
    if not dataset_path or not dataset_path.is_file():
        return
    try:
        data = json.loads(dataset_path.read_text(encoding="utf-8"))
        local_apps = data.get("local_apps") or []
        active_apps = [a for a in local_apps if isinstance(a, dict) and a.get("availability_status") not in ("retired", "pending")]
        if not active_apps:
            return

        for lang_key, heading in (("md_cn", "## 在地工具"), ("md_en", "## Local Toolkit")):
            md_path = artifacts.get(lang_key)
            if md_path and Path(md_path).is_file():
                content = Path(md_path).read_text(encoding="utf-8", errors="replace")
                if heading not in content:
                    errors.append(f"{lang_key} 产物缺失在地工具章节标题: '{heading}'")

        import openpyxl
        for lang_key, sheet_name in (("xlsx_cn", "常用APP"), ("xlsx_en", "Local Apps")):
            x_path = artifacts.get(lang_key)
            if x_path and Path(x_path).is_file():
                wb = openpyxl.load_workbook(x_path, read_only=True)
                if sheet_name not in wb.sheetnames:
                    errors.append(f"{lang_key} 工作簿缺失工作表: '{sheet_name}'")
                else:
                    ws = wb[sheet_name]
                    row_count = sum(1 for _ in ws.iter_rows(values_only=True)) - 1
                    if row_count != len(active_apps):
                        errors.append(f"{lang_key} 工作表 '{sheet_name}' 记录数 ({row_count}) 与 dataset active local_apps ({len(active_apps)}) 不一致")
                wb.close()
    except Exception as exc:
        errors.append(f"在地工具交付物一致性比对异常: {exc}")


def _check_cross_artifact_reconciliation(dataset_path: Path | None, artifacts: dict[str, str], errors: list[str]) -> None:
    """G4: Reconcile POI counts, day count, destination count, and route count across XLSX, MD, and dataset."""
    if not dataset_path or not dataset_path.is_file():
        return
    try:
        data = json.loads(dataset_path.read_text(encoding="utf-8"))
        ds_destinations = len(data.get("destinations") or [])
        ds_routes = len(data.get("routes") or [])
        ds_hotels = len(data.get("hotels") or [])
        ds_restaurants = len(data.get("restaurants") or [])
        ds_attractions = len(data.get("attractions") or [])

        import openpyxl
        for lang_key in ("xlsx_cn", "xlsx_en"):
            x_path = artifacts.get(lang_key)
            if x_path and Path(x_path).is_file():
                wb = openpyxl.load_workbook(x_path, read_only=True)
                sheet_checks = [
                    ("目的地总览", ds_destinations, "destinations"),
                    ("路线方案", ds_routes, "routes"),
                    ("住宿推荐", ds_hotels, "hotels"),
                    ("美食推荐", ds_restaurants, "restaurants"),
                    ("景点活动", ds_attractions, "attractions"),
                ]
                for sname, expected_count, kind in sheet_checks:
                    if sname in wb.sheetnames:
                        ws = wb[sname]
                        rows = [row for row in ws.iter_rows(values_only=True) if any(c is not None and str(c).strip() for c in row)]
                        count = max(0, len(rows) - 1)
                        if count != expected_count:
                            errors.append(f"{lang_key} 工作表 '{sname}' 记录数 ({count}) 与 dataset {kind} ({expected_count}) 不一致")
                wb.close()

        md_cn_path = artifacts.get("md_cn")
        if md_cn_path and Path(md_cn_path).is_file():
            md_text = Path(md_cn_path).read_text(encoding="utf-8", errors="replace")
            dest_match = re.search(r"共\s*\*\*(\d+)\*\*\s*个目的地", md_text)
            if dest_match and int(dest_match.group(1)) != ds_destinations:
                errors.append(f"md_cn 目的地数量 ({dest_match.group(1)}) 与 dataset destinations ({ds_destinations}) 不一致")
            hotel_match = re.search(r"共\s*\*\*(\d+)\*\*\s*家酒店", md_text)
            if hotel_match and int(hotel_match.group(1)) != ds_hotels:
                errors.append(f"md_cn 酒店数量 ({hotel_match.group(1)}) 与 dataset hotels ({ds_hotels}) 不一致")
    except Exception as exc:
        errors.append(f"跨交付物数据对账异常: {exc}")


def _run_validator(script: Path, html: Path, workbook: Path | None, errors: list[str]) -> None:
    # validate_output.py targets the retired pre-v4 DOM. The modern renderer is
    # covered by structural parity plus the browser visual-QA report below.
    if 'data-renderer="modern-v1"' in html.read_text(encoding="utf-8", errors="replace"):
        return
    command = pyc.interpreter([sys.executable, str(script), "--html", str(html)])
    if workbook:
        command += ["--delivery-xlsx", str(workbook)]
    result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8",
                            errors="replace", env=pyc.env())
    if result.returncode != 0:
        errors.append(f"输出门禁失败: {html.name}: {result.stdout.strip() or result.stderr.strip()}")


def _check_cn_en_parity(html_cn: Path, html_en: Path, errors: list[str]) -> None:
    """Check structural parity without comparing translated display text."""
    cn = html_cn.read_text(encoding="utf-8", errors="replace")
    en = html_en.read_text(encoding="utf-8", errors="replace")
    modern = 'data-renderer="modern-v1"' in cn or 'data-renderer="modern-v1"' in en
    patterns = {
        "destination_sections": r'<(?:div|section) class="dest-section\b',
        "location_cards": r'<article class="modern-poi\b' if modern else r'<div class="loc-card\b',
        "daily_route_anchors": r'data-map-scope="daily_destination"' if not modern else r'"map_scope": "daily_destination"',
    }
    for label, pattern in patterns.items():
        cn_count = len(re.findall(pattern, cn))
        en_count = len(re.findall(pattern, en))
        if cn_count != en_count:
            errors.append(f"CN/EN 结构数量不一致: {label} CN={cn_count}, EN={en_count}")


def _check_local_assets(assets: Path, errors: list[str]) -> None:
    if not assets.exists():
        return
    hashes: dict[str, Path] = {}
    for path in assets.rglob("*"):
        if not path.is_file():
            continue
        try:
            _, content_hash, byte_size = inspect_image(path)
            if byte_size <= 0:
                errors.append(f"图片资源为空: {path.name}")
            if content_hash in hashes:
                errors.append(f"图片内容重复: {hashes[content_hash].name} 与 {path.name}")
            hashes[content_hash] = path
        except Exception as exc:
            errors.append(f"图片资源无法解码: {path.name}: {exc}")


def _check_dataset_media_references(dataset_path: Path | None, output: Path, errors: list[str]) -> None:
    """Ensure all non-inlined media paths referenced in dataset.json physically exist on disk."""
    if not dataset_path or not dataset_path.is_file():
        return
    try:
        data = json.loads(dataset_path.read_text(encoding="utf-8"))
        for cat in ("editorial_media", "section_media"):
            for item in data.get(cat) or []:
                if isinstance(item, dict) and item.get("image"):
                    img_ref = str(item["image"])
                    if img_ref.startswith("assets/") and not img_ref.startswith("data:"):
                        rel = img_ref[7:]
                        disk_path = output / "assets" / rel
                        if not disk_path.is_file() and not (output.parent / img_ref).is_file():
                            errors.append(f"dataset.json 中引用的图片资源在磁盘不存在: {img_ref}")
    except Exception as exc:
        errors.append(f"dataset.json 媒体引用检查失败: {exc}")


def _check_asset_manifest(cache_db: str, errors: list[str]) -> None:
    if not cache_db:
        return
    db = Path(cache_db)
    if not db.exists():
        return
    try:
        with sqlite3.connect(db) as connection:
            rows = connection.execute(
                "SELECT asset_path, COUNT(DISTINCT poi_name), COUNT(DISTINCT category) FROM asset_usage GROUP BY asset_path"
            ).fetchall()
            for asset_path, poi_count, category_count in rows:
                if int(poi_count) > 1 or int(category_count) > 1:
                    errors.append(f"素材跨 POI 或类别复用: {asset_path}")
            unverified = connection.execute(
                "SELECT asset_path FROM asset_manifest WHERE status <> 'verified' OR TRIM(source_ref) = '' OR byte_size <= 0 OR mime_type NOT LIKE 'image/%'"
            ).fetchall()
            for (asset_path,) in unverified:
                errors.append(f"素材来源或验证状态不合格: {asset_path}")
            duplicate_content = connection.execute(
                "SELECT content_hash, COUNT(DISTINCT poi_name) FROM asset_manifest GROUP BY content_hash HAVING COUNT(DISTINCT poi_name) > 1"
            ).fetchall()
            for content_hash, poi_count in duplicate_content:
                errors.append(f"素材内容哈希跨 POI 重复: {content_hash} ({poi_count} 个 POI)")
    except sqlite3.Error as exc:
        errors.append(f"素材 SQLite 台账无法读取: {exc}")


def _check_scope_evidence(manifest_path: str, scope_path: str, corridors_path: str, errors: list[str]) -> None:
    """Require real scope/corridor evidence for Live delivery, not stage labels alone."""
    if not manifest_path:
        errors.append("Live 交付缺少运行 manifest")
        return
    manifest_file = Path(manifest_path)
    if not manifest_file.is_file():
        errors.append(f"运行 manifest 不存在: {manifest_file}")
        return
    try:
        manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    except Exception as exc:
        errors.append(f"运行 manifest 无法读取: {exc}")
        return
    required_stages = {"destination_discovery", "route_exploration", "source_search", "source_audit", "section_media_collection", "section_media_contact_sheet_review", "artifact_generation", "visual_qa", "qa"}
    missing_stages = sorted(required_stages - set(manifest.get("completed_stages") or []))
    if missing_stages:
        errors.append(f"运行 manifest 缺少已完成阶段: {missing_stages}")
    # 命令行显式给的优先按调用方给法用；从 run manifest 取的相对值以 run 根解析（R3F 同一把尺子）。
    run_root = manifest_file.resolve().parent
    declared_scope = scope_path or manifest.get("scope_path") or manifest.get("destination_scope_path") or ""
    declared_corridors = corridors_path or manifest.get("route_corridors_path") or ""
    scope_file = Path(declared_scope) if scope_path else resolve_run_path(declared_scope, run_root)
    corridor_file = Path(declared_corridors) if corridors_path else resolve_run_path(declared_corridors, run_root)
    if not scope_file.is_file():
        errors.append(f"缺少目的地范围证据文件: {scope_file}")
    else:
        try:
            scope = json.loads(scope_file.read_text(encoding="utf-8"))
            selected = scope.get("selected_destinations") or scope.get("destinations") or []
            if not isinstance(selected, list) or not selected:
                errors.append("目的地范围证据没有已筛选目的地")
            else:
                malformed = [item for item in selected if not isinstance(item, dict) or not item.get("name")]
                if malformed:
                    errors.append("目的地范围证据存在缺少名称的记录")
        except Exception as exc:
            errors.append(f"目的地范围证据无法读取: {exc}")
    if not corridor_file.is_file():
        errors.append(f"缺少路线走廊证据文件: {corridor_file}")
    else:
        try:
            corridors = json.loads(corridor_file.read_text(encoding="utf-8"))
            if not isinstance(corridors.get("corridors"), list) and not isinstance(corridors.get("subcorridors"), list):
                errors.append("路线走廊证据缺少 corridors/subcorridors")
            coverage = corridors.get("coverage") or {}
            classic_coverage = corridors.get("classic_coverage") or {}
            if coverage.get("uncovered") or classic_coverage.get("uncovered"):
                errors.append("路线走廊仍有未覆盖或未解释排除的候选")
        except Exception as exc:
            errors.append(f"路线走廊证据无法读取: {exc}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the complete Travel-Scope delivery gate")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--cache-db", default="")
    parser.add_argument("--mode", choices=["live", "demo"], default="live")
    parser.add_argument("--daily-limit", type=int, default=33)
    parser.add_argument("--monthly-limit", type=int, default=1000)
    parser.add_argument("--report", default="")
    parser.add_argument("--preflight", default="", help="Interactive preflight JSON used for Live delivery")
    parser.add_argument("--run-manifest", default="", help="Formal run manifest for Live delivery")
    parser.add_argument("--scope-json", default="", help="Destination scope evidence for Live delivery")
    parser.add_argument("--route-corridors", default="", help="Route corridor evidence for Live delivery")
    parser.add_argument("--data", default="", help="Unified verified dataset for cross-artifact truth checks")
    parser.add_argument("--asset-manifest", default="", help="Run-local media rights and visual-review manifest")
    parser.add_argument("--media-audit", default="", help="Required PASS media audit for Live delivery")
    parser.add_argument("--visual-qa-report", default="", help="Required PASS visual QA report for Live delivery")
    parser.add_argument("--delivery-profile", default="reader", choices=["reader", "review", "full_audit"], help="Delivery profile to enforce")
    parser.add_argument("--visual-qa", action="store_true", help="Run browser visual smoke checks at desktop and mobile viewports")
    args = parser.parse_args()

    output = Path(args.output_dir).resolve()
    script_dir = Path(__file__).resolve().parent
    errors: list[str] = []
    # v4.2.1 §15.1.1: the delivery gate must attest the release body itself.
    # sha256(product-origin.json) only proves the seal file is unchanged; verify()
    # proves the sealed source files still match their digests.
    try:
        verify_release_product()
    except Exception as exc:
        errors.append(f"发布体完整性校验失败（product-origin 与源码摘要不一致）: {exc}")

    warnings: list[str] = []
    artifacts: dict[str, str] = {}
    image_attestation: dict[str, dict] = {}
    single_file_audit: dict | None = None
    if not output.is_dir():
        errors.append(f"输出目录不存在: {output}")
    else:
        # 清扫「陈旧件」之前，先把**本次调用自己要读的输入**全部保下来。
        # 旧的保护面是手抄的五个参数（media_audit／visual_qa_report／data／asset_manifest／report），
        # 漏了 --preflight：同一趟运行里先把生成器写在 outputs/ 的 MEDIA_PREFLIGHT.json 删掉，
        # 再报「前置 QA 文件无法读取」。2026-11-03 实测：10:37 构建后该文件在盘上，10:49 跑完全套门就没了，
        # 而这一门的 live 档又必须读它——门自己把自己的一条腿锯了。
        # 现在按 args 全量取，以后新增加一个输入参数也不会再漏；这不是放宽清扫
        # （未被任何参数点名的陈旧件照旧删掉），而是「不许删掉自己声明要读的东西」这条底线。
        protected_paths = {
            Path(value).resolve()
            for value in vars(args).values()
            if isinstance(value, str) and value.strip() and Path(value).is_file()
        }
        stale_list = [
            "MEDIA_PREFLIGHT.json", "local-media-report.json", "media-review.txt",
            "scratch_test_en.md", "scratch_test_en.xlsx", "scratch_untranslated.json",
            "all_dataset_cjk_strings.json"
        ]
        for stale in stale_list:
            for cand in (output / stale, output.parent / stale, output.parent / "outputs" / stale):
                if cand.is_file() and cand.resolve() not in protected_paths:
                    try:
                        cand.unlink()
                    except OSError:
                        pass

    # Discover artifacts based on delivery profile (v4.1.8: default is 'reader')
    html_spa = _first(output, "*-travel-guide.html") or _first(output, "*重构版.html")
    html_cn = _first(output, "*地图标记.html")
    html_en = _first(output, "*地图标记-en.html")
    html_bilingual = _first(output, "*双语.html")
    xlsx_research = _first(output, "*-travel-research.xlsx")
    xlsx_cn = _first(output, "*攻略大全.xlsx")
    xlsx_en = _first(output, "*攻略大全-en.xlsx")
    md_cn = _first(output, "*攻略大全.md")
    md_en = _first(output, "*攻略大全-en.md")

    if args.delivery_profile == "reader":
        if html_spa:
            artifacts["html_spa"] = str(html_spa)
        else:
            errors.append("缺少读者版 SPA 交付文件: *-travel-guide.html")
    elif args.delivery_profile == "review":
        if html_spa:
            artifacts["html_spa"] = str(html_spa)
        else:
            errors.append("缺少读者版 SPA 交付文件: *-travel-guide.html")
        if xlsx_research:
            artifacts["xlsx_research"] = str(xlsx_research)
        else:
            errors.append("缺少研究工作簿交付文件: *-travel-research.xlsx")
    else:  # full_audit
        for label, path in (("html_cn", html_cn), ("html_en", html_en), ("html_bilingual", html_bilingual), ("html_spa", html_spa), ("xlsx_cn", xlsx_cn), ("xlsx_en", xlsx_en), ("md_cn", md_cn), ("md_en", md_en)):
            if path:
                artifacts[label] = str(path)
            elif label == "html_spa":
                warnings.append("缺少 SPA 重构版交付文件: *-travel-guide.html")
            else:
                errors.append(f"缺少交付文件: {label}")

    if html_cn and xlsx_cn:
        _run_validator(script_dir / "validate_output.py", html_cn, xlsx_cn, errors)
    if html_en and xlsx_en:
        _run_validator(script_dir / "validate_output.py", html_en, xlsx_en, errors)
    if html_bilingual and xlsx_cn:
        _run_validator(script_dir / "validate_output.py", html_bilingual, xlsx_cn, errors)
    if html_cn and html_en:
        _check_cn_en_parity(html_cn, html_en, errors)
    if (args.visual_qa or args.mode != "demo") and output.is_dir():
        visual_script = script_dir / "visual_qa.py"
        rerun_report = output / "delivery-visual-rerun.json"
        qa_argv = pyc.interpreter(
            [sys.executable, str(visual_script), "--output-dir", str(output),
             "--report", str(rerun_report)])
        if args.asset_manifest:
            qa_argv += ["--asset-manifest", args.asset_manifest]
        if args.mode != "demo":
            # V5-D（V0-L12）：真实交付档必须把读者页每张图对账到登记字节；没有清单就是阻断，
            # 不是「跳过这项检查」。demo 档没有 run 清单，允许不强制（报告里仍写明 enforced=false）。
            qa_argv.append("--require-asset-manifest")
        result = subprocess.run(qa_argv, capture_output=True, text=True,
                                encoding="utf-8", errors="replace", env=pyc.env())
        if result.returncode != 0:
            errors.append(f"浏览器视觉 QA 失败: {result.stdout.strip() or result.stderr.strip()}")
        else:
            rerun_trust = gate_producer.verify_report(rerun_report, script_dir.parent)
            if rerun_trust["trust"] != "TRUSTED":
                errors.append("本次重跑的视觉 QA 报告没有可追溯的产出者身份: "
                              + " | ".join(rerun_trust["findings"][:4]))

    # V5-B（V0-L07）：英文汉字门禁必须排在视觉 QA 之后。
    # reader/review 档没有独立 -en.html，英文证据是 visual_qa 切语言后导出的
    # visual-qa/spa-en-text.txt；旧顺序是先扫英文、后跑视觉 QA，于是这份导出在扫描的
    # 那一刻还不存在——门禁结构上读不到读者真正看到的英文态（V0-L07 记的就是这个）。
    english_text_check = _scan_final_artifacts(
        artifacts, errors, output, warnings,
        dataset_path=args.data,
        run_manifest_path=(args.run_manifest or os.environ.get("TRAVEL_SCOPE_RUN_MANIFEST", "")))
    dataset_file = Path(args.data) if args.data else None
    if not dataset_file or not dataset_file.is_file():
        cand = output / "dataset.json"
        if cand.is_file():
            dataset_file = cand
        elif args.mode == "demo":
            cand_demo = script_dir.parent / "fixtures" / "demo.json"
            if cand_demo.is_file():
                dataset_file = cand_demo
    _check_local_apps_delivery_parity(dataset_file, artifacts, errors)
    # V5-B（V0-L05）：读者档也必须跑汇率登记检查——formal gate 只在 live 路径出现，
    # demo/review 档如果不调用，FX 规则就只在部分交付档可达（正是 V0-L07 记的那类结构性空洞）。
    if dataset_file and dataset_file.is_file():
        try:
            fx_dataset = json.loads(dataset_file.read_text(encoding="utf-8"))
            errors.extend("汇率契约: %s" % item
                          for item in budget_contract.findings_for(fx_dataset, root=script_dir.parent))
        except Exception as exc:  # noqa: BLE001
            errors.append(f"汇率契约: dataset 无法读取，未判定（没检查不等于通过）: {exc}")
    else:
        errors.append("汇率契约: 没有可读的 dataset，FX 检查未执行（§10：不得当作通过）")
    _check_cross_artifact_reconciliation(dataset_file, artifacts, errors)

    html_files = [p for p in (html_cn, html_en, html_bilingual, html_spa) if p]
    for html_path in html_files:
        text = html_path.read_text(encoding="utf-8", errors="replace")
        if re.search(r"AIza[0-9A-Za-z_-]{20,}|X-Goog-Api-Key|TRAVEL_SCOPE_GOOGLE_PLACES_KEY", text):
            errors.append(f"HTML 疑似泄漏 API Key 或 Key 变量: {html_path.name}")
        if "var LIVE_MAP_ENABLED = false;" in text and re.search(r"https://(?:maps\.googleapis\.com|webapi\.amap\.com|places\.googleapis\.com)", text):
            errors.append(f"普通网页模式 HTML 仍包含供应商运行时 URL: {html_path.name}")

    if html_spa:
        spa_text = html_spa.read_text(encoding="utf-8", errors="replace")
        if re.search(r"const num = Number\(cnyVal\) \|\| 0", spa_text):
            errors.append("SPA 重构版 money() 仍为旧版 Number(cnyVal)||0，未修复区间/比索解析（v4.1.4 修复项）")
        # v4.1.8: Strict DOM & Script Validation
        if "[object Object]" in spa_text:
            errors.append(f"SPA 产物包含非法对象序列化文字 '[object Object]': {html_spa.name}")
        if re.search(r">\s*undefined\s*<", spa_text) or "undefined人均" in spa_text:
            errors.append(f"SPA 产物包含异常 'undefined' 文本: {html_spa.name}")
        if re.search(r">\s*NaN\s*<", spa_text) or "NaN人均" in spa_text:
            errors.append(f"SPA 产物包含异常 'NaN' 文本: {html_spa.name}")
        if "poi-details" in spa_text:
            errors.append(f"SPA 产物包含已弃用的 'poi-details' 规划详情折叠组件: {html_spa.name}")
        hardcoded_rate_patterns = (
            r"(?:USD_RATE|getUsdRate\s*=)[^\n]{0,160}\b7\.20\b",
            r"(?:PHP_RATE|getPhpRate\s*=)[^\n]{0,160}\b8\.0\b",
            r"return\s+(?:7\.20|8\.0)\s*;",
        )
        if any(re.search(pattern, spa_text) for pattern in hardcoded_rate_patterns):
            errors.append(f"SPA 引擎仍包含硬编码汇率兜底: {html_spa.name}")
        # V5-D（V0-L11）：读者要下载的那串字节必须被数过，且每个交付档都要数——
        # 以前只有 visual_qa 的 DOM 侧预算（只数浏览器要解码的图），没人报「这个文件多大」。
        try:
            single_file_audit = self_contained_audit.audit(html_spa)
        except single_file_policy.SingleFilePolicyError as exc:
            single_file_audit = {"status": "FAIL", "findings": [f"SFD_POLICY_MISSING|{exc}"],
                                 "blocking": [f"SFD_POLICY_MISSING|{exc}"], "advisory": [],
                                 "measured": {"html": str(html_spa).replace("\\", "/")}}
        except Exception as exc:  # noqa: BLE001
            single_file_audit = {"status": "FAIL",
                                 "findings": [f"SFD_FILE_UNREADABLE|单文件对账没跑起来: {exc}"],
                                 "blocking": [f"SFD_FILE_UNREADABLE|单文件对账没跑起来: {exc}"],
                                 "advisory": [], "measured": {"html": str(html_spa).replace("\\", "/")}}
        errors.extend(f"单文件字节账单: {item}" for item in single_file_audit["blocking"])

    assets = output / "assets"
    if assets.exists() and not any(p.is_file() and p.stat().st_size > 0 for p in assets.rglob("*")):
        errors.append("assets 目录存在但没有有效本地图片")
    _check_local_assets(assets, errors)
    _check_dataset_media_references(dataset_file, output, errors)
    _check_asset_manifest(args.cache_db, errors)

    output_asset_manifest = output / "asset-manifest.json"
    if not output_asset_manifest.is_file():
        errors.append("交付 outputs 目录缺少 asset-manifest.json 资产清单")
    else:
        try:
            out_manifest_data = json.loads(output_asset_manifest.read_text(encoding="utf-8"))
            out_assets = out_manifest_data.get("assets") or []
            if not out_assets:
                errors.append("交付 outputs/asset-manifest.json 资产清单为空")
            if args.asset_manifest and Path(args.asset_manifest).is_file():
                root_manifest_data = json.loads(Path(args.asset_manifest).read_text(encoding="utf-8"))
                root_assets = root_manifest_data.get("assets") or []
                if len(out_assets) != len(root_assets):
                    errors.append(f"outputs/asset-manifest.json 与根目录资产清单数量不一致 ({len(out_assets)} != {len(root_assets)})")
                else:
                    out_sig = sorted(json.dumps(a, sort_keys=True, ensure_ascii=False) for a in out_assets)
                    root_sig = sorted(json.dumps(a, sort_keys=True, ensure_ascii=False) for a in root_assets)
                    if out_sig != root_sig:
                        errors.append("outputs/asset-manifest.json 与根目录资产清单内容不一致（同名资产指纹/字段不同）")
        except Exception as exc:
            errors.append(f"outputs/asset-manifest.json 解析失败: {exc}")
    if args.mode != "demo":
        manifest_path = args.run_manifest or os.environ.get("TRAVEL_SCOPE_RUN_MANIFEST", "")
        provider_api_used = None
        if manifest_path and Path(manifest_path).is_file():
            try:
                provider_api_used = json.loads(Path(manifest_path).read_text(encoding="utf-8")).get("provider_api_used")
            except Exception:
                pass
        if provider_api_used is None:
            errors.append("Live 运行 manifest 必须明确 provider_api_used")
        elif provider_api_used is True and not args.cache_db:
            errors.append("Live 运行使用了供应商 API，但缺少 --cache-db 调用台账")
        elif provider_api_used is False and not args.cache_db:
            warnings.append("本次未使用需记账的供应商 API，API SQLite 台账不适用")
        _check_scope_evidence(
            manifest_path,
            args.scope_json,
            args.route_corridors,
            errors,
        )
        if not args.preflight:
            errors.append("Live 交付缺少 --preflight，未完成运行模式、分支、路线粒度和范围确认")
        else:
            preflight = Path(args.preflight)
            try:
                values = json.loads(preflight.read_text(encoding="utf-8"))
                required = {"mode", "branch", "map_mode", "route_granularity", "scope_review", "intake"}
                missing = sorted(required - set(values))
                if missing:
                    errors.append(f"前置 QA 缺少字段: {missing}")
                elif values.get("mode") not in {"1", "2"} or values.get("scope_review") not in {"1", "2"}:
                    errors.append("前置 QA 的运行模式或范围确认值无效")
            except Exception as exc:
                errors.append(f"前置 QA 文件无法读取: {exc}")
        evidence_paths = {
            "data": args.data,
            "asset_manifest": args.asset_manifest,
            "media_audit": args.media_audit,
            "visual_qa_report": args.visual_qa_report,
        }
        for label, value in evidence_paths.items():
            if not value or not Path(value).is_file():
                errors.append(f"Live 交付缺少 {label} 证据文件: {value}")
        if all(evidence_paths.values()) and all(Path(value).is_file() for value in evidence_paths.values()):
            manifest_file = Path(args.run_manifest or os.environ.get("TRAVEL_SCOPE_RUN_MANIFEST", ""))
            scope_file = Path(args.scope_json)
            corridor_file = Path(args.route_corridors)
            if manifest_file.is_file() and scope_file.is_file() and corridor_file.is_file():
                manifest_value = json.loads(manifest_file.read_text(encoding="utf-8"))
                expected_files = manifest_value.get("artifacts_expected") or []
                if isinstance(expected_files, list) and expected_files:
                    for exp in expected_files:
                        p = Path(exp)
                        if not p.is_absolute():
                            p = output / exp
                        if not p.is_file() or p.stat().st_size <= 0:
                            errors.append(f"运行 manifest 声明的期望交付物文件不存在或为空: {exp}")
                required_provenance = ("input_sha256", "product_fingerprint", "generation_command")
                missing_provenance = [field for field in required_provenance if not str(manifest_value.get(field, "")).strip()]
                if missing_provenance:
                    errors.append(f"运行 manifest 缺少生成溯源字段: {missing_provenance}")
                else:
                    actual_input_hash = hashlib.sha256(Path(args.data).read_bytes()).hexdigest()
                    if manifest_value["input_sha256"] != actual_input_hash:
                        errors.append("manifest input_sha256 与统一 dataset 不一致")

                    for seal_error in verify_seal(output.parent, manifest_value):
                        errors.append(f"输入封存校验: {seal_error}")
                    actual_product_hash = hashlib.sha256((script_dir.parent / "product-origin.json").read_bytes()).hexdigest()
                    if manifest_value["product_fingerprint"] != actual_product_hash:
                        errors.append("manifest product_fingerprint 与当前发布指纹不一致")
                result = audit_formal_data(
                    json.loads(Path(args.data).read_text(encoding="utf-8")),
                    manifest_value,
                    json.loads(scope_file.read_text(encoding="utf-8")),
                    json.loads(corridor_file.read_text(encoding="utf-8")),
                    json.loads(Path(args.asset_manifest).read_text(encoding="utf-8")),
                    base_dir=Path(args.data).parent,
                )
                # V5-A：delivery_gate 内部直接调 formal_data_gate.audit()，这份嵌套报告同样是
                # 「一次门禁结论」，必须盖章——否则上层 PASS 底下挂着一张无主报告（V0-L17 形态）。
                result = gate_producer.write_stamped_report(
                    output / "formal_data_gate.json", result, gate_role="formal_data_gate",
                    producing_code=list(FORMAL_PRODUCING_CODE),
                    producing_config=list(FORMAL_PRODUCING_CONFIG),
                    inputs=gate_producer.collect_inputs({
                        "data": args.data, "manifest": str(manifest_file),
                        "scope": str(scope_file), "corridors": str(corridor_file),
                        "asset_manifest": args.asset_manifest}))["report"]
                errors.extend(f"正式数据门禁: {error}" for error in result["errors"])
            try:
                data_value = json.loads(Path(args.data).read_text(encoding="utf-8"))
                media_root = Path(args.asset_manifest).resolve().parent
                categories = [('HOTELS', data_value.get('hotels', []), 8, 9), ('RESTAURANTS', data_value.get('restaurants', []), 8, 9),
                              ('CAFES', data_value.get('cafes', []), 8, 9), ('ATTRACTIONS', data_value.get('attractions', []), 7, 8),
                              ('DIVE_SITES', data_value.get('dive_sites', []), 7, 8)]
                validate_local_media(media_root, categories, require_complete=bool((data_value.get('image_collection') or {}).get('require_complete')))
                coverage = [(key, data_value.get(key, [])) for key in ('hotels', 'restaurants', 'cafes', 'attractions', 'dive_sites')]
                validate_section_media(media_root, data_value.get('section_media', []), coverage,
                                       require_complete=bool((data_value.get('image_collection') or {}).get('section_media_required')),
                                       editorial_media=data_value.get('editorial_media', []))
                # R3 裁 A：交付门也读同一份固化快照，不再当场回源（base_dir 给了就会按 run manifest
                # 的 source_verification_snapshot_path 解析，路径缺失/过期/摘要变化各自抛命名码）
                validate_source_identities(json.loads(Path(args.asset_manifest).read_text(encoding="utf-8")),
                                           base_dir=media_root)
            except Exception as exc:
                errors.append(f"媒体审计现场复算失败: {exc}")
            # v4.2.1 SS5: the raising validators above stop at the first bad asset, which is how
            # v4.2.0 shipped 14 stale digests behind a report that named one. These sweeps are
            # total, and they reconcile the bytes the reader actually receives.
            try:
                media_manifest = json.loads(Path(args.asset_manifest).read_text(encoding="utf-8"))
            except Exception as exc:
                media_manifest = {"assets": []}
                errors.append(f"图片清单无法读取，交付字节无法对账: {exc}")
            media_root = Path(args.asset_manifest).resolve().parent
            stale_rows = [row for row in asset_digest_sweep(media_manifest, media_root) if not row["matches_claim"]]
            for row in stale_rows:
                errors.append(
                    f"ASSET_DIGEST_STALE|图片摘要链断裂: {row['local_file']} 清单记录 "
                    f"{row['claimed_sha256'][:12] or '空'}… 与在盘字节 {(row['on_disk_sha256'] or '文件缺失')[:12]}… 不一致")
            for html_path in (p for p in (html_cn, html_en, html_bilingual, html_spa) if p):
                if not html_path.is_file():
                    continue
                img_errors, img_metrics = attest_delivered_images(
                    html_path.read_text(encoding="utf-8", errors="replace"), media_manifest, media_root)
                errors.extend(f"{html_path.name}: {e}" for e in img_errors)
                image_attestation[html_path.name] = img_metrics
            for label, value in (("媒体审计", args.media_audit), ("视觉 QA", args.visual_qa_report)):
                try:
                    report_value = json.loads(Path(value).read_text(encoding="utf-8"))
                    if report_value.get("status") != "PASS":
                        errors.append(f"{label}未通过: {report_value.get('status')}")
                    # V5-A：状态 PASS 之外还要问「这句 PASS 是谁说的」。没有产出者身份、
                    # 或者身份与现行代码/封条不符的报告，一律不得当作本次交付的证据（V0-L17）。
                    trusted = gate_producer.verify_report(report_value, script_dir.parent)
                    if trusted["trust"] != "TRUSTED":
                        errors.append(
                            f"{label}报告不可作证据（缺产出者身份或已与现行代码漂移）: "
                            + " | ".join(trusted["findings"][:4]))
                    if label == "媒体审计" and report_value.get("status") == "PASS":
                        expected_data = hashlib.sha256(Path(args.data).read_bytes()).hexdigest()
                        expected_assets = hashlib.sha256(Path(args.asset_manifest).read_bytes()).hexdigest()
                        if not report_value.get("data_sha256") or not report_value.get("asset_manifest_sha256") or report_value.get("data_sha256") != expected_data or report_value.get("asset_manifest_sha256") != expected_assets:
                            errors.append("媒体审计报告指纹缺失或与当前 dataset/asset-manifest 指纹不一致 (旧报告已过期，必须重新生成，严禁放行)")
                    if label == "视觉 QA" and report_value.get("status") == "PASS":
                        expected_html = {"cn": html_cn, "en": html_en, "bilingual": html_bilingual, "spa": html_spa}
                        actual_hashes = report_value.get("html_sha256") or {}
                        if not actual_hashes:
                            errors.append("视觉 QA 报告缺少 html_sha256 指纹记录")
                        stale = [edition for edition, path in expected_html.items() if path and actual_hashes.get(edition) != hashlib.sha256(path.read_bytes()).hexdigest()]
                        if stale:
                            errors.append(f"视觉 QA 报告与当前 HTML 指纹不一致 (旧报告已过期): {stale}")
                except Exception as exc:
                    errors.append(f"{label}报告无法读取: {exc}")
    if args.cache_db:
        report_script = script_dir / "usage_report.py"
        result = subprocess.run(pyc.interpreter([
            sys.executable, str(report_script), "--db", args.cache_db,
            "--daily-limit", str(args.daily_limit), "--monthly-limit", str(args.monthly_limit),
        ]), capture_output=True, text=True, encoding="utf-8", errors="replace",
            env=pyc.env())
        if result.returncode != 0:
            errors.append(f"API 调用报警门禁失败: {result.stdout.strip() or result.stderr.strip()}")

    # 浏览器视觉 QA（以及它导出的英文态可见文本）已经在 _scan_final_artifacts 之前跑过了，
    # 这里不再重跑：同一份产物跑两遍只会让报告里出现两个时间点，看不出谁是谁。
    version_path = script_dir.parent / "VERSION.md"
    readme_path = script_dir.parent / "README.md"
    if version_path.exists() and readme_path.exists():
        version_match = re.search(r"v(\d+\.\d+\.\d+)", version_path.read_text(encoding="utf-8"))
        readme_match = re.search(r"baseline: \*\*v(\d+\.\d+\.\d+)\*\*", readme_path.read_text(encoding="utf-8"))
        if not version_match or not readme_match or version_match.group(1) != readme_match.group(1):
            errors.append("VERSION.md 与 README 当前版本不一致")

    report = {
        "status": "PASS" if not errors else "FAIL",
        "output_dir": str(output),
        "artifacts": artifacts,
        "english_text_check": english_text_check,
        "image_attestation": image_attestation,
        "single_file_delivery": single_file_audit if single_file_audit is not None else {
            "status": "FAIL",
            "findings": ["SFD_ACCOUNTING_NOT_IN_REPORT|没有 *-travel-guide.html 读者产物，"
                         "单文件字节对账未执行（没跑不等于通过，§10）"],
            "blocking": ["SFD_ACCOUNTING_NOT_IN_REPORT|没有读者产物，字节对账未执行"],
            "advisory": [], "measured": {},
        },
        "warnings": warnings,
        "errors": errors,
    }
    report_path = Path(args.report) if args.report else output / "delivery-gate.json"
    gate_producer.write_stamped_report(
        report_path, report, gate_role="delivery_gate", producing_code=list(PRODUCING_CODE),
        producing_config=list(PRODUCING_CONFIG),
        inputs=gate_producer.collect_inputs({
            "data": args.data, "asset_manifest": args.asset_manifest,
            "media_audit": args.media_audit, "visual_qa_report": args.visual_qa_report,
            "run_manifest": args.run_manifest, "scope_json": args.scope_json,
            "route_corridors": args.route_corridors, "preflight": args.preflight,
            "formal_data_gate_report": str(output / "formal_data_gate.json")},
            only_existing=True))
    report = json.loads(report_path.read_text(encoding="utf-8"))
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if not errors else 2


if __name__ == "__main__":
    raise SystemExit(main())
