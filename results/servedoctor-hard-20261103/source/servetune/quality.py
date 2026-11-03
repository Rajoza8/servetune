"""Deterministic answer scoring and the frozen v4 count-tolerance gate.

Policy: use the final ``####`` answer marker, otherwise the final simple
``\\boxed{...}`` answer, otherwise the final nonempty line. On token-limit
truncation require an explicit marker. Normalize Unicode NFKC, case, and
whitespace; canonicalize plain finite decimals (e.g. ``1.00`` equals ``1``).
No mathematical expressions are evaluated and no LLM judges are used.
"""

from __future__ import annotations

from decimal import Decimal
import hashlib
import json
from pathlib import Path
import re
import unicodedata


SPLITS = {"dev": {"items": 150, "allowed_decrease": 3},
          "final": {"items": 300, "allowed_decrease": 6}}
TOLERANCE_WORDING = "within the predeclared 2-percentage-point tolerance"
SCORER_POLICY = {
    "answer_extraction": "last #### marker, else last simple boxed answer, else last nonempty line",
    "truncated_answer_extraction": "explicit #### or simple boxed answer required",
    "normalization": "Unicode NFKC, casefold, collapsed whitespace, canonical plain decimals",
    "expression_evaluation": False,
    "failed_eval_request": "incorrect and candidate fails outright",
}
_DECIMAL = re.compile(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)\Z")
_BOXED = re.compile(r"\\boxed\{([^{}]*)\}")
_LENGTH_REASONS = frozenset({"length", "max_tokens", "max_output_tokens"})


