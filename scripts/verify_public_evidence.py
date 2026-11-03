#!/usr/bin/env python3
"""Verify the curated v4 download, its original payload hashes and native scores.

This checks a derived publication snapshot. It does not attest that the new file
set has the original experiment's root seal. No GPU, credentials or network is
used. Temporary extraction requires approximately 1.2 GB of disk space.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import shutil
import sys
import tarfile
import tempfile


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def record(path):
    return {"bytes": path.stat().st_size, "sha256": sha256(path)}


def load(path):
    return json.loads(path.read_text())


def safe_name(name):
    path = PurePosixPath(name)
    return bool(name) and not path.is_absolute() and ".." not in path.parts


def verify(results_dir):
    evidence = results_dir / "evidence"
    inventory = load(evidence / "archive-manifest.json")
    receipt = load(evidence / "curation-receipt.json")
    original = load(evidence / "original-archive-manifest.json")
    require(inventory["artifact_scope"] == "curated_public_snapshot", "Unexpected archive scope")
    require(receipt["artifact_scope"] == "curated_public_snapshot", "Unexpected curation scope")
    require(receipt["original_root_seal_applies_to_derived_package"] is False,
            "The derived snapshot must not claim the original root seal")
    require(sha256(evidence / "original-archive-manifest.json")
            == receipt["original_archive_inventory_sha256"], "Original inventory hash mismatch")
    require(sha256(evidence / "original-study-manifest.json")
            == receipt["original_study_manifest_sha256"], "Original study manifest hash mismatch")
    require(original["archive_sha256"] == receipt["original_archive_sha256"]
            == inventory["original_archive_sha256"], "Original archive identity disagrees")
    require(inventory["archive_sha256"] == receipt["derived_archive_sha256"],
            "Derived archive identity disagrees")

    removed = receipt["removed_original_members"]
    require(set(inventory["files"]) == set(original["files"]) - set(removed),
            "Curated membership differs from the declared removals")
    require(set(receipt["changed_original_members"]) == {"study/manifest.json"},
            "Only the outer publication manifest may change")
    for name, excluded in removed.items():
        require({key: excluded[key] for key in ("bytes", "sha256")} == original["files"][name],
                f"Removed member commitment disagrees: {name}")
    for name, current in inventory["files"].items():
        require(safe_name(name), f"Unsafe inventory path: {name}")
        if name != "study/manifest.json":
            require(current == original["files"][name], f"Original payload hash changed: {name}")
    require(inventory["files"]["study/manifest.json"]["sha256"]
            == receipt["derived_study_manifest_sha256"], "Derived manifest identity disagrees")

    with tempfile.TemporaryDirectory(prefix="servetune-public-replay-") as temporary:
        work = Path(temporary)
        archive = work / "public-evidence.tar.gz"
        with archive.open("wb") as writer:
            seen_parts = set()
            for part in inventory["parts"]:
                name = part["path"]
                require(safe_name(name) and PurePosixPath(name).name == name and name not in seen_parts,
                        "Invalid or duplicate archive part")
                seen_parts.add(name)
                path = evidence / name
                require(record(path) == {key: part[key] for key in ("bytes", "sha256")},
                        f"Archive part mismatch: {name}")
                with path.open("rb") as reader:
                    shutil.copyfileobj(reader, writer)
        require(sha256(archive) == inventory["archive_sha256"], "Reassembled archive hash mismatch")
        payload = work / "payload"
        payload.mkdir()
        seen = set()
        with tarfile.open(archive, "r:gz") as tar:
            for member in tar:
                name = member.name
                require(member.isfile() and safe_name(name) and name not in seen
                        and name in inventory["files"], "Unexpected or duplicate archive member")
                path = payload / name
                path.parent.mkdir(parents=True, exist_ok=True)
                with tar.extractfile(member) as reader, path.open("wb") as writer:
                    shutil.copyfileobj(reader, writer)
                require(record(path) == inventory["files"][name], f"Archive payload mismatch: {name}")
                seen.add(name)
        require(seen == set(inventory["files"]), "An archive member is missing")
        manifest = load(payload / "study/manifest.json")
        require(manifest["artifact_scope"] == "curated_public_snapshot", "Study scope is not labelled")
        require(manifest["curation"]["original_study_manifest_sha256"]
                == receipt["original_study_manifest_sha256"], "Study provenance disagrees")
        require(manifest["curation"]["original_root_seal_preserved"] is False,
                "The publication manifest must disclose its new root seal")
        # The original manifest is evidence about the historical file set. Every
        # retained original study payload must still have that historical hash.
        original_study = load(evidence / "original-study-manifest.json")
        for name, commitment in original_study["files"].items():
            if "study/" + name in removed:
                continue
            expected = commitment["sha256"] if isinstance(commitment, dict) else commitment
            require(sha256(payload / "study" / name) == expected,
                    f"Original study payload changed: {name}")

        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
        from servetune.study_report import verify_study

        native = verify_study(payload / "study")
        compared = {key: native[key] for key in receipt["comparison_fields"]}
        encoded = json.dumps(compared, sort_keys=True, ensure_ascii=False,
                             separators=(",", ":"), allow_nan=False).encode()
        require(hashlib.sha256(encoded).hexdigest() == receipt["scientific_comparison_sha256"],
                "Native results differ from the original scientific replay")
        live = sum(row["live_observation"] for row in native["rows"])
        headline = len(native["headline_rows"])
        require(live == receipt["live_trial_observations"] == 111, "Live trial denominator changed")
        require(headline == receipt["fresh_confirmation_observations"] == 10,
                "Fresh confirmation denominator changed")
        return {"artifact_scope": "curated_public_snapshot", "verified_archive_members": len(seen),
                "retained_payloads_match_original": True, "native_results_match_original": True,
                "live_trial_observations": live, "fresh_confirmation_observations": headline,
                "derived_study_manifest_sha256": native["root_manifest_sha256"],
                "original_root_seal_applies_to_derived_package": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("results_dir", nargs="?", type=Path,
                        default=Path(__file__).resolve().parents[1] / "results/20261030")
    args = parser.parse_args()
    print(json.dumps(verify(args.results_dir.resolve()), indent=2))


if __name__ == "__main__":
    main()
