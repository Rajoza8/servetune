"""ServeDoctor command line. GPU commands need vLLM, NVML and the pinned Glimmer revision."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import uuid

from .scenarios import build_prompt_pools, load_questions, write_study

ROOT = Path(__file__).resolve().parents[1]
ARMS = ["rules", "glimmer", "spark", "wonder", "glimmer_to_spark", "glimmer_to_wonder"]


def _serving(args):
    return {"model_id": args.model_id, "model_revision": args.model_revision, "port": args.port,
            "gpu_index": args.gpu_index, "startup_timeout_s": 900, "request_timeout_s": 120, "dtype": args.dtype}


def _engine_factory(config, path, dtype):
    from servetune.engine import ManagedEngine
    return ManagedEngine(config, path, dtype)


def _gpu_factory(index):
    from .telemetry import GpuSampler
    return lambda: GpuSampler(index).start()


def _study(path):
    return json.loads(Path(path).read_text())


def _pools(study, data_dir):
    return build_prompt_pools(load_questions(data_dir), study["prompt_tokens"], study["seed"])


def _gpu_args(parser):
    parser.add_argument("--data-dir", default="data/gsm8k")
    parser.add_argument("--model-id", default="meta-models/Muse-Glimmer-30B")
    parser.add_argument("--model-revision", required=True)
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--gpu-index", type=int, default=0)
    parser.add_argument("--dtype", default="bf16", choices=["bf16", "fp8"])


def _clients(args, arms, glimmer_url=None):
    from .evaluate import expert_of
    from .llm import Ledger, ModelClient
    experts = {expert_of(a) for a in arms} - {None}
    needs_glimmer = any(a == "glimmer" or a.startswith("glimmer_to_") for a in arms)
    paid = bool(experts) or (args.glimmer == "baseten" and needs_glimmer)
    ledger = Ledger(args.ledger) if paid else None
    clients = {expert: ModelClient(expert, ledger=ledger) for expert in experts}
    if needs_glimmer:
        if args.glimmer == "baseten":
            clients["glimmer"] = ModelClient("glimmer-baseten", ledger=ledger)
        else:
            clients["glimmer"] = ModelClient("glimmer-local", base_url=glimmer_url)
    return clients, ledger


def main(argv=None):
    parser = argparse.ArgumentParser(prog="servedoctor", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("ledger-init", help="Create the separate ServeDoctor ledger (Meta $50, Baseten $20)")
    p.add_argument("--ledger", default="runs/servedoctor-ledger.json")

    p = sub.add_parser("calibrate", help="GPU: estimate capacity_rps for the base workload")
    _gpu_args(p)
    p.add_argument("--study", default=str(ROOT / "configs" / "servedoctor.json"))
    p.add_argument("--rates", default="2,4,6,8,10,12,14")
    p.add_argument("--seconds", type=int, default=60)
    p.add_argument("--out", required=True)

    p = sub.add_parser("generate", help="Freeze scenarios and sealed answer keys")
    p.add_argument("--study", default=str(ROOT / "configs" / "servedoctor.json"))
    p.add_argument("--capacity-rps", type=float)
    p.add_argument("--calibration")
    p.add_argument("--out", required=True)

    p = sub.add_parser("record", help="GPU: record incidents (grouped by engine config)")
    _gpu_args(p)
    p.add_argument("--study-dir", required=True)
    p.add_argument("--split", choices=["dev", "test", "reference"])
    p.add_argument("--ids")

    p = sub.add_parser("evaluate", help="Replay recorded incidents to agent arms")
    p.add_argument("--study-dir", required=True)
    p.add_argument("--arms", default=",".join(ARMS))
    p.add_argument("--split", choices=["dev", "test"])
    p.add_argument("--ledger", default="runs/servedoctor-ledger.json")
    p.add_argument("--glimmer", choices=["local", "baseten"], default="local")
    p.add_argument("--glimmer-url", default="http://127.0.0.1:8000/v1")
    p.add_argument("--start-glimmer", action="store_true", help="GPU: start a healthy Glimmer server for this run")
    p.add_argument("--glimmer-max-model-len", type=int, default=8192,
                   help="Dedicated evaluation server context, including the diagnosis output budget")
    p.add_argument("--model-id", default="meta-models/Muse-Glimmer-30B")
    p.add_argument("--model-revision")
    p.add_argument("--port", type=int, default=8000)
    p.add_argument("--gpu-index", type=int, default=0)
    p.add_argument("--dtype", default="bf16")

    p = sub.add_parser("score", help="Score decisions against sealed answers")
    p.add_argument("--study-dir", required=True)
    p.add_argument("--split", choices=["dev", "test"])

    p = sub.add_parser("report", help="Write report.html and report.json")
    p.add_argument("--study-dir", required=True)

    p = sub.add_parser("live", help="GPU: closed-loop run where an arm acts and recovery is verified")
    _gpu_args(p)
    p.add_argument("--study-dir", required=True)
    p.add_argument("--id", required=True)
    p.add_argument("--arm", choices=ARMS, default="glimmer_to_spark")
    p.add_argument("--ledger", default="runs/servedoctor-ledger.json")
    p.add_argument("--glimmer", choices=["local", "baseten"], default="local")
    p.add_argument("--out")

    p = sub.add_parser("simulate", help="Synthetic rehearsal study (never a result)")
    p.add_argument("--out", required=True)
    p.add_argument("--capacity-rps", type=float, default=10)

    args = parser.parse_args(argv)

    if args.command == "ledger-init":
        from .llm import Ledger
        Ledger(args.ledger).initialize()
        print(json.dumps(Ledger(args.ledger).summary(), indent=2))
    elif args.command == "calibrate":
        from .record import calibrate
        study = _study(args.study)
        rates = [float(x) for x in args.rates.split(",")]
        result = calibrate(serving=_serving(args), study=study, pools=_pools(study, args.data_dir),
                           out_dir=args.out, engine_factory=_engine_factory, rates=rates, seconds=args.seconds)
        print(json.dumps({"capacity_rps": result["capacity_rps"]}, indent=2))
    elif args.command == "generate":
        study = _study(args.study)
        if args.calibration:
            study["capacity_rps"] = json.loads(Path(args.calibration).read_text())["capacity_rps"]
        if args.capacity_rps:
            study["capacity_rps"] = args.capacity_rps
        out = Path(args.out)
        commitment = write_study(study, out)
        (out / "study.json").write_text(json.dumps(study, indent=2) + "\n")
        print(json.dumps(commitment, indent=2))
    elif args.command == "record":
        from .record import record_study
        root = Path(args.study_dir)
        study = _study(root / "study.json")
        scenarios = json.loads((root / "scenarios.json").read_text())["scenarios"]
        ids = set(args.ids.split(",")) if args.ids else None
        if args.split:
            ids = (ids or {s["id"] for s in scenarios}) & {s["id"] for s in scenarios if s["split"] == args.split}
        record_study(scenarios, serving=_serving(args), pools=_pools(study, args.data_dir), out_dir=root,
                     engine_factory=_engine_factory, gpu_factory=_gpu_factory(args.gpu_index), ids=ids)
    elif args.command == "evaluate":
        from .evaluate import evaluate
        arms = args.arms.split(",")
        root = Path(args.study_dir)
        answers = json.loads((root / "answers" / "answer_keys.json").read_text())["answers"] if args.split else None
        study = _study(root / "study.json") if (root / "study.json").exists() else {"timing": {"checkpoint_s": 30}}
        engine, engine_dir = None, None
        try:
            if args.start_glimmer:
                if not args.model_revision:
                    parser.error("--start-glimmer needs --model-revision")
                engine_dir = root / "engines" / f"evaluation-glimmer-{args.split or 'all'}-{uuid.uuid4().hex[:12]}"
                engine_dir.mkdir(parents=True, exist_ok=False)
                engine = _engine_factory({**{k: v for k, v in _serving(args).items() if k != "dtype"},
                                          **study.get("engine_base", {}),
                                          "max_model_len": args.glimmer_max_model_len,
                                          "use_engine_defaults": False}, engine_dir, args.dtype)
                engine.start()
            clients, ledger = _clients(args, arms, glimmer_url=engine.base_url if engine else args.glimmer_url)
            evaluate(root, arms, clients=clients, checkpoint_s=study["timing"]["checkpoint_s"],
                     split=args.split, answers=answers)
            if ledger:
                print(json.dumps(ledger.summary(), indent=2))
        except BaseException as exc:
            if engine_dir:
                (engine_dir / "failure.json").write_text(json.dumps({"error": type(exc).__name__}) + "\n")
            raise
        finally:
            if engine:
                try:
                    engine.stop()
                finally:
                    (engine_dir / "engine_metadata.json").write_text(json.dumps(engine.metadata, indent=2) + "\n")
    elif args.command == "score":
        from .scoring import score_study
        print(json.dumps(score_study(args.study_dir, split=args.split)["by_arm"], indent=2))
    elif args.command == "report":
        from .report import render_report
        print(render_report(args.study_dir))
    elif args.command == "live":
        from .live import run_live
        from .observe import load_incident, normal_profile
        root = Path(args.study_dir)
        study = _study(root / "study.json")
        scenario = next(s for s in json.loads((root / "scenarios.json").read_text())["scenarios"]
                        if s["id"] == args.id)
        answers = json.loads((root / "answers" / "answer_keys.json").read_text())["answers"]
        onset = next(a["onset_s"] for a in answers if a["id"] == args.id)
        reference_dir = root / "incidents" / "reference"
        reference = load_incident(reference_dir) if reference_dir.exists() else None
        clients, ledger = _clients(args, [args.arm], glimmer_url=f"http://127.0.0.1:{args.port}/v1")
        result = run_live(scenario, onset, arm=args.arm, clients=clients, serving=_serving(args),
                          pools=_pools(study, args.data_dir),
                          run_dir=args.out or root / "live" / f"{args.id}-{args.arm}",
                          engine_factory=_engine_factory, gpu_factory=_gpu_factory(args.gpu_index),
                          profile=normal_profile(reference["telemetry"]) if reference else None,
                          reference_config=reference["engine_config"] if reference else None,
                          checkpoint_s=study["timing"]["checkpoint_s"])
        print(json.dumps({k: result[k] for k in ("decision", "executed", "recovered", "rolled_back",
                                                 "time_to_recover_s")}, indent=2, default=str))
    elif args.command == "simulate":
        from .simulate import simulate_study
        study = _study(ROOT / "configs" / "servedoctor.json")
        study["capacity_rps"] = args.capacity_rps
        out = simulate_study(study, args.out)
        (Path(out) / "study.json").write_text(json.dumps(study, indent=2) + "\n")
        print(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
