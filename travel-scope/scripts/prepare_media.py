"""Declarative media preparation (§5.4.1).

The California run delivered 20 section covers squeezed into a fixed 1000x650 box, which stretched
an 8.6:1 panorama into a 1.54:1 smear — and nothing in the release produced those bytes, so the
manifest hash could never describe them. This module owns the transform instead:

  source bytes -> aspect-preserving renditions -> {source_sha256, delivered_sha256, transform}

The visual crop is left to CSS `object-fit: cover`, which is reversible and never distorts.
Every output row carries both hops, so the gate can prove the delivered bytes without trusting a
single recorded digest.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import shutil
from pathlib import Path

from PIL import Image

try:  # v4.2.2 V6-C：交付档由登记决定，本文件不再自己拿一张档位表
    from . import single_file_policy
except ImportError:  # pragma: no cover
    import single_file_policy

ASPECT_TOLERANCE = 0.02
TIER_DIR = "renditions"


def ladder() -> dict:
    """交付档 + 交付预算的唯一来源：references/single-file-delivery-policy.json。

    以前这里是 `RENDITIONS = (("w1200", 1200, 72), ("w800", 800, 70))` 一行裸常数：
    改登记不改这里，产物会静默按旧档位出货，而账单看起来仍然合规——正是 V0-L11 的形状。
    """
    return single_file_policy.rendition_ladder()


def slot_tiers(slot: str) -> list[tuple[str, int, int]]:
    table = ladder()["slots"]
    if slot not in table:
        raise ValueError("MEDIA_SLOT_UNKNOWN|%s 不在登记槽位 %s 里，档位无从声明"
                         % (slot, sorted(table)))
    return list(table[slot])


def slot_for(item: dict) -> str:
    """Map a manifest row to the layout slot that decides which renditions are worth building.

    Both entry points used to disagree: rebuild_media called a route cover "hero" while
    prepare_run passed the raw display_role "route_hero" through, which fell off the end of
    the slot table and quietly built the wrong tier set for every hero in the run.
    槽位集合本身由登记声明（single_file_policy.LADDER_SLOTS），这里只做角色→槽位的映射。
    """
    role = str(item.get("display_role") or "").strip().lower()
    if role == "route_hero" or str(item.get("category") or "").upper() == "EDITORIAL":
        return "hero"
    return "destination_atmosphere"


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def primary_rendition(rows: list) -> dict:
    """一行交付档里的「主档」＝最宽的那一档。

    这条选择规则以前只写在 install_run_media 里（`sorted(..., key=lambda t: -int(t["width"]))[0]`），
    于是「装机器件」和「核验血缘的离线重放」各拿一份排序逻辑：改一处，另一处就会静默拿着次宽档
    去验主档摘要。核验者（local_media_gate.replay_delivered_from_prepared）现在调这里。
    """
    ordered = sorted(rows or [], key=lambda t: -int(t["width"]))
    if not ordered:
        raise ValueError("MEDIA_NO_RENDITION|重放没有产任何档位，主档无从指认")
    return ordered[0]


def _ratio(width: int, height: int) -> float:
    return width / height if height else 0.0


def normalize_acquisition(blob: bytes, target_width: int, params: dict) -> tuple[bytes, str]:
    """把「API thumburl 取回的那串字节」确定性归一到清单声明的采集宽度。

    业主 2026-11-03 R3D 裁示：允许 API 返回 1920 后本地确定性缩成 prepared 1600，但这条桥必须可离线复算——
    所以它是唯一实现，参数只许来自 references/media-policy.json::source_verification_snapshot.acquisition_normalize，
    核验侧（local_media_gate）不许另写一份 PIL 缩放，否则又是两把尺子各自漂移。
    永不放大：插值不会还给读者细节，把窄档吹大再声称它来自 Commons 是伪造血缘。
    """
    resampling = str(params.get("resampling") or "")
    if resampling.upper() != "LANCZOS":
        raise ValueError("MEDIA_LINEAGE_ACQUISITION_BRIDGE_MISSING|登记的归一重采样是 %r，"
                         "本实现只支持 LANCZOS ⇒ 换写法要先改实现并重新量，不许口头声称" % resampling)
    for key in ("quality", "subsampling"):
        if params.get(key) is None:
            raise ValueError("MEDIA_SNAPSHOT_POLICY_INCOMPLETE|acquisition_normalize 缺 %s" % key)
    quality = int(params["quality"])
    subsampling = int(params["subsampling"])
    optimize = bool(params.get("optimize"))
    progressive = bool(params.get("progressive"))
    if int(target_width) <= 0:
        raise ValueError("MEDIA_LINEAGE_ACQUISITION_BRIDGE_MISSING|声明的采集宽度是 %r ⇒ 归一目标无从确定"
                         % target_width)
    with Image.open(io.BytesIO(blob)) as image:
        image.load()
        source_width, source_height = image.size
        if params.get("never_upscale", True) and source_width < int(target_width):
            raise ValueError("MEDIA_LINEAGE_ACQUISITION_BRIDGE_MISSING|API 取回档只有 %d 宽，"
                             "清单声明要 %d 宽：禁止放大补像素（插值不会还给读者细节），"
                             "这一行今天的状态是没有可绑的采集字节" % (source_width, int(target_width)))
        work = image.convert("RGB")
        work.thumbnail((int(target_width), int(target_width) * 10), Image.Resampling.LANCZOS)
        canvas = io.BytesIO()
        work.save(canvas, format="JPEG", quality=quality, optimize=optimize,
                  progressive=progressive, subsampling=subsampling)
    recipe = ("normalize=resampling=%s|thumbnail_aspect_preserve(width=%d)"
              "|jpeg(quality=%d,subsampling=%d,optimize=%s,progressive=%s)"
              % (resampling.upper(), work.size[0], quality, subsampling,
                 str(optimize).lower(), str(progressive).lower()))
    return canvas.getvalue(), recipe


def _lmg():
    """延迟导入 local_media_gate：它内部也延迟导入本模块，模块级互引会变成导入环。

    路径口径（布局模板与判据）的唯一持有者是 local_media_gate＋references/media-policy.json；
    本模块只调用，不在这里再写一遍 "media_prepared/originals" 这种字面量。
    """
    import local_media_gate
    return local_media_gate


def finalize_chain_face(run_root: Path, chain: dict, *, verify_files: bool = True,
                        face_rel: str = "media_prepared/media-manifest.json") -> dict:
    """把「要落进 run 的那份链条面」的路径收敛成 run 相对 POSIX（业主 R3F 第 2／3／5 条）。

    运行期允许用临时绝对目录（prepare_asset 的 out_dir 就是），但写进 run 的清单之前必须转换；
    转换的位置来自登记面，不来自本模块的记忆。verify_files=True 时写完形状立刻用门的同一把
    尺子判一遍（判内存里这一份），不合格就抛——生产者自己先挡住，而不是留一份坏面孔等门报错。
    """
    lmg = _lmg()
    policy = lmg.source_snapshot_policy()
    layouts = lmg.run_path_face_layout(policy, face_rel)
    root = Path(run_root).resolve()
    out = json.loads(json.dumps(chain, ensure_ascii=False))
    moved = {"entries_source": 0, "rendition_relpath": 0}
    for entry in out.get("entries") or []:
        local = str(entry.get("local_file") or "")
        name = Path(local.replace("\\", "/")).name
        current = str(entry.get("source") or "")
        # 文件名以现值为准；GCM 那类空值退到 local_file 的文件名（业主 R3F 第 3 条）。
        base = Path(current.replace("\\", "/")).name if current else name
        if base:
            entry["source"] = str(layouts.get("entries[].source") or "").replace("{file}", base)
            moved["entries_source"] += 1
        for rendition in entry.get("renditions") or []:
            base = Path(str(rendition.get("relpath") or "").replace("\\", "/")).name
            if not base:
                continue
            rendition["relpath"] = str(layouts.get("entries[].renditions[].relpath") or "").replace(
                "{file}", base)
            moved["rendition_relpath"] += 1
    if verify_files:
        errors, _metrics = lmg.run_path_containment_errors(
            root, policy, faces={face_rel: out})
        if errors:
            raise ValueError("; ".join(errors[:8]))
    out["path_form"] = {"rule": "run_relative_posix", "authority":
                        "references/media-policy.json::source_verification_snapshot.run_relative_path_rule",
                        "entries_source_rewritten": moved["entries_source"],
                        "rendition_relpath_rewritten": moved["rendition_relpath"],
                        "verified_files_before_write": bool(verify_files)}
    return out


def prepare_asset(source: Path, out_dir: Path, *, slot: str) -> dict:
    """Render one source image into the renditions its slot can actually use; refuse to distort."""
    tiers = slot_tiers(slot)
    budget = ladder()
    wanted = {label for label, _width, _quality in tiers}
    blob = source.read_bytes()
    with io.BytesIO(blob) as handle:
        with Image.open(handle) as image:
            image.load()
            source_width, source_height = image.size
            source_mode = image.mode
            source_ratio = _ratio(source_width, source_height)
            rows = []
            for label, width, quality in tiers:
                target_width = min(width, source_width)
                # V6-R：交付宽度不许把高度等比压到登记下限以下。1600×533 的 Bixby 大桥全景
                # 按 w1000 出档会得到 1000×333，媒体门按同一条下限判它不合规——我们等于自己
                # 产出一张注定进不了读者页的交付图，而读者的代价是「这张照片没了」，不是「图小了点」。
                # 钳到「仍保住下限的最大压缩」；源本身就不达标的（sf_twin_peaks 1600×186）绝不
                # upscale（插值不会还给读者细节），它走 V6-Q 的媒体缺口登记，不靠压像素蒙过门。
                floor_width = (-(-budget["min_delivered_height_px"] * source_width // source_height)
                               if source_height else 0)
                floor_clamped = (source_height >= budget["min_delivered_height_px"]
                                 and target_width < floor_width)
                if floor_clamped:
                    target_width = min(floor_width, source_width)
                work = image.convert("RGB")
                # Never upscale, never box: cap at the source width and keep the aspect. Re-encoding is
                # unconditional so a "passthrough" of a heavy source file cannot quietly double the file.
                work.thumbnail((target_width, target_width * 10), Image.Resampling.LANCZOS)
                out_width, out_height = work.size
                if (source_height >= budget["min_delivered_height_px"]
                        and out_height < budget["min_delivered_height_px"]):
                    raise ValueError(
                        "IMG_DELIVERED_BELOW_GEOMETRY_FLOOR|%s %s 出档 %dx%d，高 %d 低于登记下限 %d"
                        "（钳制后仍不达标＝登记自相矛盾，禁止出货）"
                        % (slot, label, out_width, out_height, out_height,
                           budget["min_delivered_height_px"]))
                canvas = io.BytesIO()
                # The JPEG flags are a *registered* part of the ladder, not an encoder default: they
                # decide both the delivered bytes and how much colour detail the reader keeps.
                # With the old hard-coded defaults (PIL picks 4:2:0 below quality 95) a genuine
                # Twin Peaks panorama lost enough entropy to fall under the authenticity gate's
                # registered floor and be labelled a synthetic placeholder -- a real photo the
                # reader would never have gotten. See single-file-delivery-policy.json::
                # delivered_rendition_ladder.encode.
                encode = budget["encode"]
                work.save(canvas, format="JPEG", quality=quality, optimize=encode["optimize"],
                          progressive=encode["progressive"],
                          subsampling=encode["subsampling"])
                rendition_blob = canvas.getvalue()
                transform = ("ladder=%s|thumbnail_aspect_preserve(width=%d,quality=%d)"
                             "|jpeg(subsampling=%d,optimize=%s,progressive=%s)%s"
                             % (budget["ladder_id"], target_width, quality,
                                encode["subsampling"], str(encode["optimize"]).lower(),
                                str(encode["progressive"]).lower(),
                                ("|geometry_floor_clamped(min_height_px=%d,source=%dx%d)"
                                 % (budget["min_delivered_height_px"], source_width, source_height)
                                 if floor_clamped else "")))
                ratio = _ratio(out_width, out_height)
                drift = abs(ratio - source_ratio) / source_ratio if source_ratio else 0.0
                if drift > ASPECT_TOLERANCE:
                    raise ValueError(
                        "IMG_ASPECT_DISTORTED|%s %s 宽高比从 %.3f 变成 %.3f（偏差 %.1f%%），"
                        "禁止出货变形图" % (slot, label, source_ratio, ratio, drift * 100))
                if len(rendition_blob) > budget["max_delivered_image_decoded_bytes"]:
                    # 单张比内联上限大 = 这张注定进不了单文件，读者页要么留一个走文件的引用，
                    # 要么被 JS 兜底成假封面。两种都是读者可见缺陷，所以这里拒绝出货而不是放行。
                    raise ValueError(
                        "IMG_DELIVERED_OVER_INLINE_CAP|%s %s 重编后仍有 %dB，超过登记单图上限 %dB"
                        "（media_delivery.default_max_inline_kb × 1024）——要么再降这张的档位，"
                        "要么由业主改登记" % (slot, label, len(rendition_blob),
                                             budget["max_delivered_image_decoded_bytes"]))
                target = out_dir / slot / ("%s--%s.jpg" % (source.stem, label))
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(rendition_blob)
                rows.append({"label": label, "width": out_width, "height": out_height,
                             "bytes": len(rendition_blob), "relpath": str(target),
                             "geometry_floor_clamped": floor_clamped,
                             "delivered_sha256": _sha256(rendition_blob), "transform": transform,
                             "aspect_drift": round(drift, 5)})
    if len(rows) != len(wanted):
        # 登记声明了档位却没产出来，装配端会静默少一张 srcset——这必须是错，不是少一点。
        raise ValueError("MEDIA_LADDER_UNSTABLE|槽位 %s 声明 %d 档，实产 %d 档"
                         % (slot, len(wanted), len(rows)))
    return {"slot": slot, "source": str(source), "source_sha256": _sha256(blob),
            "source_bytes": len(blob), "source_width": source_width,
            "source_height": source_height, "source_mode": source_mode,
            "renditions": rows}


def prepare_run(run_root: Path, out_dir: Path, *, manifest_name: str = "asset-manifest.json") -> dict:
    """Prepare every asset the run manifest declares, and write the double-hop chain."""
    run_root = Path(run_root).resolve()
    manifest_path = run_root / manifest_name
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    items = manifest if isinstance(manifest, list) else manifest.get("assets", [])
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    entries, errors = [], []
    for item in items:
        local = run_root / str(item.get("local_file") or "")
        slot = slot_for(item)
        if not local.is_file():
            errors.append("MEDIA_SOURCE_MISSING|%s 清单指向的在盘文件不存在: %s" % (slot, local))
            continue
        try:
            entry = prepare_asset(local, out_dir, slot=slot)
        except ValueError as exc:                             # distortion is a verdict, not a crash
            errors.append(str(exc))
            continue
        entry["slot"] = slot
        entry["local_file"] = str(item.get("local_file") or "")
        entry["declared_sha256"] = str(item.get("sha256") or "")
        entry["declared_matches_source"] = entry["declared_sha256"] == entry["source_sha256"]
        entry["license"] = item.get("license")
        entry["author"] = item.get("author")
        entry["source_asset_url"] = item.get("source_asset_url")
        entries.append(entry)
    total = sum(r["bytes"] for e in entries for r in e["renditions"])
    budget = ladder()["total_delivered_image_decoded_bytes_max"]
    if total > budget:
        # 单张都合规、加起来照样能破围栏：这就是 PH 那 7 张之外、CA 全内联却 11.1MB 的成因。
        errors.append("SFD_DELIVERED_TOTAL_OVER_BUDGET|这棵树重编后的交付图合计 %dB，"
                      "超过登记总预算 %dB（由 max_delivered_file_bytes 减容器后按 3/4 反推）"
                      % (total, budget))
    report = {"status": "PASS" if not errors else "FAIL", "assets": len(entries),
              "renditions": sum(len(e["renditions"]) for e in entries),
              "rendition_bytes": total, "rendition_budget_bytes": budget,
              "ladder_id": ladder()["ladder_id"],
              "over_budget": total > budget,
              "errors": errors, "entries": entries}
    # 写盘的那份是**面孔**，返回的这份是**运行期对象**：install／试点工具要按 relpath 去搬字节，
    # 所以运行期继续用 out_dir 里的实际位置（业主 R3F 第 5 条明确允许临时绝对路径）；
    # 而落进 run 的清单必须只带 run 相对 POSIX，由 finalize_chain_face 按登记布局重写。
    face = finalize_chain_face(run_root, report, verify_files=False)
    (out_dir / "media-manifest.json").write_text(
        json.dumps(face, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return report


def install_run_media(run_root: Path, report: dict, *, out_dir: Path | None = None) -> dict:
    """Write the prepared chain back into the run so the build can consume what it can prove.

    This is the step the release used to be missing: the transform produced bytes that no command
    could regenerate, so the run's asset-manifest recorded digests that described a different
    picture. Install is deliberately loud -- an entry without a prepared chain stays a hard error
    instead of shipping the old bytes with the old digest.
    """
    run_root = Path(run_root).resolve()
    manifest_path = run_root / "asset-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    wrapped = isinstance(manifest, dict)
    items = manifest if not wrapped else manifest.get("assets", [])
    by_file = {str(e.get("local_file") or ""): e for e in report.get("entries", [])}
    tier_dir = run_root / "assets" / TIER_DIR
    tier_dir.mkdir(parents=True, exist_ok=True)
    backup_dir = Path(out_dir or run_root / "assets_prepared_backup") / "originals"
    backup_dir.mkdir(parents=True, exist_ok=True)
    installed, errors = 0, []
    for item in items:
        rel = str(item.get("local_file") or "")
        entry = by_file.get(rel)
        if entry is None:
            errors.append("MEDIA_CHAIN_NOT_PREPARED|%s 没有对应的准备结果，"
                          "清单里的摘要无法与交付字节对齐" % rel)
            continue
        tiers = sorted(entry.get("renditions") or [], key=lambda t: -int(t["width"]))
        if not tiers:
            errors.append("MEDIA_NO_RENDITION|%s 备好了条目却没有任何档位" % rel)
            continue
        primary = primary_rendition(tiers)
        source_file = run_root / rel
        shutil.copy2(source_file, backup_dir / Path(rel).name)
        shutil.copy2(primary["relpath"], source_file)
        tier_rows = []
        for tier in tiers:
            target = tier_dir / Path(tier["relpath"]).name
            shutil.copy2(tier["relpath"], target)
            actual = _sha256(target.read_bytes())
            if actual != tier["delivered_sha256"]:
                errors.append("MEDIA_TIER_WRITE_MISMATCH|%s 写入后摘要变了: %s" % (rel, target.name))
            tier_rows.append({"label": tier["label"], "width": tier["width"],
                              "height": tier["height"], "bytes": tier["bytes"],
                              "sha256": actual,
                              "path": "assets/%s/%s" % (TIER_DIR, target.name),
                              "file": target.name, "transform": tier["transform"]})
        item["source_sha256"] = entry["source_sha256"]
        item["source_width"] = entry["source_width"]
        item["source_height"] = entry["source_height"]
        item["delivered_sha256"] = primary["delivered_sha256"]
        item["delivered_width"] = primary["width"]
        item["delivered_height"] = primary["height"]
        item["transform"] = primary["transform"]
        item["aspect_drift"] = primary["aspect_drift"]
        item["slot"] = entry["slot"]
        item["sha256"] = primary["delivered_sha256"]   # local_file now holds the widest tier
        item["renditions"] = tier_rows
        installed += 1
    payload = manifest if not wrapped else dict(manifest)
    if wrapped:
        payload["assets"] = items
    manifest_path.write_text(json.dumps(payload, ensure_ascii=False, indent=1) + "\n",
                             encoding="utf-8")
    # 链条面也在这一步落成 run 相对：install 之前 prepare 写的那份还带着临时工作区位置，
    # 而装完字节才是「交付面孔该指哪儿」的时刻——这里用门的同一把尺子验一遍（文件在不在、
    # 摘要对不对），不合格就抛，不留一份能出货却断链的清单（业主 R3F 第 5／7 条）。
    chain_target = run_root / "media_prepared" / "media-manifest.json"
    out_inside_run = False
    try:
        Path(out_dir or run_root).resolve().relative_to(run_root)
        out_inside_run = True
    except Exception:
        out_inside_run = False
    chain_status = "not_written"
    installed_chain_face = None
    if chain_target.is_file() or out_inside_run:
        try:
            finalized = finalize_chain_face(run_root, report, verify_files=True)
        except ValueError as exc:
            errors.append("MEDIA_RUN_PATH_FINALIZE_REFUSED|%s" % str(exc)[:400])
        else:
            chain_target.parent.mkdir(parents=True, exist_ok=True)
            chain_target.write_text(json.dumps(finalized, ensure_ascii=False, indent=1) + "\n",
                                    encoding="utf-8")
            chain_status = "finalized_run_relative"
            installed_chain_face = finalized
    else:
        installed_chain_face = None
    return {"status": "PASS" if not errors else "FAIL", "installed": installed,
            "manifest_entries": len(items), "tier_dir": str(tier_dir),
            "backup_dir": str(backup_dir), "chain_face": str(chain_target),
            "chain_face_form": chain_status,
            "chain_face_entries": len((installed_chain_face or {}).get("entries") or []),
            "errors": errors}


def main() -> int:
    parser = argparse.ArgumentParser(description="声明式图片准备（保比例 + 双跳摘要）")
    parser.add_argument("--run-root", required=True)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--install", action="store_true",
                        help="把双跳链写回 run 的 asset-manifest.json（会先备份在盘原图）")
    args = parser.parse_args()
    report = prepare_run(Path(args.run_root), Path(args.out_dir))
    summary = {k: v for k, v in report.items() if k != "entries"}
    if args.install:
        summary["install"] = install_run_media(Path(args.run_root), report,
                                               out_dir=Path(args.out_dir))
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    for error in report["errors"][:10]:
        print("ERROR", error[:180])
    install = summary.get("install") or {}
    for error in install.get("errors", [])[:10]:
        print("ERROR", error[:180])
    ok = report["status"] == "PASS" and install.get("status", "PASS") == "PASS"
    return 0 if ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
