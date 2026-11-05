# -*- coding: utf-8 -*-
"""MT-B3：display-only 专名通道——英文页上的名字只有两档，都不升级身份。

为什么需要这一步（实测，不是推测）：英文页的缺口账上有两类字符串，用 prose 翻译表去接是错的：
  · `老渔人码头吉罗伊海鲜` —— 同一行第 3 格就写着 `Old Fishermans Grotto`，
    但渲染层的实体名索引只吃 map_targets 与 destinations/routes/destination_coverage 三种对，
    POI 行与配图标题行从来没进过任何对索引 → 有英文来源却显示 (translation pending)；
  · `圣西蒙 (大苏尔1号公路)`、`薄荷岛巧克力山` —— 数据里没有官方英文。业主 2026-10-31 明确：
    这类只能当**显示专名**（写明来源的机器翻译/音译），不许靠类别词根拼出来冒充权威英文名，
    更不许喂进 canonical identity、地图查询、evidence 或 VERIFIED 结论。

所以这个模块只干两件事：把 tier1 已经存在的名字对**接回**渲染路径（不是翻译），
以及把 tier2 的机器翻译显示名**在有结构化 provenance 的前提下**放进显示面（缺一条就整条不进）。
列清单、档位语义、禁升级面、provenance 必填字段全部住在
`references/display-name-channel.json`，本模块不复制第二份。
"""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CHANNEL_PATH = ROOT / "references" / "display-name-channel.json"
CJK_RE = re.compile(r"[\u4e00-\u9fff]")


def channel() -> dict:
    return json.loads(CHANNEL_PATH.read_text(encoding="utf-8"))


def provenance_fields() -> list[str]:
    tiers = channel()["tiers"]["tier2_machine_translated_display_name"]
    return list(tiers["provenance_required_fields"])


def forbidden_targets() -> list[str]:
    return list(channel()["no_upgrade"]["forbidden_targets"])


def _usable_english(value) -> str:
    """英文格必须真的是一条英文：空、纯空白、还带汉字的都不算来源。"""
    text = str(value or "").strip()
    if not text or CJK_RE.search(text):
        return ""
    return text


def _cell(row, index_key: str, field_key: str):
    """list 行按登记的 index 取，dict 行按登记的 field 取（两棵候选的载荷形状本来就不同）。"""
    if isinstance(row, dict):
        return row.get(field_key) if field_key else None
    if isinstance(row, (list, tuple)) and index_key is not None:
        try:
            idx = int(index_key)
        except (TypeError, ValueError):
            return None
        return row[idx] if len(row) > idx else None
    return None


def name_columns() -> dict:
    """显示面认领的**列**：(dataset, 中文侧的 index 或 field) → 该列的角色。

    包含两类：pair_columns 的中文侧（同行有英文格）与 name_only_columns（只有中文名，
    必须等 tier2 的显式来源）。判定面用这个回答「这一格归谁」，
    而不是「这一格现在有没有英文」——后者会把该由显示面负责的名字错记成无人认领的列。
    """
    out: dict = {}
    for col in channel()["pair_columns"]:
        key = col.get("cn_field") if col.get("cn_field") is not None else col.get("cn_index")
        out[(str(col["dataset"]), key)] = col.get("role", "")
    for col in channel().get("name_only_columns") or []:
        key = col.get("field") if col.get("field") is not None else col.get("index")
        out[(str(col["dataset"]), key)] = col.get("role", "")
    return out


def read_pairs(dataset: dict) -> tuple[dict, list[dict]]:
    """tier1：从登记列里读 [中文, 英文] 名对。撞名不选边，两边一起剔出并登记。"""
    pairs: dict[str, dict] = {}
    provenance_seen: dict[str, list[str]] = {}
    for col in channel()["pair_columns"]:
        rows = dataset.get(str(col["dataset"])) or []
        for position, row in enumerate(rows):
            cn = str(_cell(row, col.get("cn_index"), col.get("cn_field")) or "").strip()
            en = _usable_english(_cell(row, col.get("en_index"), col.get("en_field")))
            if not cn or not en or not CJK_RE.search(cn):
                continue
            slot = col.get("cn_field") or col.get("cn_index")
            address = "%s[%d][%s]" % (col["dataset"], position, slot)
            known = pairs.get(cn)
            if known and known["english"] != en:
                provenance_seen.setdefault(cn, [known["english"]]).append(en)
                pairs.pop(cn, None)      # 撞名：谁都不许用，等人工裁决
                continue
            pairs.setdefault(cn, {"english": en, "tier": "tier1_dataset_pair",
                                  "address": address, "column_role": col.get("role", "")})
    conflicts = [{"cn": cn, "englishes": sorted(set(values)),
                  "rule": "collision_rule"} for cn, values in sorted(provenance_seen.items())]
    return pairs, conflicts


