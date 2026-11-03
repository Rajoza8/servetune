"""Portable, explicit commands. No implicit downloads, API calls or GPU startup."""

from __future__ import annotations

import argparse
from copy import deepcopy
import json
from pathlib import Path
import tarfile

from .artifacts import file_hash, verify, write_json
from .config import DEFAULT, load_config, validate
from .hardware import probe_hardware
from .ledger import Ledger
from .preflight import render_report, run_preflight


PROJECT = Path(__file__).resolve().parents[1]
LEDGER = PROJECT / "runs" / "ledger.json"


def _print(value):
    print(json.dumps(value, indent=2, allow_nan=False))


def main(argv=None):
    parser = argparse.ArgumentParser(description="ServeTune v4 preflight: lightweight on Mac, explicit live GPU operations")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("init", help="Initialize the single, separate ServeTune cumulative ledger once")
    commands.add_parser("budget", help="Read cumulative reservations, estimated usage, and remaining caps")
    commands.add_parser("doctor", help="Read-only GPU/runtime probe; no model download or startup")
    prepare = commands.add_parser("prepare-data", help="Download licensed public GSM8K; freeze calibration prompts and quality splits")
    prepare.add_argument("--out", type=Path, required=True)
    prepare.add_argument("--seed", type=int, default=20261030)
    run = commands.add_parser("preflight", help="Run P1/P1b/P2/P4; P3 is opt-in. Live mode loads weights")
    run.add_argument("--config", type=Path, default=PROJECT / "configs" / "preflight.example.json")
    run.add_argument("--out", type=Path, required=True)
    run.add_argument("--simulate", action="store_true", help="Software fixtures only: no GPU, weights, API, or real-ledger access")
    spark_mode = run.add_mutually_exclusive_group()
    spark_mode.add_argument("--with-spark", action="store_true", help="One paid P3 request, only after hardware gates pass")
    spark_mode.add_argument("--spark-evidence", type=Path,
                            help="Reuse hash-bound settled P3 evidence from the same cumulative ledger; no new paid call")
    run.add_argument("--model-revision", help="Exact 40-character immutable Glimmer Hub revision")
    run.add_argument("--data-dir", type=Path)
    run.add_argument("--dev-baseline-evidence", type=Path,
                     help="Reuse the same verified 150-item bf16 reference from a sealed live run; all performance repeats remain fresh")
    run.add_argument("--max-hours", type=float, help="Allocated session limit; reserves 30 seconds for cleanup, max 50 hours")
    spark = commands.add_parser("spark-check", help="One explicitly paid Meta schema/connectivity check; no GPU required")
    spark.add_argument("--out", type=Path, required=True)
    replay = commands.add_parser("replay", help="Verify sealed evidence and display the preflight report, offline")
    replay.add_argument("run", type=Path)
    export = commands.add_parser("export-run", help="Verify and pack one evidence directory to bring back from a GPU host")
    export.add_argument("run", type=Path)
    export.add_argument("--out", type=Path, required=True)
    bundle = commands.add_parser("bundle", help="Pack code/config/docs for a GPU host; excludes credentials, data and runs")
    bundle.add_argument("--out", type=Path, required=True)
    study_init = commands.add_parser("study-init", help="Freeze a v4 study plan using sealed passing preflight evidence")
    study_init.add_argument("--out", type=Path, required=True)
    study_init.add_argument("--preflight", type=Path)
    study_init.add_argument("--data-dir", type=Path)
    study_init.add_argument("--config", type=Path)
    study_init.add_argument("--simulate", action="store_true")
    study_run = commands.add_parser("study-run", help="Run/resume the declared calibration, map, A/B, search and confirmation")
    study_run.add_argument("study", type=Path)
    study_run.add_argument("--phase", choices=["all", "calibration", "map", "ab", "search", "confirmation"], default="all")
    study_run.add_argument("--max-hours", type=float, required=True, help="Remaining GPU allocation; cleanup and confirmation are reserved")
    study_run.add_argument("--ledger", type=Path, default=LEDGER)
    study_status = commands.add_parser("study-status", help="Read saved study progress without GPU or API calls")
    study_status.add_argument("study", type=Path)
    study_report = commands.add_parser("study-report", help="Verify study evidence and generate an offline dashboard/CSV/report")
    study_report.add_argument("study", type=Path)
    study_report.add_argument("--out", type=Path)
    study_replay = commands.add_parser("study-replay", help="Verify all study evidence offline; no GPU or API required")
    study_replay.add_argument("study", type=Path)
    study_demo = commands.add_parser("study-demo", help="Render a three-minute video from verified evidence, using optional media dependencies")
    study_demo.add_argument("study", type=Path)
    study_demo.add_argument("--out", type=Path, required=True)
    study_demo.add_argument("--ffmpeg", type=Path)
    study_demo.add_argument("--audio", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "init":
            Ledger(LEDGER).initialize()
            _print({"ledger": str(LEDGER), "summary": Ledger(LEDGER).summary()})
        elif args.command == "budget":
            _print(Ledger(LEDGER).summary())
        elif args.command == "doctor":
            result = probe_hardware()
            _print(result)
            return 0 if result["status"] == "pass" else 2
        elif args.command == "prepare-data":
            from .data import prepare_gsm8k
            provenance = prepare_gsm8k(args.out, args.seed)
            _print({"out": str(args.out.resolve()), "upstream_revision": provenance["upstream_revision"],
                    "license": provenance["license"]["spdx"],
                    "counts": {name: value["count"] for name, value in provenance["selection"].items()},
                    "scope": provenance["workload_scope"], "provenance": str(args.out / "provenance.json")})
        elif args.command == "preflight":
            config = load_config(args.config)
            if args.model_revision:
                config["engine"]["model_revision"] = args.model_revision
            if args.data_dir:
                for name in config["data"]:
                    config["data"][name] = str((args.data_dir / f"{name}.json").resolve())
            validate(config)
            result = run_preflight(config, args.out, simulate=args.simulate,
                                   with_spark=args.with_spark, ledger_path=LEDGER,
                                   max_runtime_s=args.max_hours * 3600 if args.max_hours is not None else None,
                                   spark_evidence=args.spark_evidence,
                                   dev_baseline_evidence=args.dev_baseline_evidence)
            print(render_report(result))
            return 0 if result["status"] in ("pass", "simulation_complete") else 2
        elif args.command == "spark-check":
            from .planner import run_spark_check
            args.out.mkdir(parents=True, exist_ok=False)
            result = run_spark_check(LEDGER, args.out)
            _print(result)
            return 0 if result["status"] == "pass" else 2
        elif args.command == "replay":
            result = verify(args.run)
            print(render_report(result))
            print("Evidence manifest verified. No GPU or API calls were made.")
        elif args.command == "export-run":
            result = verify(args.run)
            if args.out.resolve().is_relative_to(args.run.resolve()):
                raise ValueError("Export archive must be outside the sealed evidence directory")
            args.out.parent.mkdir(parents=True, exist_ok=True)
            with tarfile.open(args.out, "x:gz") as archive:
                archive.add(args.run, arcname=args.run.name)
            _print({"archive": str(args.out.resolve()), "sha256": file_hash(args.out),
                    "run_status": result["status"], "evidence_verified": True})
        elif args.command == "bundle":
            if args.out.exists():
                raise FileExistsError("Bundle exists; choose a fresh output path")
            args.out.parent.mkdir(parents=True, exist_ok=True)
            names = ["servetune", "configs", "tests", "scripts", "docs", ".github", ".gitignore",
                     "pyproject.toml", "README.md", "LICENSE", "THIRD_PARTY_NOTICES.md",
                     "BUILT_DURING_HACKATHON.md", "BUILD_BRIEF_V4.txt"]
            with tarfile.open(args.out, "x:gz") as archive:
                for name in names:
                    path = PROJECT / name
                    if not path.exists():
                        continue
                    def safe(info):
                        parts = Path(info.name).parts
                        excluded = ("__pycache__" in parts or info.name.endswith(".pyc")
                                    or any(part.startswith(".env") for part in parts)
                                    or info.issym() or info.islnk())
                        return None if excluded else info
                    archive.add(path, arcname=f"servetune/{name}", filter=safe)
            _print({"bundle": str(args.out.resolve()), "sha256": file_hash(args.out),
                    "includes_model_weights": False, "includes_credentials_or_runs": False})
        elif args.command == "study-init":
            from .study import initialize_study
            protocol = json.loads(args.config.read_text()) if args.config else None
            _print(initialize_study(args.out, args.preflight, args.data_dir, protocol, simulate=args.simulate))
        elif args.command == "study-run":
            from .study import run_study
            result = run_study(args.study, phase=args.phase, max_runtime_s=args.max_hours * 3600,
                               ledger_path=args.ledger)
            _print(result)
            return 0 if result["status"] in ("complete", "simulation_complete", "paused_at_phase_boundary") else 2
        elif args.command == "study-status":
            result = json.loads((args.study / "study.json").read_text())
            result["trial_count"] = len(result.pop("trials", []))
            _print(result)
        elif args.command in ("study-report", "study-replay"):
            from .study_report import generate_report, verify_study
            if args.command == "study-replay":
                checked = verify_study(args.study)
                _print({key: checked.get(key) for key in ("status", "root_manifest_verified", "root_manifest_sha256", "floor", "warnings")}
                       | {"verified_trials": len(checked.get("rows", [])),
                          "headline_rows": len(checked.get("headline_rows", [])), "offline": True})
            else:
                _print(generate_report(args.study, args.out))
        elif args.command == "study-demo":
            from .demo import generate_demo
            result = generate_demo(args.study, args.out, ffmpeg=args.ffmpeg, audio_path=args.audio)
            _print(result)
            return 0 if result.get("render_status") == "rendered" else 2
        return 0
    except (ValueError, OSError, KeyError) as exc:
        # Do not print arbitrary network/HTTP exception bodies or environment values.
        print(f"ServeTune could not complete {args.command}: {type(exc).__name__}. {str(exc) if not hasattr(exc, 'headers') else 'No retry was performed.'}")
        return 2
