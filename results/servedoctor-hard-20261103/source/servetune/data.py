"""Freeze licensed GSM8K calibration/evaluation inputs at one upstream revision.

This prepares math-only calibration data, not a representative mixed serving
workload. It performs public HTTPS reads without API keys and makes no model
calls. The final split is written for later confirmation; tuning must not read
its answers or score candidates against it.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import random
import re
import unicodedata
import urllib.error
import urllib.request

from .artifacts import file_hash, timestamp, write_json
from .quality import extract_answer, normalize_answer, validate_dataset_manifest


COMMIT_URL = "https://api.github.com/repos/openai/grade-school-math/commits/master"
RAW_ROOT = "https://raw.githubusercontent.com/openai/grade-school-math"
MAX_DOWNLOAD_BYTES = 10 * 1024 * 1024
_SHA = re.compile(r"[0-9a-f]{40}\Z")


class DatasetError(ValueError):
    """Public source data cannot be frozen under the declared protocol."""


class _NoRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise DatasetError("Public dataset redirect refused; update the declared source explicitly")


def _download(url: str) -> bytes:
    request = urllib.request.Request(
        url, headers={"User-Agent": "ServeTune-preflight/0.1",
                      "Accept": "application/vnd.github+json" if url == COMMIT_URL else "text/plain"},
        method="GET",
    )
    opener = urllib.request.build_opener(_NoRedirects())
    try:
        with opener.open(request, timeout=30) as response:
            raw = response.read(MAX_DOWNLOAD_BYTES + 1)
    except urllib.error.HTTPError as exc:
        raise DatasetError(f"Public dataset fetch failed with HTTP {exc.code}; no automatic retry") from None
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise DatasetError(f"Public dataset fetch failed ({type(exc).__name__}); no automatic retry") from None
    if len(raw) > MAX_DOWNLOAD_BYTES:
        raise DatasetError("Public dataset source exceeds the 10 MiB download limit")
    return raw


def _unique_object(pairs):
    obj = {}
    for key, value in pairs:
        if key in obj:
            raise DatasetError("Duplicate JSON field in public dataset source")
        obj[key] = value
    return obj


def _json(raw: bytes, label: str):
    try:
        return json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_object)
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError):
        raise DatasetError(f"Invalid UTF-8 JSON in {label}") from None


def _question_key(question: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", question).casefold().split())


def _parse_jsonl(raw: bytes, split: str) -> list[dict]:
    try:
        lines = raw.decode("utf-8").splitlines()
    except UnicodeDecodeError:
        raise DatasetError(f"Invalid UTF-8 in {split} JSONL") from None
    records = []
    for index, line in enumerate(lines):
        if not line.strip():
            continue
        row = _json(line.encode("utf-8"), f"{split} line {index + 1}")
        if not isinstance(row, dict):
            raise DatasetError(f"Expected an object in {split} line {index + 1}")
        question, solution = row.get("question"), row.get("answer")
        if not isinstance(question, str) or not question.strip():
            raise DatasetError(f"Missing question in {split} line {index + 1}")
        if not isinstance(solution, str) or "####" not in solution:
            raise DatasetError(f"Missing explicit final answer in {split} line {index + 1}")
        answer = extract_answer(solution, allow_fallback=False)
        if answer is None:
            raise DatasetError(f"Empty final answer in {split} line {index + 1}")
        try:
            normalize_answer(answer)
        except ValueError:
            raise DatasetError(f"Invalid final answer in {split} line {index + 1}") from None
        records.append({"id": f"gsm8k-{split}-{index}", "prompt": question,
                        "answer": answer, "source_index": index})
    if not records:
        raise DatasetError(f"The {split} dataset is empty")
    return records


def _pick(records: list[dict], count: int, rng: random.Random, excluded: set[str]) -> list[dict]:
    shuffled = list(records)
    rng.shuffle(shuffled)
    chosen = []
    for record in shuffled:
        key = _question_key(record["prompt"])
        if key in excluded:
            continue
        chosen.append(record)
        excluded.add(key)
        if len(chosen) == count:
            return chosen
    raise DatasetError(f"Not enough distinct non-overlapping questions to select {count} items")


def prepare_gsm8k(out_dir, seed: int = 20261030, *, transport=None) -> dict:
    """Create a new evidence directory with 150 dev, 300 final, and 12 prompts.

    ``transport(url) -> bytes`` is an optional deterministic test injection.
    No network requests are made when the output directory already exists.
    Source revision, complete raw source files, license, indices, and hashes
    are preserved. Nothing is overwritten, including a partially written run.
    """
    if type(seed) is not int or not 0 <= seed < 2**63:
        raise DatasetError("seed must be a nonnegative integer below 2**63")
    root = Path(out_dir)
    if root.exists() or root.is_symlink():
        raise FileExistsError("Dataset output directory already exists; choose a fresh path")
    fetch = transport or _download

    def get(url: str) -> bytes:
        raw = fetch(url)
        if not isinstance(raw, bytes) or not raw or len(raw) > MAX_DOWNLOAD_BYTES:
            raise DatasetError("Source must be nonempty bytes within the 10 MiB limit")
        return raw

    commit_raw = get(COMMIT_URL)
    commit = _json(commit_raw, "upstream revision")
    revision = commit.get("sha") if isinstance(commit, dict) else None
    if not isinstance(revision, str) or not _SHA.fullmatch(revision):
        raise DatasetError("Upstream revision must be a full lowercase 40-character Git SHA")
    urls = {
        "LICENSE": f"{RAW_ROOT}/{revision}/LICENSE",
        "source/train.jsonl": f"{RAW_ROOT}/{revision}/grade_school_math/data/train.jsonl",
        "source/test.jsonl": f"{RAW_ROOT}/{revision}/grade_school_math/data/test.jsonl",
    }
    raw_files = {name: get(url) for name, url in urls.items()}
    try:
        license_text = raw_files["LICENSE"].decode("utf-8")
    except UnicodeDecodeError:
        raise DatasetError("Upstream license is not UTF-8") from None
    if "MIT License" not in license_text or "Permission is hereby granted" not in license_text:
        raise DatasetError("The pinned upstream source does not declare the expected MIT license")
    train = _parse_jsonl(raw_files["source/train.jsonl"], "train")
    test = _parse_jsonl(raw_files["source/test.jsonl"], "test")
    rng = random.Random(seed)
    excluded = set()
    selected_dev = _pick(train, 150, rng, excluded)
    selected_final = _pick(test, 300, rng, excluded)
    selected_prompts = _pick(train, 12, rng, excluded)
    public_item = lambda row: {key: row[key] for key in ("id", "prompt", "answer")}
    dev = [public_item(row) for row in selected_dev]
    final = [public_item(row) for row in selected_final]
    prompts = [row["prompt"] for row in selected_prompts]
    manifest = validate_dataset_manifest(dev, final)

    # Exclusive creation remains the final guard against another process racing
    # the initial existence check while public source downloads were in flight.
    root.mkdir(parents=True, exist_ok=False)
    (root / "source").mkdir()
    raw_files["source/commit.json"] = commit_raw
    urls["source/commit.json"] = COMMIT_URL
    for name, raw in raw_files.items():
        with (root / name).open("xb") as stream:
            stream.write(raw)
    write_json(root / "prompts.json", prompts)
    write_json(root / "dev.json", dev)
    write_json(root / "final.json", final)
    files = {name: file_hash(root / name) for name in [*raw_files, "prompts.json", "dev.json", "final.json"]}
    provenance = {
        "schema_version": 1,
        "created_at": timestamp(),
        "source": "OpenAI grade-school-math / GSM8K",
        "upstream_repository": "https://github.com/openai/grade-school-math",
        "upstream_revision": revision,
        "seed": seed,
        "license": {"spdx": "MIT", "file": "LICENSE", "url": urls["LICENSE"],
                    "sha256": files["LICENSE"]},
        "source_files": {
            name: {"url": urls[name], "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}
            for name, raw in raw_files.items()
        },
        "selection": {
            "dev": {"source_split": "train", "count": 150,
                    "source_indices_zero_based": [row["source_index"] for row in selected_dev]},
            "final": {"source_split": "test", "count": 300,
                      "source_indices_zero_based": [row["source_index"] for row in selected_final]},
            "performance_prompts": {"source_split": "train", "count": 12,
                                    "source_indices_zero_based": [row["source_index"] for row in selected_prompts]},
        },
        "workload_scope": "math-only calibration prompts; not a representative mixed serving workload",
        "final_split_policy": "freeze now; do not load final answers for planner prompts or tuning evaluation; use only at final confirmation",
        "overlap_policy": "dev, final, and performance prompts have distinct normalized questions; dev and final have disjoint IDs",
        "quality_manifest": manifest,
        "files_sha256": files,
    }
    write_json(root / "provenance.json", provenance)
    return provenance
