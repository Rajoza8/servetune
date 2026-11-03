"""Make a portable three-minute evidence video entirely off GPU and offline.

Storyboards, narration and captions are written before optional rendering.
Pillow and ffmpeg are lazy optional dependencies; this module never installs
anything, calls an API, or controls a rental. Plot frames are for video only;
the report's standalone SVGs remain the shareable static charts.
"""

from __future__ import annotations

from collections import defaultdict
import importlib
import json
import math
import os
from pathlib import Path
import shutil
import statistics
import subprocess
import textwrap
import time

from .study_report import verify_study


CHAPTERS = (("problem", "The problem", 20), ("method", "The measured loop", 25),
            ("map", "The energy map", 35), ("ab", "BF16 and FP8", 25),
            ("search", "Spark and random search", 50), ("results", "Results and limits", 25))
WIDTH, HEIGHT, FPS = 1280, 720, 12


class DemoDependencyError(RuntimeError):
    pass


def _finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def _fmt(value):
    return f"{value:.4g}" if _finite(value) else "unavailable"


def _write(path, value):
    path = Path(path)
    if path.is_symlink():
        raise ValueError("Demo output must not replace a symlink")
    path.write_text(value)


def _srt_time(seconds):
    milliseconds = int(round(seconds * 1000))
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    secs, millis = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def _confirmed_groups(verified):
    groups = defaultdict(list)
    for row in verified["headline_rows"]:
        if (row["eligible"] and row["status"] == "pass"
                and all(_finite(row.get(key)) for key in
                        ("joules_per_output_token", "joules_per_completed_request", "p95_latency_s"))):
            groups[row["config_label"] or row["id"]].append(row)
    return {label: {"observations": len(rows),
                    "joules_per_output_token": statistics.median(row["joules_per_output_token"] for row in rows),
                    "joules_per_completed_request": statistics.median(row["joules_per_completed_request"] for row in rows),
                    "p95_latency_s": statistics.median(row["p95_latency_s"] for row in rows)}
            for label, rows in groups.items()}