def validate_provenance(entry, cn: str) -> tuple[bool, list[str]]:
    """tier2 的门槛：provenance 必须是**结构化对象**且登记字段一条不缺。

    字符串占位值（例如 "provenance": "machine translation"）一律判不合格——业主 MT-1 第 3 条
    针对的就是这种「看着像有来源、其实没法复算」的写法。
    """
    required = provenance_fields()
    if entry is None:
        return False, ["missing_provenance_object"]
    if not isinstance(entry, dict):
        return False, ["provenance_not_object:%r" % (type(entry).__name__,)]
    missing = [field for field in required if not str(entry.get(field) or "").strip()]
    placeholder = [field for field in required
                   if field in entry and re.fullmatch(r"(?i)(tbd|todo|n/?a|待定|占位|xxx)",
                                                      str(entry.get(field) or "").strip())]
    reasons = []
    if missing:
        reasons.append("missing_fields:%s" % ",".join(missing))
    if placeholder:
        reasons.append("placeholder_fields:%s" % ",".join(placeholder))
    return (not reasons), reasons


def read_machine_display_names(dataset: dict) -> tuple[dict, list[dict]]:
    """tier2：只放行 provenance 完整的显示名；不合格的整条不进显示面并登记原因。"""
    table = dataset.get("machine_translated_display_name") or {}
    provenance = dataset.get("display_name_provenance") or {}
    usable: dict[str, dict] = {}
    rejected: list[dict] = []
    for cn, english in table.items():
        key = str(cn or "").strip()
        value = _usable_english(english)
        entry = provenance.get(key)
        ok, reasons = validate_provenance(entry, key)
        if not value:
            rejected.append({"cn": key, "reasons": ["english_not_displayable"]})
            continue
        if not ok:
            rejected.append({"cn": key, "reasons": reasons})
            continue
        usable[key] = {"english": value, "tier": "tier2_machine_translated_display_name",
                       "review_status": str(entry.get("review_status")),
                       "glossary_version": str(entry.get("glossary_version"))}
    return usable, sorted(rejected, key=lambda item: item["cn"])


def annotate_dataset(dataset: dict) -> dict:
    """把两档结果写进载荷，并留下「谁被剔出、为什么」的账。

    关键一步：tier2 的原始表**不直接进载荷**。provenance 不合格的条目在这里被过滤掉，
    读者页只拿到通过校验的那部分，其余留在 display_name_rejected 上。渲染层无法自己判断
    provenance（它没有必填字段清单），所以 fail-closed 必须发生在构建期。
    """
    pairs, conflicts = read_pairs(dataset)
    machine, rejected = read_machine_display_names(dataset)
    dataset["name_pairs"] = {cn: item["english"] for cn, item in sorted(pairs.items())}
    dataset["name_pair_audit"] = {cn: item for cn, item in sorted(pairs.items())}
    dataset["machine_translated_display_name"] = {cn: item["english"]
                                                  for cn, item in sorted(machine.items())}
    dataset["display_name_conflicts"] = conflicts
    dataset["display_name_rejected"] = rejected
    return {"tier1_pairs": len(pairs), "tier2_usable": len(machine),
            "tier2_rejected": len(rejected), "conflicts": len(conflicts),
            "registry": "references/display-name-channel.json"}


if __name__ == "__main__":  # owner spot-check harness
    import argparse

    parser = argparse.ArgumentParser(description="Inspect the display-only proper-name channel")
    parser.add_argument("dataset", help="payload/dataset JSON")
    args = parser.parse_args()
    print(json.dumps(annotate_dataset(json.loads(Path(args.dataset).read_text(encoding="utf-8"))),
                     ensure_ascii=True, indent=1))
