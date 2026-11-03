"""Fail-closed, cumulative ServeTune accounting, independent of Verifier Forge.

Unreconciled reservations remain fully charged across process failures. Monetary
values are stored as decimal strings; caps cannot be raised through this API.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import fcntl
import json
import os
from pathlib import Path
import tempfile
import uuid


CAPS = {"meta": Decimal("15"), "baseten": Decimal("5")}


class LedgerError(ValueError):
    """An accounting operation cannot be safely completed."""


class BudgetExceeded(LedgerError):
    """The remaining allowance cannot cover a reservation."""


def _amount(value, *, positive=False):
    if isinstance(value, bool) or not isinstance(value, (str, int, float, Decimal)):
        raise LedgerError("Cost must be a finite nonnegative decimal")
    try:
        amount = Decimal(str(value))
    except InvalidOperation as exc:
        raise LedgerError("Cost must be a finite nonnegative decimal") from exc
    if not amount.is_finite() or amount < 0 or (positive and amount == 0):
        raise LedgerError("Cost must be finite and positive" if positive else
                          "Cost must be finite and nonnegative")
    return amount


def _json_copy(value):
    try:
        return json.loads(json.dumps(value, allow_nan=False))
    except (ValueError, TypeError, RecursionError) as exc:
        raise LedgerError("Accounting metadata must be finite JSON") from exc


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise LedgerError("Duplicate key in ledger")
        result[key] = value
    return result


def _now():
    return datetime.now(timezone.utc).isoformat()


class Ledger:
    def __init__(self, path):
        self.path = Path(path).resolve()

    @contextmanager
    def _lock(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.with_name(self.path.name + ".lock").open("a") as handle:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise LedgerError("ServeTune ledger is busy; no request dispatched") from exc
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def initialize(self):
        """Explicitly create a fresh project ledger; never reset existing spend."""
        with self._lock():
            if self.path.exists():
                raise LedgerError("Ledger already exists; refusing to reset spending")
            self._save({"schema_version": 1, "project": "servetune",
                        "caps_usd": {k: str(v) for k, v in CAPS.items()},
                        "created_at": _now(), "blocked": False, "entries": []})
        return self.summary()

    def _load(self):
        try:
            data = json.loads(self.path.read_text(), object_pairs_hook=_unique_object)
        except (OSError, json.JSONDecodeError, RecursionError) as exc:
            raise LedgerError("Missing or unreadable ServeTune ledger; initialize explicitly") from exc
        if (type(data) is not dict or type(data.get("schema_version")) is not int
                or data.get("schema_version") != 1
                or data.get("project") != "servetune" or type(data.get("blocked")) is not bool
                or type(data.get("caps_usd")) is not dict
                or set(data["caps_usd"]) != set(CAPS)
                or any(_amount(data["caps_usd"][k]) != v for k, v in CAPS.items())
                or type(data.get("entries")) is not list):
            raise LedgerError("Invalid ledger schema or changed spending caps")
        seen = set()
        for row in data["entries"]:
            if (type(row) is not dict or type(row.get("id")) is not str or not row["id"]
                    or row["id"] in seen or type(row.get("provider")) is not str
                    or row.get("provider") not in CAPS
                    or row.get("status") not in {"reserved", "settled", "overrun"}):
                raise LedgerError("Invalid historical reservation")
            seen.add(row["id"])
            reserved = _amount(row.get("reserved_usd"), positive=True)
            accounted = _amount(row.get("accounted_usd"))
            if ((row["status"] == "reserved" and accounted != reserved)
                    or (row["status"] == "settled" and accounted > reserved)
                    or (row["status"] == "overrun" and not data["blocked"])):
                raise LedgerError("Invalid historical reservation accounting")
            _json_copy(row)
        return data

    def _save(self, data):
        encoded = json.dumps(data, indent=2, allow_nan=False) + "\n"
        temp_path = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", dir=self.path.parent,
                                             prefix=self.path.name + ".", delete=False) as stream:
                temp_path = Path(stream.name)
                stream.write(encoded)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp_path, self.path)
            temp_path = None
        finally:
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)

    @staticmethod
    def _totals(data):
        totals = {k: Decimal(0) for k in CAPS}
        for row in data["entries"]:
            totals[row["provider"]] += _amount(row["accounted_usd"])
        return totals

    def reserve(self, provider, amount_usd, metadata=None):
        """Durably account the full request bound before sending any request."""
        if provider not in CAPS:
            raise LedgerError("Unknown provider")
        amount = _amount(amount_usd, positive=True)
        metadata = _json_copy({} if metadata is None else metadata)
        if type(metadata) is not dict:
            raise LedgerError("Reservation metadata must be an object")
        with self._lock():
            data = self._load()
            totals = self._totals(data)
            if data["blocked"] or any(totals[k] > CAPS[k] for k in CAPS):
                raise BudgetExceeded("Ledger overrun blocks further paid calls")
            if totals[provider] + amount > CAPS[provider]:
                raise BudgetExceeded(f"ServeTune {provider} cap cannot cover the request")
            reservation_id = str(uuid.uuid4())
            data["entries"].append({"id": reservation_id, "provider": provider,
                                     "reserved_usd": str(amount), "accounted_usd": str(amount),
                                     "status": "reserved", "reserved_at": _now(),
                                     "metadata": metadata})
            self._save(data)
        return reservation_id

    def settle(self, reservation_id, actual_usd, usage=None):
        """Reconcile known usage; overruns are retained in full and block calls.

        Leave this method uncalled when billing/usage is unknown: the entire
        reservation remains accounted. Known usage may be settled even when
        the model's answer was unusable.
        """
        actual = _amount(actual_usd)
        usage = _json_copy(usage)
        with self._lock():
            data = self._load()
            rows = [r for r in data["entries"] if r["id"] == reservation_id]
            if len(rows) != 1 or rows[0]["status"] != "reserved":
                raise LedgerError("Reservation missing or already reconciled")
            row = rows[0]
            overrun = actual > _amount(row["reserved_usd"])
            row.update(accounted_usd=str(actual), usage=usage, settled_at=_now(),
                       status="overrun" if overrun else "settled")
            if overrun or any(self._totals(data)[k] > CAPS[k] for k in CAPS):
                data["blocked"] = True
            self._save(data)
            if data["blocked"]:
                raise BudgetExceeded("Usage overrun retained; further paid calls blocked")
        return self.summary()

    def summary(self):
        with self._lock():
            data = self._load()
            totals = self._totals(data)
            pending = {k: Decimal(0) for k in CAPS}
            for row in data["entries"]:
                if row["status"] == "reserved":
                    pending[row["provider"]] += _amount(row["accounted_usd"])
            return {
                "project": "servetune", "caps_usd": {k: float(v) for k, v in CAPS.items()},
                "accounted_usd": {k: float(v) for k, v in totals.items()},
                "remaining_usd": {k: float(max(Decimal(0), CAPS[k] - totals[k])) for k in CAPS},
                "unreconciled_reservations_usd": {k: float(v) for k, v in pending.items()},
                "warnings": [f"{k} has reached 50% of its ServeTune cap"
                             for k in CAPS if totals[k] >= CAPS[k] / 2],
                "blocked": data["blocked"] or any(totals[k] > CAPS[k] for k in CAPS),
                "exhausted_providers": [k for k in CAPS if totals[k] >= CAPS[k]],
                "attempts": len(data["entries"]),
                "basis": "Reported-token cost estimates plus full unknown/interrupted reservations; not an invoice",
            }