def _plan(verified, duration_s):
    rows = verified["rows"]
    synthetic = bool(verified["study"].get("mode") == "synthetic_fixture" or
                     (rows and all(row["mode"] == "synthetic_fixture" for row in rows)))
    groups = _confirmed_groups(verified)
    result_ready = bool(not synthetic and verified["root_manifest_verified"]
                        and verified["status"] == "complete" and groups)
    label = ("SYNTHETIC SOFTWARE DEMO — NO GPU RESULTS" if synthetic else
             "VERIFIED FINAL CONFIRMATION" if result_ready else
             "INCOMPLETE PROCESS DEMO — NO FINAL RESULT CLAIM")
    live = sum(row["live_observation"] for row in rows)
    maps = sum(row["phase"] == "map" for row in rows)
    timeline = verified.get("timeline", [])
    quality = verified.get("final_paired_quality", [])
    if synthetic:
        intro = (f"This is ServeTune's synthetic software replay. Its {len(rows)} recorded fixture trials "
                 "exercise the controller, reports and video. None of the displayed energy or quality values "
                 "are measurements of a GPU or a model. The same harness can record real hardware evidence.")
    else:
        intro = (f"ServeTune measures serving configurations for an open-weight Meta model. This record contains "
                 f"{len(rows)} indexed trials, including {live} verified live observations. The goal is lower GPU "
                 "energy per token under a fixed incoming workload, a latency target and a quality gate. "
                 + ("The final comparison uses fresh confirmation measurements." if result_ready else
                    "This is an incomplete process demonstration; it establishes no final optimization result."))
    method = ("The trace fixes when requests arrive, including queueing in latency. Each bounded configuration "
              "starts a fresh engine, warms up, and measures the complete workload through the final response. "
              "NVML cumulative counters measure GPU energy. Actual tokens and completed requests are counted. "
              "Quality, latency, failures and length drift govern whether a change can be kept.")
    map_text = (f"The record contains {maps} energy-map trials across the recorded load levels. The plot pairs "
                "joules per output token with ninety-fifth percentile latency. Lower values are preferable. "
                "The frontier uses eligible observations; failures remain in the record. Energy per completed "
                "request is reported alongside energy per token. These measurements apply only to the recorded "
                "GPU, engine, model revision and workload.")
    if synthetic:
        method = "This synthetic replay illustrates the intended method. " + method
        map_text = "Every point in this synthetic map is a software fixture, not a hardware measurement. " + map_text
    bf16, fp8 = groups.get("bf16-default"), groups.get("fp8-default")
    if synthetic:
        ab = "These BF16 and FP8 points are synthetic fixtures. They demonstrate the A/B display and cannot establish quantization savings, speed, or model quality."
    elif result_ready and bf16 and fp8:
        ab = (f"Fresh eligible confirmation records show a median of {_fmt(bf16['joules_per_output_token'])} "
              f"GPU joules per output token for BF16 defaults, and {_fmt(fp8['joules_per_output_token'])} for "
              "FP8 defaults. These are observed values, with no assumed positive saving. The quality comparison "
              "must be read alongside them, using the predeclared two-percentage-point tolerance on held-out items.")
    else:
        ab = ("No admissible final BF16 versus FP8 comparison is available in this record. Any displayed A/B "
              "points are preliminary process evidence. They do not establish an energy saving or equal quality. "
              "Failed and inconclusive comparisons remain part of the result.")
    aliases = verified["confirmation"].get("aliases", {})
    r_label, s_label = aliases.get("R-winner", "R-winner"), aliases.get("S-winner", "S-winner")
    r_result, s_result = groups.get(r_label), groups.get(s_label)
    search = (f"The arm histories retain {len(timeline)} proposal and decision records. Random search and "
              "Muse Spark receive the same configuration space and allocated time budget. Spark's planning "
              "wait, engine loads, warmup, evaluations, failures and incomplete trials count against its clock. "
              "Each arm sees only its own search history. The timeline shows the actual hypothesis and the "
              "recorded accept or revert decision. Tuning observations are process evidence, not headline results. ")
    if synthetic:
        search += "Both arms here are synthetic software fixtures, so this replay cannot show that a model beats random search."
    elif result_ready and r_result and s_result:
        if r_label == s_label:
            search += "Both arms selected the same confirmed configuration; those aliases share one set of measurements, not independent confirmations."
        else:
            search += (f"Fresh confirmation records a median of {_fmt(r_result['joules_per_output_token'])} "
                       f"GPU joules per output token for the random-search selection and "
                       f"{_fmt(s_result['joules_per_output_token'])} for the Spark selection. This comparison is workload-specific.")
    else:
        search += "An eligible final comparison of the two selections is not available; no superiority claim follows."
    if result_ready:
        ending = (f"The final table contains {len(verified['headline_rows'])} live confirmation attempts, with "
                  f"{len(groups)} eligible configuration groups. Failed or ineligible confirmations stay in "
                  "the report. Quality wording is within the predeclared two-percentage-point tolerance on "
                  "this evaluation. The repository includes frozen inputs, raw evidence, offline reports and "
                  "rebuild instructions. No whole-system energy, general speedup or state-of-the-art claim is made.")
    else:
        ending = ("The deliverable is a reproducible measurement and decision workflow. This replay is "
                  + ("synthetic software evidence, not an experimental result. " if synthetic else
                     "an incomplete experiment, not a final optimization result. ")
                  + "The report preserves all failures, scripts, frozen inputs and verification hashes. "
                  "It makes no whole-system energy, general speedup or agent-superiority claim.")
    narrations = (intro, method, map_text, ab, search, ending)
    chapters, offset = [], 0.0
    for (key, title, nominal), narration in zip(CHAPTERS, narrations):
        length = nominal * duration_s / 180
        chapters.append({"key": key, "title": title, "start_s": offset,
                         "end_s": offset + length, "narration": narration})
        offset += length
    chapters[-1]["end_s"] = duration_s
    return {"schema_version": 1, "duration_s": duration_s, "fps": FPS,
            "width": WIDTH, "height": HEIGHT, "synthetic": synthetic,
            "result_ready": result_ready, "persistent_label": label,
            "study_status": verified["status"], "root_manifest_verified": verified["root_manifest_verified"],
            "root_manifest_sha256": verified["root_manifest_sha256"],
            "indexed_trials": len(rows), "verified_live_trials": live,
            "headline_observations": len(verified["headline_rows"]), "confirmed_groups": groups,
            "paired_quality": quality if result_ready else [], "chapters": chapters,
            "claim_scope": "GPU energy (NVML); exact recorded hardware/model/engine/frozen workloads only"}


