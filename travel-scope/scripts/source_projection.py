# -*- coding: utf-8 -*-
"""读者来源面板的唯一投影面（ZH-RELEASE-1 · #113）。

为什么要有这一支：交付物里的来源面板过去读的是 source_evidence（十列**位置**数组），
渲染器却按 source_evidence_meta 的**对象**字段取值 ⇒ 每格都是 undefined，
于是印出空白条目加「0 verified」的假统计；再加上 items.slice(0,15) 与「… N more」没有出口，
CA 174 条、PH 365 条来源记录在读者页面上根本不存在（静默丢记录）。

业主 2026-11-02 裁：阅读面改成 source_evidence_meta（自描述、两地形状一致、渲染器本来就读它），
并且「未识别形状必须阻断，而不是过滤」。所以本模块只做三件事：

1. **投影**：把机器面记录校验后原序投影成读者面记录（零丢弃、零改写文案）；
2. **闭集校验**：字段集／核验状态词表／证据等级词表全部来自 references/data-model.json，
   不在这里硬编码第二套；越出闭集就是 ProjectionError，绝不 continue；
3. **对账口径**：dataset → 投影 → DOM 三段数量必须逐项相等（reconcile()），
   旧的十列位置面不在阅读路径上，但它违反注册列序的事实由 legacy_positional_findings() 量出来登记。

生成器、formal_data_gate.py、visual_qa.py 与测试都 import 这里；判据只住一份。
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import re
from typing import Any

ROOT = pathlib.Path(__file__).resolve().parents[1]
DATA_MODEL = ROOT / "references" / "data-model.json"

# 机器面（source_evidence_meta）的**完整**字段集：多一个少一个都算没见过的形状。
REQUIRED_FIELDS = (
    "destination", "name", "url", "source_provider", "evidence_level",
    "verification_status", "retrieved_at", "cross_source_review", "notes",
)
DATE_RE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")
ERROR_CODES = (
    "row_not_object", "missing_field", "unexpected_field", "empty_field",
    "status_out_of_vocab", "level_out_of_vocab", "retrieved_at_not_date", "url_not_http",
    "empty_ledger", "status_label_unregistered", "level_label_unregistered",
    "legacy_row_not_list", "legacy_row_too_short", "legacy_id_not_string",
    "legacy_date_column_not_date", "registry_missing",
)

# ── 台账血缘自证（ZH-RELEASE-2 步1 · 业主 2026-11-03 裁 finding_1）────────────────
# 正式链必须是 input dataset source_evidence_meta → canonical_dataset → source_projection
# → source_records → DOM，**并核对输入 SHA**。渲染器与门都不造这一面：生成器按它实际读到的
# 输入字节写一份自证（面自身摘要＋输入文件摘要＋行数），下游只核对它。于是
# 「直调 render_spa_document()」那份产物拿不到输入字节 ⇒ 造不出自证 ⇒ 正式门判 ABSENT ⇒
# 它只剩 smoke 身份，而不是把 smoke 换成正式证据。自证的字段集是闭集：多一个少一个都算形状错。
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
PROVENANCE_FIELDS = ("dataset_rows", "input_sha256", "ledger_sha256")
PROVENANCE_CODES = (
    "provenance_absent", "provenance_not_object", "provenance_field_missing",
    "provenance_field_unexpected", "provenance_rows_mismatch",
    "provenance_input_sha_malformed", "provenance_digest_mismatch",
)


class ProjectionError(RuntimeError):
    """投影层的阻断异常：带**闭合错误码**，门禁据此断言「是哪一条规则咬住」而不是只看红。"""

    def __init__(self, code: str, detail: str, index: "int | None" = None):
        self.code, self.detail, self.index = code, detail, index
        where = "-" if index is None else "row[%d]" % index
        super().__init__("%s @ %s: %s" % (code, where, detail))


def registry(path: pathlib.Path = DATA_MODEL) -> dict:
    """读注册表；词表缺失即阻断（不许悄悄退回模块内置的一份）。"""
    model = json.loads(path.read_bytes().decode("utf-8"))
    for key in ("source_evidence_levels", "source_verification_statuses",
                "source_verification_status_labels", "source_evidence_columns"):
        if key not in model:
            raise ProjectionError("registry_missing",
                                  "references/data-model.json 缺少 %s（词表唯一持有者）" % key)
    statuses = tuple(model["source_verification_statuses"])
    labels = model["source_verification_status_labels"]
    missing = [s for s in statuses if s not in labels]
    if missing:
        raise ProjectionError("status_label_unregistered",
                              "这些核验状态没有中文显示名：%s" % missing)
    levels = tuple(model["source_evidence_levels"])
    level_labels = model.get("source_evidence_level_labels") or {}
    missing_levels = [l for l in levels if l not in level_labels]
    if missing_levels:
        raise ProjectionError("level_label_unregistered",
                              "这些证据等级没有中文显示名（机器词表不许直接印给读者）：%s" % missing_levels)
    return {"levels": levels, "statuses": statuses,
            "labels": labels, "level_labels": level_labels,
            "columns": tuple(model["source_evidence_columns"])}


def _check(item: Any, index: int, reg: dict) -> dict:
    if not isinstance(item, dict):
        raise ProjectionError("row_not_object",
                              "阅读面要求对象记录（自描述字段），收到 %s" % type(item).__name__, index)
    missing = [k for k in REQUIRED_FIELDS if k not in item]
    if missing:
        raise ProjectionError("missing_field", "缺字段 %s" % missing, index)
    extra = sorted(set(item) - set(REQUIRED_FIELDS))
    if extra:
        raise ProjectionError("unexpected_field",
                              "多出未注册的字段 %s；加字段要先改 data-model.json 再改这里" % extra, index)
    status = str(item["verification_status"])
    if status not in reg["statuses"]:
        raise ProjectionError("status_out_of_vocab",
                              "核验状态 %r 不在闭集 %s" % (status, list(reg["statuses"])), index)
    level = str(item["evidence_level"])
    if level not in reg["levels"]:
        raise ProjectionError("level_out_of_vocab",
                              "证据等级 %r 不在闭集 %s" % (level, list(reg["levels"])), index)
    retrieved = str(item["retrieved_at"])
    if not DATE_RE.match(retrieved):
        raise ProjectionError("retrieved_at_not_date", "核验日期 %r 不是 YYYY-MM-DD" % retrieved, index)
    url = str(item["url"])
    if not url.startswith(("http://", "https://")):
        raise ProjectionError("url_not_http", "来源 URL 不是 http(s)：%r" % url[:60], index)
    for key in ("destination", "name", "source_provider"):
        if not str(item[key]).strip():
            raise ProjectionError("empty_field", "%s 为空" % key, index)
    return {"row_index": index,
            "row_uid": hashlib.sha256(
                ("%s|%s|%s" % (item["destination"], item["name"], url)).encode("utf-8")).hexdigest()[:12],
            "destination": str(item["destination"]), "name": str(item["name"]), "url": url,
            "source_provider": str(item["source_provider"]), "evidence_level": level,
            "evidence_level_label": reg["level_labels"][level],
            "verification_status": status, "verification_label": reg["labels"][status],
            "retrieved_at": retrieved,
            "cross_source_review": str(item["cross_source_review"]), "notes": str(item["notes"])}


def project(records, *, reg: "dict | None" = None) -> list:
    """机器面 → 读者面：原序、零丢弃；任何一条不认识的形状就整面阻断。"""
    reg = reg or registry()
    rows = list(records or [])
    if not rows:
        raise ProjectionError("empty_ledger", "source_evidence_meta 为空 ⇒ 读者页没有来源可发")
    return [_check(item, i, reg) for i, item in enumerate(rows)]


def counts(rows) -> dict:
    out = {"total": len(rows), "by_status": {}, "by_provider": {}, "by_level": {}}
    for r in rows:
        for bucket, key in (("by_status", "verification_status"),
                            ("by_provider", "source_provider"), ("by_level", "evidence_level")):
            token = str(r[key])
            out[bucket][token] = out[bucket].get(token, 0) + 1
    return out


def ledger_digest(rows) -> str:
    """机器面（source_evidence_meta 列表）自身的摘要：**口径只在这里定义一次**。

    生成器按它实际读到的行序写这个值，渲染器与门各自复算再比——所以「来源台账在装配后被改动」
    是量得出来的，不是靠人记得看。逐字段排序、键名排序、紧凑分隔符，跨平台稳定。
    """
    canon = json.dumps(list(rows or []), ensure_ascii=False, sort_keys=True,
                       separators=(",", ":"))
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()


def build_provenance(rows, input_sha256: str) -> dict:
    """正式生成链的血缘自证：生成器只准用它**实际读到的那份输入字节**来调这里。

    业主 2026-11-03 裁：不得从十列位置面重新推导，也不得缺失时回退空列表。因此这一支
    在没有输入摘要时直接抛码（provenance_input_sha_malformed），而不是写一个空串占位。
    """
    sha = str(input_sha256 or "")
    if not SHA256_RE.match(sha):
        raise ProjectionError("provenance_input_sha_malformed",
                              "输入 dataset 的 SHA-256 不是 64 位十六进制（实测 %r）："
                              "自证指不到具体字节，正式构建不得带着这种账出货" % sha[:24])
    return {"dataset_rows": len(list(rows or [])), "input_sha256": sha,
            "ledger_sha256": ledger_digest(rows)}


def provenance_problems(block, rows) -> list:
    """核对「产物自证的那张面」⇄「现在手上这张面」，返回 [(code, detail)]，空＝合。

    判定住在门（delivery_gate），测量住在这里；渲染器只在正式构建里拿它当阻断依据。
    """
    if block is None:
        return [("provenance_absent",
                 "读者载荷没有 source_ledger_meta 自证块：这一件不是从正式生成链装配出来的"
                 "（直调 render_spa_document() 拿不到输入字节），按合同只算 smoke，"
                 "不得作为中文正式交付证据")]
    if not isinstance(block, dict):
        return [("provenance_not_object",
                 "source_ledger_meta 必须是对象，收到 %s" % type(block).__name__)]
    problems = []
    missing = [key for key in PROVENANCE_FIELDS if key not in block]
    extra = sorted(set(block) - set(PROVENANCE_FIELDS))
    if missing:
        problems.append(("provenance_field_missing",
                         "自证缺字段 %s（注册字段闭集 %s）" % (missing, list(PROVENANCE_FIELDS))))
    if extra:
        problems.append(("provenance_field_unexpected",
                         "自证多出未注册字段 %s；加字段要先改合同再改这里" % extra))
    if missing:
        return problems
    rows = list(rows or [])
    try:
        declared_rows = int(block.get("dataset_rows"))
    except (TypeError, ValueError):
        problems.append(("provenance_rows_mismatch",
                         "dataset_rows 不是整数（实测 %r）" % (block.get("dataset_rows"),)))
        return problems
    if declared_rows != len(rows):
        problems.append(("provenance_rows_mismatch",
                         "自证记 dataset_rows=%d，现在这张机器面是 %d 行：来源台账在装配后被改动或"
                         "自证指的不是这一面" % (declared_rows, len(rows))))
    sha = str(block.get("input_sha256") or "")
    if not SHA256_RE.match(sha):
        problems.append(("provenance_input_sha_malformed",
                         "input_sha256 %r 不是 64 位小写十六进制" % sha[:24]))
    want = ledger_digest(rows)
    if str(block.get("ledger_sha256") or "") != want:
        problems.append(("provenance_digest_mismatch",
                         "ledger_sha256=%r 与按现面复算的 %s 不符（口径 source_projection.ledger_digest）"
                         % (str(block.get("ledger_sha256"))[:12], want[:12])))
    return problems


def reconcile(*, dataset_rows: int, projected_rows: int, dom_rows: int,
              status_bucket_total: "int | None" = None) -> dict:
    """dataset → 投影 → DOM 三段数量逐项相等；不等就是丢记录。"""
    problems = []
    if not (dataset_rows == projected_rows == dom_rows):
        problems.append("count_drift:dataset=%s projected=%s dom=%s"
                        % (dataset_rows, projected_rows, dom_rows))
    if status_bucket_total is not None and status_bucket_total != projected_rows:
        problems.append("status_bucket_sum_mismatch:%s!=%s" % (status_bucket_total, projected_rows))
    return {"ok": not problems, "problems": problems,
            "numbers": {"dataset": dataset_rows, "projected": projected_rows, "dom": dom_rows}}


def legacy_positional_findings(rows, *, reg: "dict | None" = None) -> dict:
    """十列位置面的形状清点（不在阅读路径上，但违反注册列序必须被量出来，不许静默）。

    注册列序来自 data-model.json::source_evidence_columns；这里只出清册与计数，
    不改数据、不修列序——那是英文路由（MT-D2-A 别名表）那一遍的活。
    """
    reg = reg or registry()
    columns = list(reg["columns"])
    out = {"registered_columns": columns, "rows": 0,
           "by_code": {"legacy_row_not_list": 0, "legacy_row_too_short": 0,
                       "legacy_id_not_string": 0, "legacy_date_column_not_date": 0},
           "examples": []}
    id_col = columns.index("evidence_id") if "evidence_id" in columns else 0
    date_col = columns.index("retrieved_at") if "retrieved_at" in columns else 5
    for i, row in enumerate(rows or []):
        out["rows"] += 1
        codes = []
        if not isinstance(row, list):
            codes.append("legacy_row_not_list")
        elif len(row) < len(columns):
            codes.append("legacy_row_too_short")
        else:
            if not isinstance(row[id_col], str):
                codes.append("legacy_id_not_string")
            if not DATE_RE.match(str(row[date_col])):
                codes.append("legacy_date_column_not_date")
        for code in codes:
            out["by_code"][code] += 1
        if codes and len(out["examples"]) < 5:
            out["examples"].append({"row_index": i, "codes": codes,
                                    "row": ([str(c)[:40] for c in row] if isinstance(row, list)
                                            else repr(row)[:80])})
    out["clean"] = not any(out["by_code"].values())
    return out
