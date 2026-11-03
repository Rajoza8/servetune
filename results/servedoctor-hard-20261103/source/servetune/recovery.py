"""Small, sanitized recovery archives; never a model cache or rental session.

This module performs local file operations only. It neither starts nor stops
instances, books replacements, copies SSH credentials, or deletes source data.
"""

from __future__ import annotations

from datetime import datetime, timezone
import gzip
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import tarfile


MAX_FILE_BYTES = 20_000_000
MAX_TOTAL_BYTES = 100_000_000
_TOP_FILES = ("pyproject.toml", "README.md", "BUILD_BRIEF_V4.txt",
              "BUILT_DURING_HACKATHON.md", "LICENSE", "LICENSE.md")
_DATA_FILES = ("prompts.json", "dev.json", "final.json", "provenance.json",
               "LICENSE", "LICENSE.md", "source/train.jsonl", "source/test.jsonl",
               "source/commit.json")
_TEXT_SUFFIXES = frozenset({".py", ".json", ".jsonl", ".csv", ".md", ".txt", ".log", ".sh", ".toml"})
_SECRET_KEY = re.compile(
    r"api[_-]?key|secret|password|passwd|authorization|cookie|credential|"
    r"access[_-]?token|refresh[_-]?token|hf[_-]?token|private[_-]?key|ssh[_-]?key", re.I)
_SECRET_FILE = re.compile(r"(?:^|[_.-])(?:ssh|session|secret|credential|auth|token)(?:[_.-]|$)", re.I)
_PRIVATE_BLOCK = re.compile(r"-----BEGIN [^-\n]*PRIVATE KEY-----.*?-----END [^-\n]*PRIVATE KEY-----", re.S)
_BEARER = re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]+", re.I)
_KNOWN_TOKEN = re.compile(r"\b(?:hf_[A-Za-z0-9]{20,}|sk[-_][A-Za-z0-9_-]{16,})\b")
_USERINFO = re.compile(r"(https?://)[^\s/@]+@", re.I)
_ENV_ASSIGNMENT = re.compile(
    r"\b((?:[A-Z0-9_]*(?:API_KEY|SECRET|PASSWORD|ACCESS_TOKEN|REFRESH_TOKEN|HF_TOKEN|PRIVATE_KEY)))"
    r"\s*=\s*(?:\"[^\"\n]*\"|'[^'\n]*'|[^\s\n]+)")


class RecoveryError(ValueError):
    pass


def _hash(raw):
    return hashlib.sha256(raw).hexdigest()


def _json(value):
    try:
        return (json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False,
                           allow_nan=False) + "\n").encode()
    except (TypeError, ValueError, RecursionError) as exc:
        raise RecoveryError("Recovery manifests must contain finite JSON") from exc


def _clean_text(text):
    text = _PRIVATE_BLOCK.sub("[REDACTED PRIVATE KEY]", text)
    text = _BEARER.sub("Bearer [REDACTED]", text)
    text = _KNOWN_TOKEN.sub("[REDACTED TOKEN]", text)
    text = _USERINFO.sub(r"\1[REDACTED]@", text)
    return _ENV_ASSIGNMENT.sub(lambda match: match[1] + "=[REDACTED]", text)


def _sanitize(value):
    if isinstance(value, dict):
        return {str(key): "[REDACTED]" if _SECRET_KEY.search(str(key)) else _sanitize(item)
                for key, item in value.items()}
    if isinstance(value, list):
        return [_sanitize(item) for item in value]
    if isinstance(value, str):
        return _clean_text(value)
    return value


def _safe_name(name):
    path = PurePosixPath(name)
    if path.is_absolute() or not path.parts or any(part in {"", ".", ".."} for part in path.parts):
        raise RecoveryError("Recovery archive names must be relative without traversal")
    return path.as_posix()


def _excluded(path):
    for part in path.parts:
        lower = part.casefold()
        if (lower.startswith(".env") or lower in {".git", ".ssh", ".cache", "__pycache__", ".venv", "ops"}
                or lower.startswith("id_rsa") or lower.startswith("id_ed25519")
                or _SECRET_FILE.search(lower)):
            return True
    return path.suffix.casefold() in {".pem", ".key", ".pub", ".safetensors", ".bin", ".pt", ".pth", ".gguf"}


def _has_symlink(path, root):
    current = path
    while current != root:
        if current.is_symlink():
            return True
        if current == current.parent:
            raise RecoveryError("Source is outside the project")
        current = current.parent
    return root.is_symlink()