def _resolve_ffmpeg(value=None):
    if value is not None:
        candidate = Path(value).expanduser()
        resolved = str(candidate.resolve()) if candidate.is_file() else shutil.which(str(value))
    else:
        resolved = shutil.which("ffmpeg")
        if not resolved:
            try:
                resolved = importlib.import_module("imageio_ffmpeg").get_ffmpeg_exe()
            except (ImportError, RuntimeError, OSError):
                resolved = None
    if (not resolved or not Path(resolved).is_file() or not os.access(resolved, os.X_OK)
            or not Path(resolved).name.casefold().startswith("ffmpeg")):
        raise DemoDependencyError("A local executable ffmpeg is required; no dependency was installed")
    return str(Path(resolved).resolve())


def _pillow():
    try:
        return (importlib.import_module("PIL.Image"), importlib.import_module("PIL.ImageDraw"),
                importlib.import_module("PIL.ImageFont"))
    except ImportError as exc:
        raise DemoDependencyError("Pillow is required for frame rendering; storyboard and narration were preserved") from exc


def _command(binary, video, duration, *, audio=None):
    command = [binary, "-hide_banner", "-loglevel", "warning", "-nostdin", "-n",
               "-protocol_whitelist", "file,pipe", "-f", "rawvideo", "-pix_fmt", "rgb24",
               "-s:v", f"{WIDTH}x{HEIGHT}", "-r", str(FPS), "-i", "pipe:0"]
    if audio is not None:
        command += ["-protocol_whitelist", "file,pipe", "-i", str(audio),
                    "-map", "0:v:0", "-map", "1:a:0", "-af", "apad", "-c:a", "aac", "-b:a", "128k"]
    else:
        command += ["-an"]
    command += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "21", "-pix_fmt", "yuv420p",
                "-t", str(duration), "-movflags", "+faststart", "-f", "mp4", str(video)]
    return command


