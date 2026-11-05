# -*- coding: utf-8 -*-
"""正式读者载荷的语言范围投影（ZH-RELEASE-1 · 业主 P0-1）。

业主指出的缺陷很具体：只 pop 顶层 `excluded_payload_keys` 证明不了嵌套英文消失了。实测加州
zh-formal 载荷里嵌套 EN 形状键共 **300 处**（口径＝剔候审面**之前**；现行顺序**之后**实测加州 292／
菲律宾 254，两个数都登记在 references/renderer-contract.json::payload_scope.authority，不许混用）。
构成：`map_targets.*.names.en` 205 处、`editorial_media[*].caption_en` 36 处、`title_en` 16 处、
`limitations_en` 14 处、`name_en` 14 处、`use_cases_en` 14 处、`en_note` 1 处。所以这一支做三件事：

1. **顶层允许清单**（合同 `payload_scope.top_level_allowlist`）：没登记过的顶层键直接阻断构建，
   于是「换一个未登记字段名把候审英文带进成品」这条路是被堵死的，不是靠我记得加黑名单；
2. **递归英文形状剥离并登记**：任何深度上命中 `nested_en_patterns` 的键一律剔除，并把命中路径与
   计数写进报告（合同要求保留全部记录的读者面走 source_projection，那边是零丢弃；这里是反向：
   正式读者面零英文显示面）；
3. **档位自证**：正式档载荷必须带 `reader_language_scope = "zh_only"`，门禁据此决定跑哪套检查，
   而不是靠构建参数或文件名猜。

判据只住这里；渲染器、门禁、测试都 import 本模块。
"""
from __future__ import annotations

import json
import pathlib
import re
from typing import Any

ROOT = pathlib.Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "references" / "renderer-contract.json"
DATA_MODEL = ROOT / "references" / "data-model.json"

# 命中即视为「英文显示面」的键形状；刻意保守：宁可多剥一处并登记，也不留一处未证明的嵌套英文。
NESTED_EN_PATTERNS = (r"^en$", r"^en_", r"_en$", r"^en\.", r".*english.*")
SCOPE_VALUE = "zh_only"
ERROR_CODES = ("scope_contract_missing", "scope_allowlist_missing",
               "scope_payload_key_unregistered", "scope_profile_mismatch",
               "scope_en_key_left_in_payload", "scope_numeric_value_key_stripped",
               "scope_exempt_value_rejected", "scope_exempt_path_shape_unregistered")
# 豁免位支持的取值检查；每一项的规则来源都指向一处既有登记，不在这里另立标准。
VALUE_CHECKS = ("nonempty_string", "no_cjk", "names_schema")


class ScopeError(RuntimeError):
    def __init__(self, code: str, detail: str, path: "str | None" = None):
        self.code, self.detail, self.path = code, detail, path
        super().__init__("%s @ %s: %s" % (code, path or "-", detail))


def scope_contract(path: pathlib.Path = CONTRACT) -> dict:
    block = json.loads(path.read_bytes().decode("utf-8")).get("reader_language")
    if not isinstance(block, dict):
        raise ScopeError("scope_contract_missing", "renderer-contract.json 没有 reader_language 块")
    return block


def profile_scope(profile: str) -> dict:
    block = scope_contract()
    spec = (block.get("profiles") or {}).get(profile)
    if spec is None:
        raise ScopeError("scope_profile_mismatch", "未登记的读者档位 %r" % profile)
    return spec.get("payload_scope") or {}


def _require_scope(profile: str) -> dict:
    scope = profile_scope(profile)
    if not scope.get("top_level_allowlist"):
        raise ScopeError("scope_allowlist_missing",
                         "正式档位 %r 没有登记 payload_scope.top_level_allowlist ⇒ 无法证明载荷干净" % profile)
    return scope


def names_schema(path: pathlib.Path = DATA_MODEL) -> dict:
    """`names` 的既有结构冻结（§17 W1R）：唯一登记处 references/data-model.json::names_schema。

    输入侧的执行住在 scripts/data_model.py（NAMES_KEY_MISSING／NAMES_KEY_UNKNOWN／
    NAMES_VALUE_INVALID／NAMES_EN_NOT_LATIN）；这里做的是**出货面复检**——豁免掉的机读面
    在离开构建器之前必须仍然满足同一张 schema，而不是「因为要豁免所以不检查」。
    """
    model = json.loads(path.read_bytes().decode("utf-8"))
    schema = model.get("names_schema")
    if not isinstance(schema, dict) or "en" not in (schema.get("required") or []):
        raise ScopeError("scope_exempt_value_rejected",
                         "references/data-model.json::names_schema 没有把 en 登记为必填结构，"
                         "机读豁免失去判据来源")
    return schema