def _read_text_file(path):
    if path.stat().st_size >= MAX_FILE_BYTES:
        raise RecoveryError(f"Recovery source file exceeds the {MAX_FILE_BYTES}-byte limit")
    with path.open("rb") as stream:
        raw = stream.read(MAX_FILE_BYTES)
    if len(raw) >= MAX_FILE_BYTES:
        raise RecoveryError("Recovery source file grew beyond its limit")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise RecoveryError("Only bounded UTF-8 source/data/evidence files may be archived") from exc
    if path.suffix.casefold() == ".json":
        try:
            value = json.loads(text)
            sanitized = _sanitize(value)
            # Preserve original bytes/hashes when no redaction is needed, so
            # frozen data provenance and original preflight seals remain useful.
            content = raw if sanitized == value else _json(sanitized)
        except (ValueError, RecursionError) as exc:
            raise RecoveryError("Invalid JSON in a recovery source") from exc
    elif path.suffix.casefold() == ".jsonl":
        try:
            values = [json.loads(line) for line in text.splitlines() if line.strip()]
            sanitized = [_sanitize(value) for value in values]
            content = raw if sanitized == values else (
                "".join(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                   separators=(",", ":"), allow_nan=False) + "\n"
                        for value in sanitized)).encode()
        except (ValueError, RecursionError) as exc:
            raise RecoveryError("Invalid JSONL in a recovery source") from exc
    else:
        content = _clean_text(text).encode()
    return raw, content


