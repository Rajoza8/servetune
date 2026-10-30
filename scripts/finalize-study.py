#!/usr/bin/env python3
"""Create the offline delivery from downloaded, verified study evidence."""
from pathlib import Path
import argparse
import hashlib
import json
import sys

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from servetune.study_report import generate_report, verify_study
from servetune.demo import generate_demo


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--study", type=Path, required=True)
    parser.add_argument("--out", type=Path, default=PROJECT / "reports/full-v4-20261030")
    parser.add_argument("--no-video", action="store_true")
    args = parser.parse_args()
    checked = verify_study(args.study)
    reports = generate_report(args.study, args.out)
    media = generate_demo(args.study, args.out / "demo", render=not args.no_video)
    files = {}
    for path in sorted(args.out.rglob("*")):
        if path.is_file() and path.name != "delivery.json":
            value = hashlib.sha256()
            with path.open("rb") as stream:
                for block in iter(lambda: stream.read(1024 * 1024), b""):
                    value.update(block)
            files[path.relative_to(args.out).as_posix()] = value.hexdigest()
    result = {"study_status": checked["status"],
              "root_manifest_verified": checked["root_manifest_verified"],
              "root_manifest_sha256": checked.get("root_manifest_sha256"),
              "report": reports, "media": media, "files_sha256": files,
              "provider_calls": 0, "gpu_required": False}
    (args.out / "delivery.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"out": str(args.out.resolve()), "study_status": checked["status"],
                      "video_status": media["render_status"], "files": len(files)}, indent=2))


if __name__ == "__main__":
    main()