def _compile_exemptions(entries) -> list:
    """把登记项编译成匹配用的形状；形状不合法或检查项没实现 ⇒ 直接抛码，不降级成「没有豁免」。"""
    out = []
    for entry in entries or []:
        segments = entry.get("path_segments") if isinstance(entry, dict) else None
        if not isinstance(segments, list) or not segments or not all(isinstance(s, str) and s for s in segments):
            raise ScopeError("scope_exempt_path_shape_unregistered",
                             "机读豁免项的 path_segments 必须是若干非空字符串段（登记值=%r）："
                             "豁免位没有精确路径就等于全局放行，本门不许这种形状" % (segments,))
        # 精确性还要能机械判定（业主 2026-11-03 裁②：「只豁免精确路径，不得全局放行键名 en」）：
        # 首段是通配 ⇒ 任何顶层面都能挂上来；末段是通配 ⇒ 就是按键名放行；
        # 字面段少于 2 ⇒ 没有父路径锚点。三种都不是「精确路径」，一律阻断而不是放行。
        literal = [s for s in segments if s != "*"]
        if segments[0] == "*" or segments[-1] == "*" or len(literal) < 2:
            raise ScopeError("scope_exempt_path_shape_unregistered",
                             "机读豁免项的段序列 %r 不够精确（首段或末段是通配，或字面段少于 2 个）："
                             "这种形状等于按父路径或键名全局放行，裁②明令禁止" % (segments,))
        checks = list(entry.get("value_checks") or [])
        unknown = sorted(set(checks) - set(VALUE_CHECKS))
        if unknown:
            raise ScopeError("scope_exempt_path_shape_unregistered",
                             "机读豁免项登记了没有实现的取值检查 %s（可实现的是 %s）"
                             % (unknown, list(VALUE_CHECKS)))
        out.append({"segments": [str(s) for s in segments],
                    "value_checks": checks,
                    "authority": str(entry.get("authority") or ""),
                    "shape": "$." + ".".join(str(s) for s in segments)})
    return out


def _exemptions_from_block(block: dict, profile: str) -> list:
    spec = (block.get("profiles") or {}).get(profile) or {}
    return _compile_exemptions((spec.get("payload_scope") or {}).get("machine_readable_exempt_paths"))


def machine_readable_exempt_paths(profile: str) -> list:
    """合同登记的「机读面精确路径豁免」清单（业主 2026-11-03 裁②）。

    只登记**完整段序列**，例如 `["map_targets", "*", "names", "en"]`：`*` 只许匹配恰好一段
    （map_targets 的直接子键＝目标名），结构段一律逐字相等。因此键名 en、`names.en`、
    任何 `*_en` 都不会被全局放行——换一个父路径就命中不了这条模式，照旧剥离。
    清单为空＝没有任何豁免（保守默认，不在代码里硬编码豁免位）。
    """
    return _exemptions_from_block(scope_contract(), profile)


def _match_exempt(pattern_segments, actual_segments) -> bool:
    """段序列精确匹配：长度必须相等，`*` 只吃掉一段。"""
    if len(pattern_segments) != len(actual_segments):
        return False
    return all(pat == "*" or pat == act for pat, act in zip(pattern_segments, actual_segments))


def _check_exempt_value(shape: str, parent, key, value, checks) -> None:
    """豁免不等于免检：值必须仍是非空字符串、不含汉字，并符合既有 names_schema。"""
    try:
        from data_model import CJK_RE
    except ImportError:  # pragma: no cover
        from scripts.data_model import CJK_RE  # type: ignore
    if "nonempty_string" in checks:
        if not isinstance(value, str) or not value.strip():
            raise ScopeError("scope_exempt_value_rejected",
                             "机读豁免位 %s 的值不是非空字符串（实测 %r）：豁免只覆盖形状，"
                             "不给空值或非标量开门" % (shape, value), path=shape)
    if "no_cjk" in checks and isinstance(value, str) and CJK_RE.search(value):
        raise ScopeError("scope_exempt_value_rejected",
                         "机读豁免位 %s 的值含中日韩字符（%r）：这一面是构造 URL 的拉丁名输入，"
                         "含汉字说明它不是机读标识而是把中文塞进英文面（NAMES_EN_NOT_LATIN 同源规则）"
                         % (shape, value[:40]), path=shape)
    if "names_schema" in checks:
        schema = names_schema()
        allowed = set(schema.get("allowed") or [])
        required = set(schema.get("required") or [])
        if not isinstance(parent, dict):
            raise ScopeError("scope_exempt_value_rejected",
                             "机读豁免位 %s 的父节点不是对象，无法按 names_schema 校验" % shape, path=shape)
        absent = sorted(required - set(parent))
        if absent:
            raise ScopeError("scope_exempt_value_rejected",
                             "机读豁免位 %s 所在的 names 缺必填键 %s（schema=%s）"
                             % (shape, absent, sorted(required)), path=shape)
        unknown = sorted(set(parent) - allowed)
        if unknown:
            raise ScopeError("scope_exempt_value_rejected",
                             "机读豁免位 %s 所在的 names 含冻结结构之外的键 %s（allowed=%s）"
                             % (shape, unknown, sorted(allowed)), path=shape)
        if schema.get("en_must_be_latin") and str(key) == "en" and isinstance(value, str) \
                and CJK_RE.search(value):
            raise ScopeError("scope_exempt_value_rejected",
                             "机读豁免位 %s 违反 names_schema.en_must_be_latin（§17 W1R 冻结："
                             "en 是构造 URL 的唯一来源）" % shape, path=shape)
        if key not in allowed:
            raise ScopeError("scope_exempt_value_rejected",
                             "机读豁免位 %s 的键名不在 names_schema.allowed %s 里：豁免路径上的字段"
                             "必须是 schema 认识的那一个" % (shape, sorted(allowed)), path=shape)


