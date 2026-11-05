"""Deterministic English gloss for Chinese POI category labels (checklist SS2.2.1).

The mechanism is root decomposition, not an example table: a category is tokenized by
longest-match against the tier/region/form/subject root tables (plus an exception table for
genuine irregulars such as proper nouns), then re-assembled in modifier-head order. Anything
that cannot be decomposed comes back as "" plus the missing segments, so the caller must fail
loudly and demand a lexicon entry instead of shipping Chinese into the English product.

Wording provenance: machine-composed from roots. Not externally verified. The owner samples
the generated labels before release (SS2.2.5 exists precisely because "extend the dictionary"
was already proven unscalable once).

Two things live in `references/category-lexicon.json` and nowhere else: the root tables, and
`category_columns` — the list of dataset columns that are category-shaped. MT-B2 (2026-10-31)
moved that second list into the config because it had been hardcoded in gen_travel_scope.py;
the column set there stopped at the five POI tables, so transport_nodes 的枢纽类别（机场 /
综合枢纽 / 客运轮渡码头）从未进过 category_en，英文页只能给读者一个 pending 标记。
"""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LEXICON_PATH = ROOT / "references" / "category-lexicon.json"

CJK_RE = re.compile(r"[\u4e00-\u9fff]+")
LATIN_RUN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9 .'&#+-]*")
SEPARATORS = ("与", "和", "及", "、", "·", "-", "—", "，", ",")
_STRIP = "《》()（）[]【】\"”“ "


def _load(path: Path | None = None) -> dict:
    data = json.loads((path or LEXICON_PATH).read_text(encoding="utf-8"))
    tables = data.get("tables") or {}
    roots: dict[str, tuple[str, str]] = {}
    for table_name in ("tier", "region", "nouns", "form", "subject"):
        for cn, en in (tables.get(table_name) or {}).items():
            key = cn.strip()
            if key and key not in roots:
                roots[key] = (en, table_name)
    # Exception table = whole-label overrides, never sub-token vocabulary. Mixing them into
    # the roots made --no-exceptions measure a partly disabled lexicon (a duplicate key like
    # 海鲜 resolved to the exception entry and then vanished from the root set).
    exceptions = {cn.strip(): en for cn, en in (tables.get("phrase") or {}).items() if cn.strip()}
    data["_roots"] = roots
    data["_exceptions"] = exceptions
    data["_order"] = {name: idx for idx, name in enumerate(data.get("compose_order") or [])}
    data["_max_root_len"] = max((len(k) for k in roots), default=1)
    # MT-B2：「哪几列是类别列」也只住在这份配置里。生成器和注释器都必须读它，
    # 否则又多一处列清单——v4.2.1 的列清单写在 gen_travel_scope.py 里，transport_nodes
    # 的枢纽类别就因为不在那份清单上而从未进过 category_en。
    data["_category_columns"] = [dict(col) for col in (data.get("category_columns") or [])]
    return data


LEXICON = _load()


def normalize(text: str) -> str:
    out = str(text or "").strip()
    for ch in _STRIP:
        out = out.replace(ch, "")
    return out.strip()


def _tokenize(text: str, merged: dict) -> tuple[list[tuple[str, str, str]], list[str]]:
    """Longest-match segmentation. The dictionary is tried at every position, so a numbered
    proper noun like 66号公路 wins before the bare digits get consumed as a Latin run."""
    tokens: list[tuple[str, str, str]] = []
    missing: list[str] = []
    i = 0
    max_len = LEXICON.get("_max_root_len", 12)
    while i < len(text):
        hit = None
        for span in range(min(max_len, len(text) - i), 1, -1):
            candidate = text[i:i + span]
            if candidate in merged:
                hit = (candidate, merged[candidate])
                break
        if hit is not None:
            candidate, (english, table_name) = hit
            if english:
                tokens.append((candidate, english, table_name))
            i += len(candidate)
            continue
        ch = text[i]
        if "\u4e00" <= ch <= "\u9fff":
            if ch in merged:
                english, table_name = merged[ch]
                if english:
                    tokens.append((ch, english, table_name))
                i += 1
                continue
            missing.append(ch)
            i += 1
            continue
        run = LATIN_RUN_RE.match(text, i)
        if run and run.group(0).strip():
            value = run.group(0).strip()
            tokens.append((value, value, "latin"))
            i = run.end()
            continue
        i += 1
    return tokens, missing