class _Painter:
    def __init__(self, verified, plan, pillow):
        self.verified, self.plan = verified, plan
        self.Image, self.Draw, self.Font = pillow
        self.fonts = {}
        candidates = ("/System/Library/Fonts/Supplemental/Arial.ttf",
                      "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/Library/Fonts/Arial.ttf")
        for size in (14, 17, 20, 24, 32, 40):
            for path in candidates:
                try:
                    self.fonts[size] = self.Font.truetype(path, size)
                    break
                except OSError:
                    continue
            else:
                self.fonts[size] = self.Font.load_default()

    def text(self, draw, xy, value, size=20, color="#d9e5ed", width=1140):
        words, lines, current = str(value).split(), [], ""
        for word in words:
            trial = (current + " " + word).strip()
            if current and draw.textbbox((0, 0), trial, font=self.fonts[size])[2] > width:
                lines.append(current)
                current = word
            else:
                current = trial
        lines.append(current)
        x, y = xy
        for line in lines:
            draw.text((x, y), line, font=self.fonts[size], fill=color)
            y += size + 8
        return y

    def plot(self, draw, rows, xkey, ykey, xlabel, ylabel, *, bounds=(100, 250, 1180, 610), frontier=False):
        left, top, right, bottom = bounds
        points = [row for row in rows if _finite(row.get(xkey)) and _finite(row.get(ykey))]
        xmax = max([row[xkey] for row in points] + [1]) * 1.1
        ymax = max([row[ykey] for row in points] + [1]) * 1.12
        x = lambda value: left + value / xmax * (right - left)
        y = lambda value: bottom - value / ymax * (bottom - top)
        for i in range(6):
            xx, yy = left + i * (right-left)/5, top + i*(bottom-top)/5
            draw.line((xx, top, xx, bottom), fill="#284355", width=1)
            draw.line((left, yy, right, yy), fill="#284355", width=1)
            self.text(draw, (xx-14, bottom+8), _fmt(xmax*i/5), 14)
            self.text(draw, (left-65, yy-5), _fmt(ymax*(5-i)/5), 14)
        self.text(draw, (left+360, bottom+35), xlabel, 17)
        self.text(draw, (left, top-30), ylabel, 17, color="#91cdbd")
        if frontier:
            eligible = [row for row in points if row.get("eligible")]
            front = sorted([row for row in eligible if not any(
                other[xkey] <= row[xkey] and other[ykey] <= row[ykey]
                and (other[xkey] < row[xkey] or other[ykey] < row[ykey]) for other in eligible)],
                key=lambda row: row[xkey])
            if len(front) > 1:
                draw.line([(x(row[xkey]), y(row[ykey])) for row in front], fill="#8499ab", width=2)
        for row in points:
            color = "#60c4a7" if row.get("arm") == "R" else "#82b3ff" if row.get("arm") == "S" else (
                "#e8b75c" if row.get("dtype") == "fp8" else "#9fc6db")
            xx, yy = x(row[xkey]), y(row[ykey])
            draw.ellipse((xx-5, yy-5, xx+5, yy+5), fill=color)
        if not points:
            self.text(draw, (left+200, top+120), "No recorded observations for this panel", 24)

    def frame(self, seconds):
        image = self.Image.new("RGB", (WIDTH, HEIGHT), "#102739")
        draw = self.Draw.Draw(image)
        chapter = next((row for row in self.plan["chapters"] if row["start_s"] <= seconds < row["end_s"]), self.plan["chapters"][-1])
        progress = min(1, max(0, (seconds-chapter["start_s"])/(chapter["end_s"]-chapter["start_s"])))
        self.text(draw, (55, 25), "SERVETUNE  /  EVIDENCE REPLAY", 17, "#82d8bd")
        self.text(draw, (55, 67), chapter["title"], 40)
        badge = "#e8b75c" if not self.plan["result_ready"] else "#82d8bd"
        self.text(draw, (55, 126), self.plan["persistent_label"], 17, badge)
        rows = [row for row in self.verified["rows"] if row["live_observation"] or (self.plan["synthetic"] and row["mode"] == "synthetic_fixture")]
        key = chapter["key"]
        if key == "problem":
            self.text(draw, (60, 215), "Same workload. Different serving settings. Measured consequences.", 32)
            for x, label, value in ((65, "Indexed trials", self.plan["indexed_trials"]),
                                    (465, "Verified live trials", self.plan["verified_live_trials"]),
                                    (865, "Final observations", self.plan["headline_observations"])):
                draw.rounded_rectangle((x, 330, x+345, 510), 14, fill="#19384d")
                self.text(draw, (x+22, 355), label, 20)
                self.text(draw, (x+22, 415), str(value), 40, "#82d8bd")
            self.text(draw, (65, 560), "GPU energy only • fixed hardware/model/engine/workload scope", 20)
        elif key == "method":
            labels = ("Frozen arrivals", "Bounded proposal", "Fresh engine", "Measure full trace", "Quality + latency", "Accept / revert")
            for i, label in enumerate(labels):
                column, row = i % 3, i // 3
                x, y = 70 + column*405, 245 + row*175
                active = i <= int(progress*6)
                draw.rounded_rectangle((x, y, x+330, y+110), 14, fill="#27594f" if active else "#19384d")
                self.text(draw, (x+15, y+17), f"{i+1:02d}", 17, "#82d8bd")
                self.text(draw, (x+15, y+51), label, 24)
            self.text(draw, (70, 610), "Every request completes • actual tokens counted • failures retained", 20)
        elif key == "map":
            maps = [row for row in rows if row["phase"] == "map"]
            loads = list(dict.fromkeys(row["load_label"] for row in maps))
            load = loads[min(len(loads)-1, int(progress*len(loads)))] if loads else None
            selected = [row for row in maps if row["load_label"] == load]
            self.text(draw, (65, 185), f"Recorded load filter: {load or 'unavailable'}", 20)
            self.plot(draw, selected, "p95_latency_s", "joules_per_output_token", "p95 latency (seconds)", "GPU joules / output token", frontier=True)
        elif key == "ab":
            final = [row for row in self.verified["headline_rows"] if row["config_label"] in ("bf16-default", "fp8-default") and row["eligible"]]
            selected = final if self.plan["result_ready"] else [row for row in rows if row["phase"] == "ab"]
            title = "Fresh eligible confirmation" if self.plan["result_ready"] and final else "Preliminary / incomplete process evidence"
            self.text(draw, (65, 185), title + " · no positive saving assumed", 20)
            points = [{**row, "dtype_index": 1 if row["dtype"] == "bf16" else 2} for row in selected]
            self.plot(draw, points, "dtype_index", "joules_per_output_token", "1 = BF16 defaults    2 = FP8 defaults", "GPU joules / output token")
        elif key == "search":
            selected = [row for row in rows if row["phase"] == "search"]
            points = [{**row, "trial_index": i+1} for i, row in enumerate(selected[:max(1, int(progress*len(selected)))])]
            self.plot(draw, points, "trial_index", "joules_per_output_token", "Recorded search repeat order — process evidence", "GPU joules / output token", bounds=(100, 240, 1180, 465))
            timeline = self.verified.get("timeline", [])
            item = timeline[min(len(timeline)-1, int(progress*len(timeline)))] if timeline else None
            if item:
                self.text(draw, (65, 530), f"{item['id']} · {item['arm']} · " + ("accepted" if item["accepted"] is True else "reverted / rejected" if item["accepted"] is False else "decision unrecorded"), 24, "#82d8bd")
                self.text(draw, (65, 572), (item.get("hypothesis") or item.get("decision_reason") or "No explanation recorded")[:280], 17, width=1140)
            else:
                self.text(draw, (65, 550), "No arm decision history is available.", 24)
        else:
            if self.plan["result_ready"]:
                self.text(draw, (65, 190), "Eligible groups from fresh confirmation only", 24)
                for i, (label, row) in enumerate(list(self.plan["confirmed_groups"].items())[:5]):
                    y = 255+i*58
                    self.text(draw, (70, y), label, 20)
                    self.text(draw, (480, y), f"{_fmt(row['joules_per_output_token'])} GPU J/token", 20, "#82d8bd")
                    self.text(draw, (880, y), f"p95 {_fmt(row['p95_latency_s'])} s", 20)
                self.text(draw, (65, 580), "Quality: within the declared 2-percentage-point tolerance on this evaluation.", 17)
            else:
                self.text(draw, (65, 235), "The process is inspectable. The result remains bounded.", 32)
                self.text(draw, (65, 330), "No final optimization result is claimed from this replay.", 24, "#e8b75c")
                self.text(draw, (65, 410), "Frozen inputs • retained failures • verified artifacts • offline replay", 24)
            self.text(draw, (65, 620), "Open the accompanying results, CSVs, SVGs and source hashes.", 17)
        draw.rectangle((0, HEIGHT-12, int(WIDTH*seconds/self.plan["duration_s"]), HEIGHT), fill="#70ccb0")
        self.text(draw, (55, 680), f"{int(seconds)//60:02d}:{int(seconds)%60:02d} / {int(self.plan['duration_s'])//60:02d}:{int(self.plan['duration_s'])%60:02d}    GPU energy (NVML) • offline evidence replay", 14)
        return image