def _strip_en(node: Any, trail: str, patterns, hits: "dict[str, int]",
              examples: "dict[str, str]", segments: "tuple[str, ...]" = (),
              exempt: "list[dict] | None" = None,
              kept: "dict[str, int] | None" = None) -> Any:
    """递归剥掉命中 EN 形状的键；命中处登记路径与计数，不静默。

    两个例外都是业主实测后点名登记的，不是实现者自己扩的：
      * **数字值的命中键**（`scope_numeric_value_key_stripped`）：那是标识或统计维度
        （如 `source_counts.by_provider["en.wikivoyage.org"] = 188`），删它＝删记录；
      * **合同登记的机读面精确路径**（`machine_readable_exempt_paths`，业主 2026-11-03 裁②＝
        标识／URL 构造输入）：命中段序列完全等于登记形状时保留，但值必须继续通过
        nonempty_string／no_cjk／names_schema 三项复检，并计数登记在
        `machine_readable_kept` 里——保留是有账的保留，不是悄悄放行。
    """
    exempt = exempt or []
    kept_acc = {} if kept is None else kept
    if isinstance(node, dict):
        result = {}
        for key, value in node.items():
            token = str(key)
            if any(re.search(pattern, token, re.I) for pattern in patterns):
                shape = "%s.%s" % (_collapse(trail), token)
                actual = segments + (token,)
                matched = next((entry for entry in exempt
                                if _match_exempt(entry["segments"], actual)), None)
                if matched is not None:
                    _check_exempt_value(matched["shape"], node, key, value, matched["value_checks"])
                    kept_acc[matched["shape"]] = kept_acc.get(matched["shape"], 0) + 1
                    result[key] = value
                    continue
                if isinstance(value, (int, float, bool)) and not isinstance(value, str):
                    raise ScopeError(
                        "scope_numeric_value_key_stripped",
                        "EN 形状键 %s 的值是数字（%r）：那是标识/统计维度而不是英文显示面，"
                        "静默剥离＝丢记录；这一面要不要出货必须回合同登记" % (shape, value),
                        path=shape)
                hits[shape] = hits.get(shape, 0) + 1
                examples.setdefault(shape, "%s.%s=%s" % (_collapse(trail), token, json.dumps(
                    value, ensure_ascii=False)[:60]))
                continue
            result[key] = _strip_en(value, "%s.%s" % (trail, key), patterns, hits, examples,
                                    segments + (token,), exempt, kept_acc)
        return result
    if isinstance(node, list):
        return [_strip_en(v, "%s[*]" % trail, patterns, hits, examples,
                          segments + ("[*]",), exempt, kept_acc) for v in node]
    return node


def _scan_en(node: Any, trail: str = "$", patterns=None, segments: "tuple[str, ...]" = (),
             exempt: "list[dict] | None" = None) -> "list[str]":
    """残留自检：与 _strip_en 用同一张豁免清单，否则剥离留下的机读面会被自己判成残留。"""
    patterns = list(patterns or NESTED_EN_PATTERNS)
    exempt = exempt or []
    out = []
    if isinstance(node, dict):
        for key, value in node.items():
            token = str(key)
            actual = segments + (token,)
            hit = any(re.search(p, token, re.I) for p in patterns)
            if hit and not any(_match_exempt(entry["segments"], actual) for entry in exempt):
                out.append("%s.%s" % (trail, token))
            out.extend(_scan_en(value, "%s.%s" % (trail, token), patterns,
                                segments + (token,), exempt))
    elif isinstance(node, list):
        for value in node:
            out.extend(_scan_en(value, "%s[*]" % trail, patterns,
                                segments + ("[*]",), exempt))
    return out