def compose(text: str, *, use_exceptions: bool = True) -> tuple[str, list[str]]:
    """Return (english_gloss, uncovered_cjk). Empty gloss means 'must be filled in'."""
    raw = normalize(text)
    if not raw:
        return "", []
    if not CJK_RE.search(raw):
        return raw, []
    if use_exceptions and raw in LEXICON["_exceptions"]:
        return LEXICON["_exceptions"][raw], []
    tokens, missing = _tokenize(raw, LEXICON["_roots"])
    missing = sorted(set(missing))
    if missing or not tokens:
        return "", missing or [raw]
    order = LEXICON["_order"]
    ranked = sorted(range(len(tokens)),
                    key=lambda idx: (order.get(tokens[idx][2], len(order)), idx))
    # Head-like tables (subject/kind) read last in English, so put modifiers first while
    # keeping the original order inside each class.
    seen: list[str] = []
    stems: set[str] = set()
    for idx in ranked:
        value = tokens[idx][1]
        stem = re.sub(r"[^a-z]", "", value.lower())
        # "Themed Theme Park" reads as a bug, not as translation: skip a modifier whose head
        # word is already present.
        if stem and stem in stems:
            continue
        if value not in seen:
            seen.append(value)
            if stem:
                stems.add(stem)
    gloss = re.sub(r"\s{2,}", " ", " ".join(seen)).strip()
    return gloss, []


def coverage(values: list[str], *, use_exceptions: bool = True) -> dict:
    mapped: dict[str, str] = {}
    unmapped: dict[str, list[str]] = {}
    for value in values:
        gloss, missing = compose(value, use_exceptions=use_exceptions)
        if gloss:
            mapped[str(value)] = gloss
        else:
            unmapped[str(value)] = missing
    return {"total": len(values), "mapped": len(mapped), "unmapped": len(unmapped),
            "map": mapped, "unmapped_detail": unmapped}


def category_values(dataset: dict) -> list[str]:
    """按 `category_columns` 登记收集类别值；list 行看 index，dict 行看 field。

    两种形状都是现场事实：交付载荷里 hotels/transport 仍是位置数组，transport_nodes 已是对象，
    所以登记面必须同时支持 index 与 field，不能只认一种（只认 index 就是 transport_nodes
    类别从来没进过 category_en 的直接原因）。
    """
    values: list[str] = []
    for col in LEXICON.get("_category_columns") or []:
        rows = dataset.get(str(col.get("dataset") or "")) or []
        for row in rows:
            if isinstance(row, dict):
                value = row.get(str(col.get("field") or ""))
            elif isinstance(row, (list, tuple)) and col.get("index") is not None:
                idx = int(col["index"])
                value = row[idx] if len(row) > idx else None
            else:
                value = None
            text = str(value or "").strip()
            if text and CJK_RE.search(text):
                values.append(text)
    return sorted(set(values))


def annotate_dataset(dataset: dict, *, source_of_truth: str = "references/category-lexicon.json") -> dict:
    """Fill dataset['category_en'] for every Chinese category the reader may see in EN mode."""
    unique = category_values(dataset)
    report = coverage(unique)
    report.update({"source_of_truth": source_of_truth, "distinct": len(unique),
                   "registry": "references/category-lexicon.json::category_columns",
                   "lexicon_version": (LEXICON.get("lexicon_version") or {}).get("version")})
    if unique:
        dataset["category_en"] = report["map"]
        # 「X :: 缺字根 Y」是交付物里已经存在的写法，注释器与生成器共用同一份产物格式，
        # 不许出现第二套描述文本。
        dataset["category_unmapped"] = sorted(
            f"{value} :: 缺字根 {''.join(missing)}"
            for value, missing in report["unmapped_detail"].items())
    else:
        dataset.setdefault("category_en", {})
        dataset.setdefault("category_unmapped", [])
    return report


if __name__ == "__main__":  # manual spot-check harness for the owner
    import argparse
    parser = argparse.ArgumentParser(description="Compose English category glosses from roots")
    parser.add_argument("values", nargs="*")
    parser.add_argument("--file", default="", help="one category per line (space separated also fine)")
    parser.add_argument("--no-exceptions", action="store_true", help="measure root coverage only")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    items = list(args.values)
    if args.file:
        text = Path(args.file).read_text(encoding="utf-8")
        items = [p.strip() for chunk in text.split("\n") for p in re.split(r"[ \t]+", chunk) if p.strip()]
    report = coverage(items, use_exceptions=not args.no_exceptions)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=1))
    else:
        print(f"total={report['total']} mapped={report['mapped']} unmapped={report['unmapped']}")
        for value, gloss in sorted(report["map"].items()):
            print(f"  OK   {value} -> {gloss}")
        for value, missing in sorted(report["unmapped_detail"].items()):
            print(f"  MISS {value} :: 未覆盖字根 {missing}")
