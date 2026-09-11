#!/usr/bin/env python3
"""Lossless frame extraction, exact change inventory, and full video decode QA.

Requires Python 3.9+, Pillow 9.1+, and ffmpeg/ffprobe on PATH. Frame numbers are
zero-based. No command deletes source media or automatically removes black frames.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import re
import shutil
import subprocess
import sys
from fractions import Fraction

from PIL import Image, ImageChops, ImageDraw


def run(args):
    return subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          text=True, encoding="utf-8", errors="replace")


def write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def probe(video, frames=False, count=False):
    cmd = ["ffprobe", "-v", "error"]
    if frames:
        cmd += ["-select_streams", "v:0", "-show_frames", "-show_entries",
                "frame=best_effort_timestamp,best_effort_timestamp_time,duration,pkt_duration,duration_time,pkt_duration_time"]
    else:
        cmd += ["-show_streams", "-show_format"]
    if count:
        cmd += ["-count_frames"]
    result = run(cmd + ["-of", "json", str(video)])
    if result.returncode:
        raise RuntimeError("ffprobe failed: " + result.stderr)
    return json.loads(result.stdout)


def first_video(info):
    return next(s for s in info["streams"] if s["codec_type"] == "video")


def file_hash(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def rgb_hash(image):
    h = hashlib.sha256(("RGB:%d:%d:" % image.size).encode("ascii"))
    h.update(image.tobytes())
    return h.hexdigest()


def rational_time(frame, stream):
    pts = frame.get("best_effort_timestamp")
    return str(Fraction(pts) * Fraction(stream["time_base"])) if pts is not None else None


def extract(args):
    out = Path(args.out_dir)
    if out.exists() and (not out.is_dir() or any(out.iterdir())):
        raise ValueError("OUT_DIR must be absent or empty; choose a new directory")
    if min(args.page_frames, args.columns, args.thumb_width) < 1:
        raise ValueError("Atlas dimensions must be positive")
    info = probe(args.video)
    stream = first_video(info)
    metadata = probe(args.video, frames=True)["frames"]
    out.mkdir(parents=True, exist_ok=True)
    images = out / "frames"
    atlases = out / "atlas"
    images.mkdir()
    atlases.mkdir()
    # No -r/fps filter: passthrough preserves VFR and all decoded frames.
    cmd = ["ffmpeg", "-hide_banner", "-v", "error", "-nostdin", "-xerror",
           "-err_detect", "explode", "-noautorotate", "-i", str(args.video),
           "-map", "0:v:0", "-an", "-sn", "-vsync", "0", "-start_number", "0",
           str(images / "frame_%08d.png")]
    result = run(cmd)
    files = sorted(images.glob("frame_*.png"))
    if result.returncode or len(files) != len(metadata) or not files:
        error = {"command": cmd, "returncode": result.returncode,
                 "stderr": result.stderr, "image_count": len(files),
                 "probe_frame_count": len(metadata)}
        write_json(out / "extract_error.json", error)
        raise RuntimeError("Extraction incomplete or frame counts differ; see extract_error.json")
    records, pages = [], []
    tile_h = round(args.thumb_width * stream["height"] / stream["width"])
    label_h = 36
    page = None
    for i, (path, meta) in enumerate(zip(files, metadata)):
        with Image.open(path) as raw:
            rgb = raw.convert("RGB")
            rec = {"index": i, "file": path.relative_to(out).as_posix(),
                   "sha256": file_hash(path), "rgb_sha256": rgb_hash(rgb),
                   "width": rgb.width, "height": rgb.height,
                   "pts": meta.get("best_effort_timestamp"),
                   "pts_seconds_exact": rational_time(meta, stream),
                   "pts_seconds": meta.get("best_effort_timestamp_time"),
                   "duration_ticks": meta.get("duration", meta.get("pkt_duration"))}
            records.append(rec)
            slot = i % args.page_frames
            if slot == 0:
                remaining = min(args.page_frames, len(files) - i)
                rows = math.ceil(remaining / args.columns)
                page = Image.new("RGB", (args.columns * args.thumb_width,
                                         rows * (tile_h + label_h)), "#10151d")
                draw = ImageDraw.Draw(page)
            thumb = rgb.copy()
            thumb.thumbnail((args.thumb_width, tile_h), Image.Resampling.LANCZOS)
            x = (slot % args.columns) * args.thumb_width
            y = (slot // args.columns) * (tile_h + label_h)
            page.paste(thumb, (x + (args.thumb_width - thumb.width) // 2, y))
            draw.text((x + 4, y + tile_h + 3), "f%d  PTS %ss" %
                      (i, rec["pts_seconds"] or "unknown"), fill="white")
        if slot == args.page_frames - 1 or i == len(files) - 1:
            page_path = atlases / ("page_%05d.jpg" % (i // args.page_frames))
            page.save(page_path, quality=94)
            pages.append({"file": page_path.relative_to(out).as_posix(),
                          "start": i - slot, "end": i})
    manifest = {"schema": 1, "source": str(Path(args.video).resolve()),
                "source_sha256": file_hash(args.video), "stream": stream,
                "frame_count": len(records), "index_base": 0,
                "timestamp_complete": all(r["pts_seconds_exact"] is not None for r in records),
                "autorotation": False, "image_encoding": "lossless PNG; statistics use decoded 8-bit RGB, all PNG byte changes retained",
                "frames": records, "atlas": pages, "extraction_command": cmd,
                "ffmpeg_stderr": result.stderr}
    write_json(out / "manifest.json", manifest)
    print(json.dumps({"frames": len(records), "atlas_pages": len(pages), "out": str(out)}))
    return 0


def load_manifest(directory):
    data = json.loads((Path(directory) / "manifest.json").read_text(encoding="utf-8"))
    if data.get("schema") != 1 or data.get("frame_count") != len(data.get("frames", [])):
        raise ValueError("Unsupported or inconsistent manifest: " + str(directory))
    if [r["index"] for r in data["frames"]] != list(range(data["frame_count"])):
        raise ValueError("Frame indices must be consecutive and zero-based")
    listed = {r["file"] for r in data["frames"]}
    actual = {p.relative_to(directory).as_posix() for p in (Path(directory) / "frames").glob("*.png")}
    if listed != actual:
        raise ValueError("PNG inventory differs from manifest: " + str(directory))
    return data


def allowed_ranges(values):
    ranges = []
    for value in values:
        match = re.fullmatch(r"(\d+):(\d+)", value)
        if not match or int(match[1]) > int(match[2]):
            raise ValueError("--allow must be START:END, zero-based inclusive")
        ranges.append((int(match[1]), int(match[2])))
    return ranges


def compare(args):
    before, after = load_manifest(args.before_dir), load_manifest(args.after_dir)
    allows = allowed_ranges(args.allow)
    timing = []
    for field in ("time_base", "avg_frame_rate", "r_frame_rate", "start_time"):
        a, b = before["stream"].get(field), after["stream"].get(field)
        if a != b:
            timing.append({"field": field, "before": a, "after": b})
    if before["frame_count"] != after["frame_count"]:
        timing.append({"field": "frame_count", "before": before["frame_count"], "after": after["frame_count"]})
    changed, integrity = [], []
    total = max(before["frame_count"], after["frame_count"])
    for i in range(total):
        a = before["frames"][i] if i < before["frame_count"] else None
        b = after["frames"][i] if i < after["frame_count"] else None
        expected = any(start <= i <= end for start, end in allows)
        row = {"index": i, "allowed_index": expected}
        if a is None or b is None:
            row["kind"] = "added" if a is None else "removed"
            changed.append(row)
            continue
        if a["pts_seconds_exact"] != b["pts_seconds_exact"] or a["pts_seconds_exact"] is None:
            timing.append({"field": "pts", "index": i,
                           "before": a["pts_seconds_exact"], "after": b["pts_seconds_exact"]})
        duration_a = a.get("duration_ticks")
        duration_b = b.get("duration_ticks")
        if duration_a is not None and duration_b is not None:
            duration_a = str(Fraction(duration_a) * Fraction(before["stream"]["time_base"]))
            duration_b = str(Fraction(duration_b) * Fraction(after["stream"]["time_base"]))
            if duration_a != duration_b:
                timing.append({"field": "duration", "index": i, "before": duration_a, "after": duration_b})
        elif duration_a != duration_b:
            timing.append({"field": "duration_availability", "index": i, "before": duration_a, "after": duration_b})
        paths = [Path(args.before_dir) / a["file"], Path(args.after_dir) / b["file"]]
        hashes = [file_hash(p) for p in paths]
        for side, rec, digest in zip(("before", "after"), (a, b), hashes):
            if digest != rec["sha256"]:
                integrity.append({"side": side, "index": i, "issue": "PNG differs from extraction manifest"})
        if hashes[0] == hashes[1]:
            continue
        with Image.open(paths[0]) as ar, Image.open(paths[1]) as br:
            ai, bi = ar.convert("RGB"), br.convert("RGB")
            row.update(before_size=ai.size, after_size=bi.size,
                       before_rgb_sha256=rgb_hash(ai), after_rgb_sha256=rgb_hash(bi))
            if ai.size != bi.size:
                row["kind"] = "dimensions"
            else:
                diff = ImageChops.difference(ai, bi)
                bands = diff.split()
                maximum = ImageChops.lighter(ImageChops.lighter(bands[0], bands[1]), bands[2])
                count = ai.width * ai.height - maximum.histogram()[0]
                hist = diff.histogram()
                row.update(kind="pixels" if count else "bytes_only_in_rgb8",
                           changed_pixels=count, total_pixels=ai.width * ai.height,
                           max_channel_delta=max(k % 256 for k, n in enumerate(hist) if n),
                           mean_abs_channel_delta=sum((k % 256) * n for k, n in enumerate(hist)) / (ai.width * ai.height * 3))
            changed.append(row)
    compatible = not timing
    for row in changed:
        row["classification"] = "timing_unverified" if not compatible else ("expected" if row["allowed_index"] else "unexpected")
    report = {"schema": 1, "before": str(Path(args.before_dir).resolve()),
              "after": str(Path(args.after_dir).resolve()), "time_compatible": compatible,
              "alignment": "same-index only; no resampling, nearest-time matching, or silent alignment",
              "comparison_space": "8-bit RGB statistics; bytes_only_in_rgb8 may include PNG metadata, encoding, alpha, or precision not represented in RGB8",
              "time_differences": timing, "allowed_inclusive_ranges": allows,
              "integrity_issues": integrity, "changed": changed,
              "changed_count": len(changed),
              "unexpected_count": sum(r["classification"] == "unexpected" for r in changed),
              "inheritance_candidate": compatible and not integrity and all(r["allowed_index"] for r in changed)}
    write_json(args.report, report)
    print(json.dumps({k: report[k] for k in ("time_compatible", "changed_count", "unexpected_count", "inheritance_candidate")}))
    return 2 if not compatible or integrity or report["unexpected_count"] else 0


def verify(args):
    problems = []
    try:
        info = probe(args.video, count=True)
        video = first_video(info)
    except (RuntimeError, ValueError, StopIteration, KeyError) as error:
        info, video = {"streams": []}, {}
        problems.append("ffprobe video inspection failed: " + str(error))
    audio = [s for s in info["streams"] if s["codec_type"] == "audio"]
    cmd = ["ffmpeg", "-hide_banner", "-nostdin", "-xerror", "-err_detect", "explode",
           "-i", str(args.video), "-map", "0:v:0", "-map", "0:a?",
           "-vf", "blackframe=amount=98:threshold=32", "-vsync", "0",
           "-progress", "pipe:1", "-nostats", "-f", "null", "-"]
    result = run(cmd)
    counts = re.findall(r"^frame=(\d+)", result.stdout, re.MULTILINE)
    decoded = int(counts[-1]) if counts else None
    probe_count = video.get("nb_read_frames")
    probe_count = int(probe_count) if str(probe_count).isdigit() else None
    declared = video.get("nb_frames")
    declared = int(declared) if str(declared).isdigit() else None
    if result.returncode:
        problems.append("ffmpeg full decode failed")
    if decoded is None or decoded == 0:
        problems.append("No decoded video frame count")
    if probe_count is not None and decoded != probe_count:
        problems.append("Full decode count differs from ffprobe nb_read_frames")
    if declared is not None and decoded != declared:
        problems.append("Full decode count differs from declared nb_frames")
    black = [{"index": int(m[0]), "black_percent": float(m[1]), "filter_time_seconds": m[2]}
             for m in re.findall(r"frame:(\d+).*?pblack:([\d.]+).*?t:([-\d.]+)", result.stderr)]
    report = {"schema": 1, "source": str(Path(args.video).resolve()),
              "status": "PASS" if not problems else "FAIL", "problems": problems,
              "decoded_frames": decoded, "probe_frames": probe_count, "declared_frames": declared,
              "video_stream": video, "audio_stream_count": len(audio), "audio_streams": audio,
              "audio_note": "All audio streams decoded; absent audio may be intentional. This does not prove sync or listening quality.",
              "black_candidates": black, "black_note": "98% pixels below luma 32; candidates only, never removed. Review fades, pauses and intended black manually.",
              "command": cmd, "returncode": result.returncode,
              "ffmpeg_stderr": result.stderr, "ffmpeg_progress": result.stdout,
              "scope": "first video stream and all audio streams; decoder verification, not real-time visual playback"}
    write_json(args.report, report)
    print(json.dumps({"status": report["status"], "frames": decoded,
                      "audio_streams": len(audio), "black_candidates": len(black)}))
    return 0 if not problems else 2


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("extract", help="Extract every decoded frame and consecutive atlases")
    p.add_argument("video"); p.add_argument("out_dir")
    p.add_argument("--page-frames", type=int, default=30)
    p.add_argument("--columns", type=int, default=6)
    p.add_argument("--thumb-width", type=int, default=320)
    p = sub.add_parser("compare", help="Inventory every changed frame without thresholds")
    p.add_argument("before_dir"); p.add_argument("after_dir")
    p.add_argument("--report", required=True)
    p.add_argument("--allow", action="append", default=[], metavar="START:END")
    p = sub.add_parser("verify", help="Decode video and audio fully; list black candidates")
    p.add_argument("video"); p.add_argument("--report", required=True)
    args = parser.parse_args()
    try:
        if args.command != "compare":
            for binary in ("ffmpeg", "ffprobe"):
                if not shutil.which(binary):
                    raise RuntimeError(binary + " is not on PATH")
        return {"extract": extract, "compare": compare, "verify": verify}[args.command](args)
    except (OSError, ValueError, RuntimeError, KeyError, StopIteration) as error:
        print("ERROR: " + str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