def _collapse(trail: str) -> str:
    """把 `$.map_targets.圣塔芭芭拉|Best Western….names` 里的具体实体名折成 `*`，
    报告才不会被 205 个地名淹掉；折叠只动动态键，结构段一个不少。"""
    parts = trail.split(".")
    out = [parts[0]]
    for part in parts[1:]:
        out.append(part.split("|")[0] + "|*" if "|" in part else part)
    return ".".join(out)


def _shape_of_key(trail: str) -> str:  # 兼容旧调用名；实现只有 _collapse 一份
    return _collapse(trail)


def project_reader_payload(data: dict, profile: str, *, formal_profile: str) -> "tuple[dict, dict]":
    """返回 (可以给读者的载荷, 登记报告)。

    正式档：顶层允许清单（未登记即阻断）＋任意深度 EN 形状剥离并登记＋残留自检。
    审计档（en-audit）：不裁剪——它的存在意义就是把英文面交给真渲染探针，报告里如实记 enforced=False。
    """
    block = scope_contract()
    is_formal = profile == block.get("formal_profile") == formal_profile
    patterns = list((profile_scope(profile) or {}).get("nested_en_patterns") or NESTED_EN_PATTERNS)
    allow = []
    dropped, unregistered = [], []
    exempt = []
    if is_formal:
        allow = _require_scope(profile)["top_level_allowlist"]
        exempt = _exemptions_from_block(block, profile)
        for key in list(data):
            if key not in allow:
                if key in (profile_scope(profile).get("excluded_top_level") or []):
                    data.pop(key, None)
                    dropped.append(key)
                else:
                    unregistered.append(key)
        if unregistered:
            raise ScopeError("scope_payload_key_unregistered",
                             "顶层键没有登记，无法判断它是否夹带候审英文：%s" % sorted(unregistered)[:8],
                             path="$")
    hits: dict = {}
    examples: dict = {}
    kept: dict = {}
    cleaned = _strip_en(data, "$", patterns, hits, examples, (), exempt, kept) if is_formal else dict(data)
    if is_formal:
        leftover = _scan_en(cleaned, patterns=patterns, exempt=exempt)
        if leftover:
            raise ScopeError("scope_en_key_left_in_payload",
                             "剥离后仍残留英文形状键：%s" % leftover[:6], path=leftover[0])
        cleaned["reader_language_scope"] = SCOPE_VALUE
    report = {"profile": profile, "enforced": is_formal,
              "scope_value": (SCOPE_VALUE if is_formal else None),
              "patterns_used": patterns,
              "allowlist_size": len(allow),
              "top_level_dropped_registered": sorted(dropped),
              "top_level_unregistered": sorted(unregistered),
              "nested_en_stripped": {k: v for k, v in sorted(hits.items(), key=lambda x: -x[1])},
              "nested_en_total": sum(hits.values()),
              "nested_en_examples": examples,
              "machine_readable_exempt_shapes": [entry["shape"] for entry in exempt],
              "machine_readable_kept": {k: v for k, v in sorted(kept.items(), key=lambda x: -x[1])},
              "machine_readable_kept_total": sum(kept.values()),
              "keys_after": len(cleaned)}
    return cleaned, report


def assert_scope_declared(payload: dict, profile: str, *, contract_block: "dict | None" = None) -> dict:
    """门禁侧的反向核对：产物自己声称的范围必须与档位一致（防止「声明 zh_only 却带英文」）。"""
    block = contract_block or scope_contract()
    formal = block.get("formal_profile")
    declared = payload.get("reader_language_scope")
    patterns = list((profile_scope(profile) or {}).get("nested_en_patterns") or NESTED_EN_PATTERNS)
    problems = []
    exempt: list = []
    if profile == formal:
        if declared != SCOPE_VALUE:
            problems.append("scope_not_declared:%r" % declared)
        # 反向核对读**同一份登记**：门里不另立第二张豁免名单。合同里删掉那条精确路径，
        # 这一面立刻重新算作残留（并回到「未登记形状就阻断」的保守默认），而不是靠代码记住它。
        exempt = _exemptions_from_block(block, profile)
        leftover = _scan_en(payload, patterns=patterns, exempt=exempt)
        if leftover:
            problems.append("nested_en_present:%d 处，例如 %s" % (len(leftover), leftover[0]))
        allow = _require_scope(formal)["top_level_allowlist"]
        surprise = sorted(set(payload) - set(allow))
        if surprise:
            problems.append("top_level_unregistered:%s" % surprise[:8])
    return {"ok": not problems, "problems": problems, "profile": profile,
            "declared_scope": declared, "formal_profile": formal,
            "machine_readable_exempt_shapes": [entry["shape"] for entry in exempt]}