def _hash(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def scorer_sha256() -> str:
    """Hash the exact saved scorer implementation, not a model's description."""
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def normalize_answer(value) -> str:
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        raise ValueError("Answer must be a string or finite number")
    value = " ".join(unicodedata.normalize("NFKC", str(value)).casefold().split())
    if not value:
        raise ValueError("Expected answer must not be empty")
    if _DECIMAL.fullmatch(value):
        number = Decimal(value)
        if not number.is_finite():
            raise ValueError("Answer must be finite")
        value = format(number, "f")
        if "." in value:
            value = value.rstrip("0").rstrip(".")
        if number == 0:
            value = "0"
    elif value in {"nan", "+nan", "-nan", "inf", "+inf", "-inf", "infinity", "+infinity", "-infinity"}:
        raise ValueError("Answer must be finite")
    return value


def extract_answer(text: str, *, allow_fallback: bool = True) -> str | None:
    if not isinstance(text, str) or not text.strip():
        return None
    if "####" in text:
        lines = [line.strip() for line in text.rsplit("####", 1)[1].splitlines() if line.strip()]
        if lines:
            return lines[0]
    matches = _BOXED.findall(text)
    if matches:
        return matches[-1].strip() or None
    if allow_fallback:
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        return lines[-1] if lines else None
    return None


def _validate_items(items: list[dict]) -> tuple[dict, str]:
    if not isinstance(items, list) or not items:
        raise ValueError("Items must be a nonempty list")
    indexed = {}
    for item in items:
        if not isinstance(item, dict):
            raise ValueError("Each evaluation item must be an object")
        item_id = item.get("id")
        if not isinstance(item_id, str) or not item_id.strip() or item_id in indexed:
            raise ValueError("Evaluation IDs must be unique nonempty strings")
        normalize_answer(item.get("answer"))
        indexed[item_id] = item
    return indexed, _hash(items)


def validate_dataset_manifest(dev_items: list[dict], final_items: list[dict]) -> dict:
    dev, dev_hash = _validate_items(dev_items)
    final, final_hash = _validate_items(final_items)
    if len(dev) != SPLITS["dev"]["items"] or len(final) != SPLITS["final"]["items"]:
        raise ValueError("The v4 manifests require 150 dev and 300 final items")
    if set(dev) & set(final):
        raise ValueError("Dev and final item IDs must be disjoint")
    # IDs alone do not prevent the same question from being renamed across splits.
    def contents(mapping):
        result = set()
        for item in mapping.values():
            prompt = item.get("prompt", item.get("question"))
            if not isinstance(prompt, str) or not prompt.strip():
                raise ValueError("Manifest items require a nonempty prompt or question")
            result.add(" ".join(unicodedata.normalize("NFKC", prompt).casefold().split()))
        return result
    dev_contents, final_contents = contents(dev), contents(final)
    if len(dev_contents) != len(dev) or len(final_contents) != len(final):
        raise ValueError("Evaluation splits must not contain duplicate questions")
    if dev_contents & final_contents:
        raise ValueError("Dev and final questions must be disjoint")
    return {"dev_items": len(dev), "final_items": len(final),
            "dev_sha256": dev_hash, "final_sha256": final_hash,
            "scorer_sha256": scorer_sha256(), "policy": dict(SCORER_POLICY),
            "gate": SPLITS, "wording": TOLERANCE_WORDING}


def score_items(items: list[dict], outputs: list[dict]) -> dict:
    """Score actual output records; missing outputs count as failed requests.

    This function accepts small fixture sets for local verification. The gate
    itself refuses to apply the real 150/300-item tolerances to small fixtures.
    Outputs use ``id``, ``text``, ``finish_reason``, and optional ``error``.
    """
    indexed, items_hash = _validate_items(items)
    if not isinstance(outputs, list):
        raise ValueError("Outputs must be a list")
    by_id = {}
    for output in outputs:
        if (not isinstance(output, dict) or not isinstance(output.get("id"), str)
                or output["id"] not in indexed):
            raise ValueError("Output has an unknown evaluation item ID")
        if output["id"] in by_id:
            raise ValueError("Duplicate evaluation output ID")
        by_id[output["id"]] = output
    results = []
    for item_id, item in indexed.items():
        output = by_id.get(item_id)
        text = output.get("text") if output else None
        failed = (output is None or bool(output.get("error"))
                  or not isinstance(text, str) or not text.strip())
        truncated = bool(output and output.get("finish_reason") in _LENGTH_REASONS)
        extracted = None if failed else extract_answer(text, allow_fallback=not truncated)
        correct = False
        if extracted is not None:
            try:
                correct = normalize_answer(extracted) == normalize_answer(item["answer"])
            except ValueError:
                pass
        results.append({"id": item_id, "correct": correct, "failed_request": failed,
                        "truncated": truncated, "extracted_answer": extracted})
    correct = sum(row["correct"] for row in results)
    return {"items": len(results), "correct": correct, "incorrect": len(results) - correct,
            "failed_requests": sum(row["failed_request"] for row in results),
            "truncated_answers": sum(row["truncated"] for row in results),
            "score": correct / len(results), "items_sha256": items_hash,
            "item_ids": list(indexed), "scorer_sha256": scorer_sha256(),
            "policy": dict(SCORER_POLICY), "results": results}


def evaluate_gate(candidate_result: dict, baseline_result: dict, split: str = "dev") -> dict:
    """Compare against the same bf16 reference; a count tolerance is not a
    statistical finding of equivalence or absence of a detected regression.
    """
    if split not in SPLITS:
        raise ValueError("split must be dev or final")
    spec = SPLITS[split]
    for result in (candidate_result, baseline_result):
        if not isinstance(result, dict) or result.get("items") != spec["items"]:
            raise ValueError(f"The {split} quality gate requires {spec['items']} items")
        if (type(result.get("correct")) is not int
                or not 0 <= result["correct"] <= spec["items"]
                or type(result.get("failed_requests")) is not int
                or not 0 <= result["failed_requests"] <= spec["items"]):
            raise ValueError("Invalid quality counts")
        ids = result.get("item_ids")
        rows = result.get("results")
        if (not isinstance(ids, list) or len(ids) != spec["items"]
                or any(not isinstance(item_id, str) or not item_id for item_id in ids)
                or len(set(ids)) != spec["items"]
                or not isinstance(rows, list) or len(rows) != spec["items"]):
            raise ValueError("Quality records must cover the complete unique evaluation set")
        seen = set()
        for row in rows:
            if (not isinstance(row, dict) or not isinstance(row.get("id"), str)
                    or row["id"] not in ids or row["id"] in seen
                    or type(row.get("correct")) is not bool
                    or type(row.get("failed_request")) is not bool
                    or (row["failed_request"] and row["correct"])):
                raise ValueError("Invalid paired evaluation result")
            seen.add(row["id"])
        if (sum(row["correct"] for row in rows) != result["correct"]
                or sum(row["failed_request"] for row in rows) != result["failed_requests"]):
            raise ValueError("Quality aggregate counts do not match paired result records")
    for key in ("items_sha256", "scorer_sha256", "item_ids"):
        if not candidate_result.get(key) or candidate_result[key] != baseline_result.get(key):
            raise ValueError("Candidate and reference must use identical items and scorer")
    if baseline_result["failed_requests"]:
        raise ValueError("The frozen reference contains failed evaluation requests")
    candidate = candidate_result["correct"]
    reference = baseline_result["correct"]
    passed = (candidate_result["failed_requests"] == 0
              and candidate >= reference - spec["allowed_decrease"])
    candidate_rows = {row["id"]: row for row in candidate_result.get("results", [])}
    baseline_rows = {row["id"]: row for row in baseline_result.get("results", [])}
    if set(candidate_rows) != set(candidate_result["item_ids"]) or set(baseline_rows) != set(baseline_result["item_ids"]):
        raise ValueError("Paired result records must cover the complete evaluation set")
    lost = sum(bool(baseline_rows[i]["correct"]) and not bool(candidate_rows[i]["correct"])
               for i in baseline_rows)
    gained = sum(not bool(baseline_rows[i]["correct"]) and bool(candidate_rows[i]["correct"])
                 for i in baseline_rows)
    return {"split": split, "passed": passed, "items": spec["items"],
            "candidate_correct": candidate, "reference_correct": reference,
            "allowed_decrease": spec["allowed_decrease"],
            "minimum_correct": max(0, reference - spec["allowed_decrease"]),
            "difference_percentage_points": 100 * (candidate - reference) / spec["items"],
            "paired_lost": lost, "paired_gained": gained,
            "failed_requests": candidate_result["failed_requests"],
            "wording": TOLERANCE_WORDING if passed else "outside the predeclared quality gate",
            "claim_scope": "observed counts on this fixed evaluation; no statistical equivalence claim",
            "items_sha256": candidate_result["items_sha256"],
            "scorer_sha256": candidate_result["scorer_sha256"]}