def _encode(verified, plan, video, binary, *, audio=None):
    pillow = _pillow()
    painter = _Painter(verified, plan, pillow)
    command = _command(binary, video, plan["duration_s"], audio=audio)
    process = None
    log = video.with_suffix(".ffmpeg.log")
    started = time.monotonic()
    deadline = max(60., plan["duration_s"]*4)
    try:
        with log.open("wb") as errors:
            process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                                       stderr=errors, shell=False)
            for index in range(int(plan["duration_s"]*FPS)):
                if time.monotonic()-started > deadline:
                    raise TimeoutError("Local video rendering exceeded its CPU time limit")
                process.stdin.write(painter.frame(index/FPS).tobytes())
            process.stdin.close()
            process.wait(timeout=max(1, deadline-(time.monotonic()-started)))
        if process.returncode != 0 or not video.is_file() or video.stat().st_size == 0:
            raise RuntimeError("Local ffmpeg encoding failed; storyboard and narration remain available")
    except BaseException:
        if process is not None:
            if process.stdin and not process.stdin.closed:
                try:
                    process.stdin.close()
                except (OSError, BrokenPipeError):
                    pass
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
        video.unlink(missing_ok=True)
        raise
    return {"ffmpeg_argv": command, "render_seconds": time.monotonic()-started, "ffmpeg_log": str(log)}