def build_recovery_bundle(project_dir, output_path, *, environment_manifest: dict,
                          model_manifest: dict, run_paths=None) -> dict:
    """Build a fresh ``.tar.gz`` from allowlisted project and preflight files.

    Only explicit run roots containing both preflight.json and manifest.json
    are included, even when nested below an operations directory. Frozen data
    directories must declare a nonempty license in provenance.json. Manifests
    are sanitized as a defensive boundary, not a substitute for supplying an
    allowlisted environment inventory rather than a raw environment dump.

    The export's file manifest is authoritative for sanitized payloads. Original
    run hashes can differ after redaction or omission of credential files.
    """
    root = Path(project_dir).absolute()
    if root.is_symlink() or not root.is_dir():
        raise RecoveryError("Project must be an existing nonsymlink directory")
    provided_root = root
    root = root.resolve()
    output = Path(output_path).absolute()
    if output.exists() or output.is_symlink():
        raise FileExistsError("Recovery archive already exists; nothing is overwritten")
    if output.suffixes[-2:] != [".tar", ".gz"]:
        raise RecoveryError("Use a .tar.gz recovery output path")
    if type(environment_manifest) is not dict or type(model_manifest) is not dict:
        raise RecoveryError("Environment and model manifests must be objects")
    candidates = set()
    omitted = []

    for name in _TOP_FILES:
        candidates.add(root / name)
    for directory, suffixes in (("servetune", {".py"}),
                                ("configs", {".json"}), ("scripts", {".sh", ".py"})):
        base = root / directory
        if base.exists() and not base.is_symlink():
            for path in base.rglob("*"):
                if path.suffix.casefold() in suffixes:
                    candidates.add(path)
    data = root / "data"
    if data.exists() and not data.is_symlink():
        for directory in data.iterdir():
            if not directory.is_dir() or directory.is_symlink():
                continue
            provenance = directory / "provenance.json"
            if not provenance.is_file() or provenance.is_symlink():
                continue
            _, sanitized = _read_text_file(provenance)
            document = json.loads(sanitized)
            if (type(document) is not dict or not document.get("license")
                    or document.get("origin") == "synthetic_fixture"):
                continue
            candidates.update(directory / name for name in _DATA_FILES)
    runs_root = root / "runs"
    for value in (() if run_paths is None else run_paths):
        path = Path(value)
        if not path.is_absolute():
            path = root / path
        elif path.is_relative_to(provided_root):
            # Normalize system-level aliases such as macOS /var -> /private/var
            # without resolving symlinks inside the project evidence tree.
            path = root / path.relative_to(provided_root)
        path = path.absolute()
        if path.is_relative_to(root):
            _safe_name(path.relative_to(root).as_posix())
        if (not path.is_relative_to(runs_root) or _has_symlink(path, root)
                or not path.is_dir() or not (path / "preflight.json").is_file()
                or not (path / "manifest.json").is_file()):
            raise RecoveryError("Explicit runs must be preflight evidence directories under project/runs")
        for member in path.rglob("*"):
            if member.suffix.casefold() in _TEXT_SUFFIXES:
                candidates.add(member)
    ledger = runs_root / "ledger.json"
    if not ledger.is_file() or _has_symlink(ledger, root):
        raise RecoveryError("A regular cumulative runs/ledger.json is required for migration")
    candidates.add(ledger)

    payload, manifest = {}, {}
    total = 0

    def include(name, content, *, original=None):
        nonlocal total
        name = _safe_name(name)
        if name in payload:
            raise RecoveryError("Duplicate recovery archive member")
        if len(content) >= MAX_FILE_BYTES:
            raise RecoveryError("Sanitized recovery member exceeds the per-file limit")
        total += len(content)
        if total >= MAX_TOTAL_BYTES:
            raise RecoveryError("Recovery payload exceeds the 100 MB total limit")
        payload[name] = content
        record = {"sha256": _hash(content), "bytes": len(content)}
        if original is not None:
            record.update(source_sha256=_hash(original), sanitized=original != content)
        manifest[name] = record

    for path in sorted(candidates):
        relative = path.relative_to(root)
        if (_excluded(relative) or _has_symlink(path, root) or not path.is_file()
                or not path.resolve().is_relative_to(root)):
            omitted.append(relative.as_posix())
            continue
        raw, content = _read_text_file(path)
        include("project/" + relative.as_posix(), content, original=raw)

    environment = _sanitize(environment_manifest)
    model = _sanitize(model_manifest)
    include("recovery/environment.json", _json(environment))
    include("recovery/model-cache-manifest.json", _json(model))
    guidance = """# ServeTune recovery bundle

This is a sanitized source/data/evidence export, not a machine image or model cache.

1. Verify every payload's SHA256 against recovery/file-manifest.json before running it.
2. Recreate the GPU environment from recovery/environment.json. Use its exact pinned
   container image digest, driver/CUDA compatibility, and package versions. If the
   inventory omits a digest or version, record that limitation and resolve it before
   comparing new measurements; this bundle does not invent environment pins.
3. Restore project/ into a fresh workspace. Install the source with
   `python3 -m pip install -e '.[gpu]'` inside the selected pinned environment.
   Transfer credentials separately through the environment; none are bundled.
4. Restore the recorded model ID at the exact revision in
   recovery/model-cache-manifest.json. MODEL WEIGHTS ARE NOT INCLUDED. Reuse a
   separately verified existing cache copy or redownload the pinned weights. Charge
   all download, setup, and transfer costs to the approved rental budget.
5. Keep project/runs/ledger.json as the same cumulative ServeTune ledger. Never
   initialize a new allowance merely because the GPU or workspace changed.
6. Use the frozen data, scorer, trace, and configuration hashes. Repeat hardware,
   identity, telemetry, and noise preflight on the destination. Measurements from
   different physical GPUs cannot be combined into one same-machine comparison.

Only explicitly selected preflight runs are exported. Rental/SSH sessions, operations
folders, credentials, symlinks, and model weights are excluded. Original run manifests
may no longer verify after credential redaction or omitted auth files; use this
export's file-manifest.json for the exact exported payload and retain originals on
the stopped instance's disk until the recovery copy and migration decision are verified.

Creating this archive does not authorize another rental or destruction of the source.
Ask the user before stopping the instance. Destroy only after a verified copy and
a concrete cheaper replication comparison within the user's authorization.
"""
    include("REBUILD.md", guidance.encode())
    export_manifest = {"schema_version": 1, "kind": "servetune_sanitized_recovery",
                       "created_at": datetime.now(timezone.utc).isoformat(),
                       "files": manifest, "manifest_excludes_itself": True,
                       "weights_included": False, "omitted_paths": sorted(omitted),
                       "source_scope": "allowlisted source/config/scripts, licensed frozen data, explicit preflight runs, cumulative ledger"}
    manifest_bytes = _json(export_manifest)
    if len(manifest_bytes) >= MAX_FILE_BYTES:
        raise RecoveryError("Recovery manifest exceeds its size limit")
    output.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(output, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            with gzip.GzipFile(filename="", mode="wb", fileobj=stream, mtime=0) as compressed:
                with tarfile.open(fileobj=compressed, mode="w|", format=tarfile.PAX_FORMAT) as archive:
                    for name, content in [*sorted(payload.items()),
                                          ("recovery/file-manifest.json", manifest_bytes)]:
                        info = tarfile.TarInfo(_safe_name(name))
                        info.size, info.mtime = len(content), 0
                        info.uid = info.gid = 0
                        info.uname = info.gname = ""
                        info.mode = 0o755 if name.endswith(".sh") else 0o644
                        archive.addfile(info, io.BytesIO(content))
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException:
        output.unlink(missing_ok=True)
        raise
    return {"archive": str(output), "archive_sha256": _hash(output.read_bytes()),
            "archive_bytes": output.stat().st_size, "payload_bytes": total,
            "files": len(payload) + 1, "weights_included": False,
            "manifest": "recovery/file-manifest.json", "omitted_paths": sorted(omitted)}
