"""One bounded Meta proposal request for preflight P3, with no implicit retry.

Rates/model/request format checked against official Meta documentation on
2026-10-29. Usage accounting intentionally ignores cache discounts.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
import hashlib
import json
import math
import os
from pathlib import Path
import time
import urllib.error
import urllib.request

from .ledger import BudgetExceeded, Ledger, LedgerError


MODEL = "muse-spark-1.3"
ENDPOINT = "https://api.meta.ai/v1/chat/completions"
INPUT_RATE = Decimal("1.25")
OUTPUT_RATE = Decimal("4.25")
DOCS = ["https://dev.meta.ai/docs/protocols/chat-completions",
        "https://dev.meta.ai/docs/pricing-rate-limits"]
BASELINE = {"max_num_seqs": 64, "max_num_batched_tokens": 8192,
            "enable_chunked_prefill": True, "gpu_memory_utilization": 0.85}


class ProposalError(ValueError):
    pass


class _RejectRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ProposalError("Authenticated HTTP redirects are blocked")


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ProposalError("Duplicate key in model JSON")
        result[key] = value
    return result


def validate_proposal(value):
    if type(value) is not dict or set(value) != {"hypothesis", "expected_effect", "diff"}:
        raise ProposalError("Proposal must contain exactly hypothesis, expected_effect, diff")
    for key in ("hypothesis", "expected_effect"):
        if type(value[key]) is not str or not 1 <= len(value[key].strip()) <= 1000:
            raise ProposalError("Proposal explanations must be nonempty strings of at most 1000 characters")
    diff = value["diff"]
    if type(diff) is not dict or len(diff) != 1:
        raise ProposalError("A preflight proposal must change exactly one knob")
    key, item = next(iter(diff.items()))
    if key not in BASELINE:
        raise ProposalError("Proposal names a non-whitelisted knob")
    if key == "max_num_seqs":
        valid = type(item) is int and 1 <= item <= 128
    elif key == "max_num_batched_tokens":
        valid = type(item) is int and 512 <= item <= 16384
    elif key == "enable_chunked_prefill":
        valid = type(item) is bool
    else:
        valid = (type(item) in (int, float) and math.isfinite(item)
                 and 0.5 <= item <= 0.9)
    if not valid or item == BASELINE[key]:
        raise ProposalError("Proposal value is out of bounds or leaves the baseline unchanged")
    return value


def _usage_cost(usage):
    if type(usage) is not dict:
        raise ProposalError("Provider supplied no valid usage; full reservation retained")
    counts = {}
    for key in ("prompt_tokens", "completion_tokens"):
        if type(usage.get(key)) is not int or not 0 <= usage[key] <= 1_000_000_000_000:
            raise ProposalError("Provider supplied invalid usage; full reservation retained")
        counts[key] = usage[key]
    total = usage.get("total_tokens")
    if total is not None and (type(total) is not int or total != sum(counts.values())):
        raise ProposalError("Provider supplied inconsistent usage; full reservation retained")
    cost = (Decimal(counts["prompt_tokens"]) * INPUT_RATE
            + Decimal(counts["completion_tokens"]) * OUTPUT_RATE) / Decimal(1_000_000)
    return counts, cost


def _transport(body, key, timeout):
    request = urllib.request.Request(
        ENDPOINT, data=json.dumps(body).encode("utf-8"), method="POST",
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    opener = urllib.request.build_opener(_RejectRedirects())
    with opener.open(request, timeout=timeout) as response:
        raw = response.read(1_000_001)
        if len(raw) > 1_000_000:
            raise ProposalError("Provider response exceeds the bounded response size")
        return json.loads(raw, object_pairs_hook=_unique_object)


def _save(path, value):
    # Exclusive creation makes a repeated preflight path fail before dispatch.
    with path.open("x") as stream:
        json.dump(value, stream, indent=2, allow_nan=False)
        stream.write("\n")


def _request_body(max_output_tokens=2048):
    messages = [
        {"role": "system", "content":
         "Return exactly one JSON object with keys hypothesis (string), expected_effect (string), "
         "and diff (object). This preflight tests schema compatibility only. Propose exactly one "
         "change to the supplied baseline, using only these bounds: max_num_seqs integer 1..128; "
         "max_num_batched_tokens integer 512..16384; enable_chunked_prefill boolean; "
         "gpu_memory_utilization number 0.5..0.9. No other fields or commands. Each explanation "
         "must have 1..1000 characters. No execution occurs."},
        {"role": "user", "content": json.dumps({"baseline": BASELINE,
         "goal": "Propose one hypothesis to reduce GPU energy per output token under a fixed workload and latency SLO; effects are unmeasured."})},
    ]
    return {"model": MODEL, "messages": messages, "temperature": 1.0,
            "reasoning_effort": "low", "max_completion_tokens": max_output_tokens}


_EVIDENCE_FILES = ("spark-request.json", "spark-usage.json", "spark-result.json")


def _evidence_snapshot(directory):
    directory = Path(directory)
    if not directory.is_dir() or directory.is_symlink():
        raise ProposalError("Saved P3 evidence must be a regular directory")
    raw, documents = {}, {}
    for name in _EVIDENCE_FILES:
        path = directory / name
        if not path.is_file() or path.is_symlink() or path.stat().st_size > 1_000_000:
            raise ProposalError("Saved P3 evidence is missing, symlinked, or oversized")
        with path.open("rb") as stream:
            raw[name] = stream.read(1_000_001)
        if len(raw[name]) > 1_000_000:
            raise ProposalError("Saved P3 evidence exceeded its bounded file size")
        try:
            documents[name] = json.loads(raw[name], object_pairs_hook=_unique_object)
        except (ValueError, UnicodeDecodeError, RecursionError) as exc:
            raise ProposalError("Saved P3 evidence is not valid unique-key JSON") from exc
        if type(documents[name]) is not dict:
            raise ProposalError("Saved P3 evidence files must be JSON objects")
    return raw, documents


def _canonical(value):
    try:
        return json.dumps(value, sort_keys=True, ensure_ascii=False,
                          separators=(",", ":"), allow_nan=False).encode()
    except (ValueError, TypeError, RecursionError) as exc:
        raise ProposalError("Saved P3 evidence must contain finite JSON") from exc


def _saved_amount(value):
    if type(value) not in (str, int, float):
        raise ProposalError("Saved P3 cost is not a finite nonnegative amount")
    try:
        amount = Decimal(str(value))
    except InvalidOperation as exc:
        raise ProposalError("Saved P3 cost is invalid") from exc
    if not amount.is_finite() or amount < 0:
        raise ProposalError("Saved P3 cost is not finite and nonnegative")
    return amount


def _validate_saved(documents, ledger_data):
    if ledger_data["blocked"]:
        raise ProposalError("The cumulative ledger has an unresolved usage overrun")
    result = documents["spark-result.json"]
    if (result.get("check") != "P3" or result.get("status") != "pass"
            or type(result.get("paid_calls")) is not int or result["paid_calls"] != 1
            or result.get("provider") != "meta" or result.get("model") != MODEL
            or result.get("endpoint") != ENDPOINT
            or result.get("accounting_status") != "usage_reconciled"
            or type(result.get("reservation_id")) is not str):
        raise ProposalError("Saved P3 result is not a successful accounted Meta check")
    rows = [row for row in ledger_data["entries"] if row["id"] == result["reservation_id"]]
    if len(rows) != 1:
        raise ProposalError("Saved P3 reservation is absent from the cumulative ledger")
    row = rows[0]
    metadata = row.get("metadata")
    if (row["provider"] != "meta" or row["status"] != "settled" or type(metadata) is not dict
            or metadata.get("phase") != "preflight_P3" or metadata.get("model") != MODEL):
        raise ProposalError("Saved P3 reservation is not a settled preflight Meta call")
    maximum = metadata.get("max_completion_tokens")
    if type(maximum) is not int or not 256 <= maximum <= 2048:
        raise ProposalError("Saved P3 completion ceiling differs from the supported protocol")
    request = documents["spark-request.json"]
    if _canonical(request) != _canonical(_request_body(maximum)):
        raise ProposalError("Saved P3 request differs from the current exact model/schema/baseline")
    input_bound = len(json.dumps(request["messages"], ensure_ascii=False).encode("utf-8")) + 512
    reserved = (Decimal(input_bound) * INPUT_RATE + Decimal(maximum) * OUTPUT_RATE) / Decimal(1_000_000)
    if (type(result.get("input_token_reservation")) is not int
            or result["input_token_reservation"] != input_bound
            or _saved_amount(result.get("reserved_usd")) != reserved
            or _saved_amount(row["reserved_usd"]) != reserved):
        raise ProposalError("Saved P3 reservation bound does not match its ledger entry")
    usage_doc = documents["spark-usage.json"]
    usage, actual = _usage_cost(usage_doc.get("usage"))
    if (usage != result.get("usage") or usage != row.get("usage")
            or _saved_amount(usage_doc.get("estimated_cost_usd")) != actual
            or _saved_amount(result.get("estimated_actual_usd")) != actual
            or _saved_amount(row["accounted_usd"]) != actual
            or usage_doc.get("rates_usd_per_million") != {"input": str(INPUT_RATE), "output": str(OUTPUT_RATE)}
            or usage["completion_tokens"] > maximum or usage["prompt_tokens"] > input_bound):
        raise ProposalError("Saved P3 usage/cost does not match its settled ledger entry")
    validate_proposal(result.get("proposal"))
    return row


def attest_spark_evidence(ledger_path, evidence_dir, *, _capture_mode="explicit_local_attestation"):
    """Explicitly bind reviewed local P3 files to their settled reservation.

    This is needed once for legacy checks recorded before evidence hashes were
    captured. It is an owner's local attestation, not retrospective proof of an
    unrecorded response. Import never calls it automatically. No provider calls
    occur and accounting amounts are unchanged.
    """
    if _capture_mode not in {"explicit_local_attestation", "captured_after_request"}:
        raise ProposalError("Unknown P3 evidence binding mode")
    raw, documents = _evidence_snapshot(evidence_dir)
    hashes = {name: hashlib.sha256(content).hexdigest() for name, content in raw.items()}
    ledger = Ledger(ledger_path)
    with ledger._lock():
        data = ledger._load()
        row = _validate_saved(documents, data)
        binding = {"schema_version": 1, "files_sha256": hashes,
                   "ledger_created_at": data["created_at"], "mode": _capture_mode}
        prior = row["metadata"].get("p3_evidence")
        if prior is not None:
            if (type(prior) is not dict or prior.get("files_sha256") != hashes
                    or prior.get("ledger_created_at") != data["created_at"]):
                raise ProposalError("P3 evidence hashes are already bound and cannot be replaced")
            return prior
        row["metadata"]["p3_evidence"] = binding
        ledger._save(data)
    return binding


def import_spark_evidence(ledger_path, evidence_dir, artifact_dir):
    """Validate bound, settled P3 evidence, then copy its exact bytes offline."""
    raw, documents = _evidence_snapshot(evidence_dir)
    hashes = {name: hashlib.sha256(content).hexdigest() for name, content in raw.items()}
    ledger = Ledger(ledger_path)
    with ledger._lock():
        data = ledger._load()
        row = _validate_saved(documents, data)
        binding = row["metadata"].get("p3_evidence")
        if (type(binding) is not dict or binding.get("schema_version") != 1
                or binding.get("files_sha256") != hashes
                or binding.get("ledger_created_at") != data["created_at"]
                or binding.get("mode") not in {"explicit_local_attestation", "captured_after_request"}):
            raise ProposalError("Saved P3 files are not hash-bound to this cumulative ledger")
        ledger_entry_sha = hashlib.sha256(_canonical(row)).hexdigest()
    destination = Path(artifact_dir)
    destination.mkdir(parents=True, exist_ok=False)
    for name, content in raw.items():
        with (destination / name).open("xb") as stream:
            stream.write(content)
    imported = {"schema_version": 1, "imported": True, "paid_calls_this_run": 0,
                "original_paid_calls": 1, "reservation_id": row["id"],
                "files_sha256": hashes, "ledger_entry_sha256": ledger_entry_sha,
                "ledger_created_at": binding["ledger_created_at"], "binding_mode": binding["mode"],
                "claim": "Reused schema/connectivity evidence; no new model response or tuning trial"}
    _save(destination / "import.json", imported)
    return {**documents["spark-result.json"], "imported": True, "paid_calls_this_run": 0,
            "reason": "Verified saved Meta P3 evidence against its settled cumulative ledger entry; no new paid call",
            "import": imported}


def run_spark_check(ledger_path, artifact_dir, *, transport=None, environ=None,
                    timeout_seconds=60, max_output_tokens=2048):
    """P3: make at most one paid request and retain its reservation on uncertainty.

    `transport(body, key, timeout)->dict` is injectable for offline tests. Caller
    must initialize the separate ServeTune ledger explicitly before live use.
    Keys are read only from process environment; no .env files are loaded.
    """
    if (type(timeout_seconds) not in (int, float) or not math.isfinite(timeout_seconds)
            or not 1 <= timeout_seconds <= 120 or type(max_output_tokens) is not int
            or not 256 <= max_output_tokens <= 2048):
        raise ValueError("Use timeout 1–120 seconds and output cap 256–2048")
    artifact_dir = Path(artifact_dir)
    artifact_dir.mkdir(parents=True, exist_ok=True)
    result = {"check": "P3", "status": "blocked", "paid_calls": 0,
              "provider": "meta", "model": MODEL, "endpoint": ENDPOINT,
              "docs": DOCS, "pricing_checked": "2026-10-29"}
    if any((artifact_dir / name).exists() for name in
           ("spark-request.json", "spark-result.json", "spark-usage.json")):
        raise ProposalError("Spark evidence already exists; use a fresh preflight directory")
    environment = os.environ if environ is None else environ
    key = environment.get("MODEL_API_KEY") or environment.get("META_API_KEY")
    if not isinstance(key, str) or not key:
        result["reason"] = "Set MODEL_API_KEY or META_API_KEY in the environment"
        _save(artifact_dir / "spark-result.json", result)
        return result
    body = _request_body(max_output_tokens)
    messages = body["messages"]
    input_bound = len(json.dumps(messages, ensure_ascii=False).encode("utf-8")) + 512
    reservation = (Decimal(input_bound) * INPUT_RATE + Decimal(max_output_tokens) * OUTPUT_RATE) / Decimal(1_000_000)
    result.update(reserved_usd=float(reservation), input_token_reservation=input_bound,
                  cost_basis="Conservative UTF-8 bytes + 512 input bound and capped output; reported tokens priced without cache discount")
    ledger = Ledger(ledger_path)
    try:
        reservation_id = ledger.reserve("meta", reservation,
                                        {"phase": "preflight_P3", "model": MODEL,
                                         "max_completion_tokens": max_output_tokens})
    except LedgerError as exc:
        result["reason"] = str(exc)
        _save(artifact_dir / "spark-result.json", result)
        return result
    result["reservation_id"] = reservation_id
    # Persist the exact non-secret request before dispatch. A filesystem failure
    # here leaves a conservative reservation, never an unaccounted paid request.
    _save(artifact_dir / "spark-request.json", body)
    started = time.monotonic()
    result["paid_calls"] = 1
    try:
        response = (transport or _transport)(body, key, timeout_seconds)
        if type(response) is not dict:
            raise ProposalError("Provider returned a malformed response")
        usage, actual_cost = _usage_cost(response.get("usage"))
        # Only allowlisted usage fields are saved. Arbitrary server strings,
        # headers, errors, and complete response bodies never enter artifacts.
        _save(artifact_dir / "spark-usage.json", {
            "usage": usage, "estimated_cost_usd": str(actual_cost),
            "rates_usd_per_million": {"input": str(INPUT_RATE), "output": str(OUTPUT_RATE)},
            "basis": "Reported prompt/completion tokens; completion includes reasoning; no cache discount; not an invoice"})
        ledger.settle(reservation_id, actual_cost, usage=usage)
        result.update(estimated_actual_usd=float(actual_cost), usage=usage,
                      accounting_status="usage_reconciled")
        choices = response.get("choices")
        if type(choices) is not list or len(choices) != 1 or type(choices[0]) is not dict:
            raise ProposalError("Provider returned no single completion")
        choice = choices[0]
        if choice.get("finish_reason") != "stop":
            raise ProposalError("Completion did not finish normally; no retry performed")
        message = choice.get("message")
        content = message.get("content") if type(message) is dict else None
        if type(content) is not str or len(content) > 8192:
            raise ProposalError("Completion must contain bounded JSON text")
        proposal = validate_proposal(json.loads(content, object_pairs_hook=_unique_object))
        # Even a provider echoing a credential cannot persist it in explanations.
        proposal = {**proposal,
                    "hypothesis": proposal["hypothesis"].replace(key, "[REDACTED]"),
                    "expected_effect": proposal["expected_effect"].replace(key, "[REDACTED]")}
        result.update(status="pass", proposal=proposal)
    except BudgetExceeded:
        result.update(status="fail", reason="Reported usage overran its reservation; paid calls are blocked",
                      accounting_status="overrun_retained")
    except (ProposalError, ValueError, TypeError, KeyError, IndexError, LedgerError,
            OSError, urllib.error.URLError, TimeoutError, RecursionError) as exc:
        # Exception text from network/library code can contain credentials or
        # server bodies. Save only known local validation messages.
        reason = str(exc) if type(exc) is ProposalError else type(exc).__name__
        result.update(status="fail", reason=reason.replace(key, "[REDACTED]"))
        result.setdefault("accounting_status", "full_reservation_retained")
    finally:
        result["planner_wait_seconds"] = time.monotonic() - started
    result["budget"] = ledger.summary()
    _save(artifact_dir / "spark-result.json", result)
    if result["status"] == "pass":
        attest_spark_evidence(ledger_path, artifact_dir, _capture_mode="captured_after_request")
    return result