def generate_demo(study_dir, out_dir, *, ffmpeg=None, duration_s=180, render=True, audio_path=None):
    """Write scripts first, then optionally encode an exact-duration H264 MP4.

    ``render=False`` has no optional media dependencies. Missing dependencies
    and local render failures preserve all narration/storyboard artifacts and
    return an explicit status. An optional local audio file is padded/trimmed
    to the video duration; there is no automatic voice generation.
    """
    if type(duration_s) is not int or not 1 <= duration_s <= 600:
        raise ValueError("Video duration must be an integer from 1 to 600 seconds")
    if type(render) is not bool:
        raise ValueError("render must be boolean")
    verified = verify_study(study_dir)
    root = Path(verified["study_dir"])
    supplied = Path(out_dir)
    if supplied.is_symlink():
        raise ValueError("Demo output must not be a symlink")
    out = supplied.resolve()
    if out.is_relative_to(root):
        raise ValueError("Demo artifacts must remain outside the sealed study")
    out.mkdir(parents=True, exist_ok=True)
    video = out / "servetune-demo.mp4"
    if render and (video.exists() or video.is_symlink()):
        raise FileExistsError("Demo video already exists; preserve it or choose a new output directory")
    plan = _plan(verified, duration_s)
    reports = root.with_name(root.name+"-report")
    plan["chart_links"] = [os.path.relpath(path, out) for path in sorted((reports / "svg").glob("*.svg"))]
    plan["results_link"] = os.path.relpath(reports / "results.md", out) if (reports / "results.md").is_file() else None
    plan["study_dir"] = str(root)
    script_lines = ["# ServeTune narration", "", f"**{plan['persistent_label']}**", "",
                    f"Duration: {duration_s} seconds. Six chapters use the v4 20/25/35/25/50/25 timing ratio.", ""]
    storyboard = ["# ServeTune storyboard", "", f"**{plan['persistent_label']}**", "",
                  "Every rendered frame retains this evidence-state label. Video plots are illustrative exports of recorded values; publication SVGs remain separate.", ""]
    captions, plain, cue = [], [], 0
    for number, row in enumerate(plan["chapters"], 1):
        script_lines += [f"## {_srt_time(row['start_s'])} — {row['title']}", "", row["narration"], ""]
        plain.append(row["narration"])
        words = row["narration"].split()
        chunks = [words[i:i+12] for i in range(0, len(words), 12)]
        for index, chunk in enumerate(chunks):
            cue += 1
            start = row["start_s"] + (row["end_s"]-row["start_s"])*index/len(chunks)
            end = row["start_s"] + (row["end_s"]-row["start_s"])*(index+1)/len(chunks)
            caption = "\n".join(textwrap.wrap(" ".join(chunk), width=44, break_long_words=False))
            captions += [str(cue), f"{_srt_time(start)} --> {_srt_time(end)}", caption, ""]
        storyboard += [f"- **{row['start_s']:.2f}–{row['end_s']:.2f} s / {row['title']}**: "
                       f"{row['key']} panel, actual recorded observations, persistent evidence label."]
    if plan["results_link"]:
        script_lines += [f"[Verified results]({plan['results_link']})", ""]
    storyboard += ["", "## Existing SVG chart references", ""]
    storyboard += [f"- [{Path(path).name}]({path})" for path in plan["chart_links"]]
    if not plan["chart_links"]:
        storyboard.append("No report SVGs were found; generate the offline study report first to add those chart references.")
    paths = {"storyboard": str(out / "storyboard.json"), "storyboard_md": str(out / "storyboard.md"),
             "script": str(out / "narration.md"), "narration_text": str(out / "narration.txt"),
             "captions": str(out / "captions.srt"), "video": None}
    _write(Path(paths["storyboard"]), json.dumps(plan, indent=2, ensure_ascii=False, allow_nan=False)+"\n")
    _write(Path(paths["storyboard_md"]), "\n".join(storyboard)+"\n")
    _write(Path(paths["script"]), "\n".join(script_lines))
    _write(Path(paths["narration_text"]), "\n\n".join(plain)+"\n")
    _write(Path(paths["captions"]), "\n".join(captions))
    result = {"paths": paths, **paths, "duration_s": duration_s, "render_status": "not_requested",
              "synthetic": plan["synthetic"], "result_ready": plan["result_ready"]}
    if not render:
        return result
    try:
        audio = None
        if audio_path is not None:
            audio = Path(audio_path).expanduser()
            if audio.is_symlink() or not audio.is_file() or audio.suffix.casefold() not in {".aif", ".aiff", ".wav", ".mp3", ".m4a", ".flac", ".ogg"}:
                raise ValueError("Audio must be a regular local supported audio file")
            audio = audio.resolve()
        binary = _resolve_ffmpeg(ffmpeg)
        encoded = _encode(verified, plan, video, binary, audio=audio)
    except DemoDependencyError as exc:
        result.update(render_status="dependency_unavailable", error=str(exc))
    except (ValueError, OSError, RuntimeError, TimeoutError, subprocess.TimeoutExpired) as exc:
        result.update(render_status="failed", error_type=type(exc).__name__,
                      error="Local media rendering failed; narration, captions and storyboard were preserved")
    else:
        paths["video"] = str(video)
        result.update(paths=paths, video=str(video), render_status="rendered", **encoded)
    return result
