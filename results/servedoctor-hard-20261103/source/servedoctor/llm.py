"""Model clients for the agent arms, with a separate fail-closed ServeDoctor ledger.

Meta (Muse Spark) and Baseten calls reserve their worst-case cost before
dispatch; unknown outcomes keep the full reservation. Local Glimmer calls cost
no API money. Keys come only from the process environment.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from decimal import Decimal
import fcntl
import http.client
import ipaddress
import json
import os
from pathlib import Path
import re
import ssl
import time
import urllib.error
import urllib.request
from urllib.parse import urlsplit
import uuid

from .catalog import ACTION_TYPES, ROOT_CAUSES, ActionError, validate_action

CAPS = {"meta": Decimal("50"), "baseten": Decimal("20")}
META_COMPLETIONS_URL = "https://api.meta.ai/v1/chat/completions"


def _meta_proxy_address(value):
    try:
        if not isinstance(value, str) or len(value) > 256 or any(ord(c) <= 32 or ord(c) >= 127 for c in value):
            raise ValueError()
        parsed = urlsplit(value)
        if (not value.startswith("http://") or parsed.scheme != "http" or parsed.path or parsed.query
                or parsed.fragment or "?" in value or "#" in value or parsed.username is not None
                or parsed.password is not None or parsed.port is None or not 1 <= parsed.port <= 65535
                or not ipaddress.ip_address(parsed.hostname).is_loopback):
            raise ValueError()
        return parsed.hostname, parsed.port
    except (ValueError, TypeError):
        raise ValueError("Meta CONNECT proxy must be a numeric loopback HTTP URL with an explicit port and no other fields") from None


def load_api_transport(study_dir, *, environ=None):
    """Read the explicit study transport only; no network or credential access."""
    path = Path(study_dir) / "api-transport.json"
    if not path.exists() and not path.is_symlink():
        return None
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 4096:
        raise ValueError("Invalid study API transport file")

    def unique_object(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise ValueError("Duplicate API transport field")
            value[key] = item
        return value

    config = json.loads(path.read_text(), object_pairs_hook=unique_object)
    if (not isinstance(config, dict) or set(config) != {"project", "instance_id", "meta_https_connect_proxy"}
            or config["project"] != "servedoctor" or type(config["instance_id"]) is not int
            or config["instance_id"] <= 0):
        raise ValueError("Invalid ServeDoctor API transport schema")
    environ = os.environ if environ is None else environ
    if environ.get("CONTAINER_ID") != str(config["instance_id"]):
        raise ValueError("API transport instance does not match CONTAINER_ID")
    _meta_proxy_address(config["meta_https_connect_proxy"])
    return config["meta_https_connect_proxy"]


class _MetaConnectConnection(http.client.HTTPSConnection):
    """TLS to the official Meta host after a plaintext loopback CONNECT handshake."""
    def __init__(self, proxy_address, timeout):
        host, port = proxy_address
        super().__init__(host, port=port, timeout=timeout, context=ssl.create_default_context())
        self.set_tunnel("api.meta.ai", port=443)

PROVIDERS = {
    "spark": {"provider": "meta", "url": "https://api.meta.ai/v1/chat/completions",
              "model": "muse-spark-1.3", "key_env": ("MODEL_API_KEY", "META_API_KEY"),
              "input_per_m": Decimal("1.25"), "output_per_m": Decimal("4.25"),
              "extra": {"reasoning_effort": "low"}, "max_tokens_field": "max_completion_tokens",
              "temperature": 1.0},
    # Muse Wonder (Meta's newer frontier model). Model ID and rates must be checked
    # against dev.meta.ai before the first paid call; override with META_WONDER_MODEL.
    "wonder": {"provider": "meta", "url": "https://api.meta.ai/v1/chat/completions",
               "model": "muse-wonder", "key_env": ("MODEL_API_KEY", "META_API_KEY"),
               "input_per_m": Decimal("4"), "output_per_m": Decimal("20"),
               "extra": {"reasoning_effort": "low"}, "max_tokens_field": "max_completion_tokens",
               "temperature": 1.0},
    "glimmer-local": {"provider": "local", "url": None, "model": "servetune-glimmer", "key_env": (),
                      "input_per_m": Decimal(0), "output_per_m": Decimal(0),
                      "extra": {"chat_template_kwargs": {"reasoning_strength": "low"},
                                "response_format": {"type": "json_object"}},
                      "max_tokens_field": "max_tokens"},
    "glimmer-baseten": {"provider": "baseten", "url": None, "model": None, "key_env": ("BASETEN_API_KEY",),
                        "input_per_m": Decimal(0), "output_per_m": Decimal(0),
                        "extra": {}, "max_tokens_field": "max_tokens"},
}


class LedgerError(RuntimeError):
    pass


class BudgetWarningError(LedgerError):
    """Paid work must pause for a user report at the ledger's 50% warning."""


class PermanentAPIError(RuntimeError):
    """A paid API rejected the request; retain evidence and require intervention."""

    def __init__(self, provider, http_status):
        self.provider, self.http_status = provider, http_status
        super().__init__(f"{provider} returned HTTP {http_status}; stop and report before another paid call")


class PermanentConfigurationError(RuntimeError):
    """A request cannot be encoded; keep one failure and require configuration repair."""

    def __init__(self, provider):
        self.provider = provider
        super().__init__(f"{provider} request encoding failed; stop and verify configuration")


class Ledger:
    def __init__(self, path):
        self.path = Path(path)

    @contextmanager
    def _lock(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.with_name(self.path.name + ".lock").open("a") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def _load(self):
        if not self.path.exists():
            raise LedgerError("ServeDoctor ledger missing; run `python3 -m servedoctor ledger-init` once")
        data = json.loads(self.path.read_text())
        if data.get("project") != "servedoctor" or data.get("caps_usd") != {k: str(v) for k, v in CAPS.items()}:
            raise LedgerError("Ledger project or caps changed")
        return data

    def _save(self, data):
        tmp = self.path.with_name(self.path.name + f".{uuid.uuid4().hex}.tmp")
        tmp.write_text(json.dumps(data, indent=2) + "\n")
        os.replace(tmp, self.path)

    def initialize(self):
        with self._lock():
            if self.path.exists():
                raise LedgerError("Ledger exists; refusing to reset spending")
            self._save({"project": "servedoctor", "caps_usd": {k: str(v) for k, v in CAPS.items()},
                        "entries": []})

    @staticmethod
    def _total(data, provider):
        return sum((Decimal(e["accounted_usd"]) for e in data["entries"] if e["provider"] == provider), Decimal(0))

    def reserve(self, provider, amount, meta):
        with self._lock():
            data = self._load()
            self._require_below_warning(data)
            if self._total(data, provider) + amount > CAPS[provider]:
                raise LedgerError(f"{provider} cap of ${CAPS[provider]} reached; no request sent")
            entry_id = uuid.uuid4().hex
            data["entries"].append({"id": entry_id, "provider": provider, "status": "reserved",
                                    "reserved_usd": str(amount), "accounted_usd": str(amount),
                                    "at": datetime.now(timezone.utc).isoformat(), "meta": meta})
            self._save(data)
            return entry_id

    @classmethod
    def _require_below_warning(cls, data):
        warned = [p for p in CAPS if cls._total(data, p) >= CAPS[p] / 2]
        if warned:
            raise BudgetWarningError(f"{', '.join(warned)} at or above 50% of its cap; stop and report")

    def require_below_warning(self):
        with self._lock():
            self._require_below_warning(self._load())

    def settle(self, entry_id, actual, usage):
        with self._lock():
            data = self._load()
            entry = next(e for e in data["entries"] if e["id"] == entry_id)
            overrun = actual > Decimal(entry["reserved_usd"])
            entry.update(status="overrun" if overrun else "settled", accounted_usd=str(actual), usage=usage)
            self._save(data)

    def summary(self):
        with self._lock():
            data = self._load()
            totals = {p: float(self._total(data, p)) for p in CAPS}
            return {"caps_usd": {k: float(v) for k, v in CAPS.items()}, "accounted_usd": totals,
                    "warnings": [f"{p} at or above 50% of its cap" for p in CAPS
                                 if totals[p] >= float(CAPS[p]) / 2],
                    "calls": len(data["entries"])}


class ModelClient:
    def __init__(self, name, *, ledger=None, base_url=None, model=None, timeout_s=120, transport=None,
                 environ=None, meta_https_connect_proxy=None):
        if name not in PROVIDERS:
            raise ValueError(f"Unknown model client {name}")
        self.name = name
        self.spec = dict(PROVIDERS[name])
        self.meta_https_connect_proxy = meta_https_connect_proxy
        self._meta_proxy = None
        if meta_https_connect_proxy is not None:
            if self.spec["provider"] != "meta" or self.spec["url"] != META_COMPLETIONS_URL:
                raise ValueError("The explicit Meta CONNECT transport is available only for official Meta clients")
            self._meta_proxy = _meta_proxy_address(meta_https_connect_proxy)
        environ = os.environ if environ is None else environ
        if name == "glimmer-local":
            self.spec["url"] = (base_url or "http://127.0.0.1:8000/v1").rstrip("/") + "/chat/completions"
        if name == "wonder":
            self.spec["model"] = model or environ.get("META_WONDER_MODEL", self.spec["model"])
        if name == "glimmer-baseten":
            self.spec["url"] = base_url or environ.get("BASETEN_BASE_URL", "").rstrip("/") + "/chat/completions"
            self.spec["model"] = model or environ.get("BASETEN_MODEL")
            try:
                rates = [Decimal(environ[k]) for k in ("BASETEN_INPUT_PER_M", "BASETEN_OUTPUT_PER_M")]
            except (KeyError, ArithmeticError, ValueError) as exc:
                raise ValueError("Set verified BASETEN_INPUT_PER_M and BASETEN_OUTPUT_PER_M prices") from exc
            if any(not rate.is_finite() or rate <= 0 for rate in rates):
                raise ValueError("Baseten token prices must be finite and positive")
            self.spec["input_per_m"], self.spec["output_per_m"] = rates
        self.key = next((environ[k] for k in self.spec["key_env"] if environ.get(k)), None)
        if self.spec["key_env"] and (not isinstance(self.key, str) or not self.key
                                    or any(not 33 <= ord(char) <= 126 for char in self.key)):
            raise ValueError("Paid API credentials must be nonempty ASCII strings without whitespace or control characters")
        self.ledger = ledger
        if self.spec["provider"] in CAPS and ledger is None:
            raise ValueError("Paid providers require the ServeDoctor ledger")
        self.timeout_s = timeout_s
        self.transport = transport or self._http
        self.calls = 0
        self.cost_usd = Decimal(0)
        self.wait_s = 0.0
        self.failures = 0

    def _http(self, body):
        headers = {"Content-Type": "application/json"}
        if self.key:
            headers["Authorization"] = f"Bearer {self.key}"
        if self._meta_proxy is not None:
            if self.spec["url"] != META_COMPLETIONS_URL:
                raise ValueError("Meta CONNECT transport target changed")
            connection = _MetaConnectConnection(self._meta_proxy, self.timeout_s)
            try:
                connection.request("POST", "/v1/chat/completions", body=json.dumps(body).encode(), headers=headers)
                response = connection.getresponse()
                if 300 <= response.status < 400:
                    raise PermanentAPIError("meta", response.status)
                if not 200 <= response.status < 300:
                    raise urllib.error.HTTPError(META_COMPLETIONS_URL, response.status, "Meta request failed", None, None)
                return json.loads(response.read(2_000_000))
            finally:
                connection.close()
        request = urllib.request.Request(self.spec["url"], data=json.dumps(body).encode(), headers=headers,
                                         method="POST")
        handlers = [urllib.request.ProxyHandler({})] if self.spec["provider"] == "local" else []
        with urllib.request.build_opener(*handlers).open(request, timeout=self.timeout_s) as response:
            return json.loads(response.read(2_000_000))

    def chat(self, system, user, max_tokens=1500):
        body = {"model": self.spec["model"], "temperature": self.spec.get("temperature", 0),
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
                self.spec["max_tokens_field"]: max_tokens, **self.spec["extra"]}
        provider = self.spec["provider"]
        entry = None
        if provider in CAPS:
            input_bound = len(json.dumps(body["messages"]).encode()) + 512
            reserve = (Decimal(input_bound) * self.spec["input_per_m"]
                       + Decimal(max_tokens) * self.spec["output_per_m"]) / Decimal(1_000_000)
            entry = self.ledger.reserve(provider, max(reserve, Decimal("0.000001")),
                                        {"client": self.name, "max_tokens": max_tokens})
        started = time.monotonic()
        self.calls += 1
        try:
            response = self.transport(body)
        except UnicodeEncodeError:
            self.failures += 1
            raise PermanentConfigurationError(provider) from None
        except urllib.error.HTTPError as exc:
            self.failures += 1
            if provider in CAPS and exc.code in (400, 401, 403, 404, 429):
                raise PermanentAPIError(provider, exc.code) from None
            raise
        except Exception:
            self.failures += 1
            raise
        finally:
            self.wait_s += time.monotonic() - started
        usage = response.get("usage") or {}
        if entry is not None and isinstance(usage.get("prompt_tokens"), int) \
                and isinstance(usage.get("completion_tokens"), int):
            cost = (Decimal(usage["prompt_tokens"]) * self.spec["input_per_m"]
                    + Decimal(usage["completion_tokens"]) * self.spec["output_per_m"]) / Decimal(1_000_000)
            self.ledger.settle(entry, cost, {k: usage[k] for k in ("prompt_tokens", "completion_tokens")})
            self.cost_usd += cost
        choice = (response.get("choices") or [{}])[0]
        content = (choice.get("message") or {}).get("content") or ""
        if self.key and len(self.key) >= 16:  # Never let an echoed credential reach saved evidence.
            content = content.replace(self.key, "[REDACTED]")
        return content, usage


_JSON_BLOCK = re.compile(r"\{.*\}", re.DOTALL)


def parse_json(text):
    """Accept bare JSON or JSON inside prose/code fences; reject anything else."""
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        match = _JSON_BLOCK.search(text or "")
        if not match:
            raise ValueError("No JSON object in model output")
        return json.loads(match.group(0))


MONITOR_SYSTEM = """You are the always-on monitor for one LLM inference server (vLLM on one GPU).
Every 30 seconds you get recent telemetry. Decide whether an operator should look now.
Flag anomalies that threaten the SLO, errors, or clear waste of the GPU; ignore normal noise and brief spikes.
Reply with only JSON: {"status": "healthy" | "anomaly", "summary": "<at most 200 characters>"}"""


def diagnose_system():
    causes = "\n".join(f"- {k}: {v}" for k, v in ROOT_CAUSES.items())
    actions = "\n".join(f"- {k}: {v}" for k, v in ACTION_TYPES.items())
    return f"""You are the on-call engineer for one LLM inference server (vLLM serving Muse Glimmer on one GPU).
You receive telemetry visible right now: SLO, current and reference engine config, gateway policy,
change log, a normal profile from a healthy reference run, 10-second metric buckets, GPU processes
and recent engine log lines. Decide whether there is an incident, its root cause, and the safest fix.

Root causes (choose exactly one key):
{causes}

Allowed actions (JSON objects; at most 2; prefer the least disruptive fix; engine changes restart the engine):
{actions}

Field formats: set_engine_config {{"type":"set_engine_config","knob":<knob>,"value":<number>}};
gateway_rate_limit {{"type":"gateway_rate_limit","max_rps":<number>}};
gateway_max_prompt_tokens {{"type":"gateway_max_prompt_tokens","max_prompt_tokens":<integer>}};
stop_gpu_process {{"type":"stop_gpu_process","pid":<integer from the GPU process table>}}.
If there is no incident, use root_cause "healthy" and the action no_action.

Reply with only JSON:
{{"incident": true|false, "root_cause": "<key>", "confidence": <0..1>,
  "evidence": ["<short fact from the telemetry>", ...at most 5],
  "actions": [<action objects>], "explanation": "<at most 400 characters>"}}"""


def normalize_decision(raw, *, current_config):
    """Validate a model decision; invalid parts become explicit failures, never silent fixes."""
    if type(raw) is not dict:
        raise ValueError("Decision must be a JSON object")
    root = raw.get("root_cause")
    if root not in ROOT_CAUSES:
        root = "other"
    actions, rejected = [], []
    for action in (raw.get("actions") or [])[:2]:
        try:
            actions.append(validate_action(action, current_config=current_config))
        except ActionError as exc:
            rejected.append({"action": action, "reason": str(exc)})
    incident = bool(raw.get("incident")) and root != "healthy"
    if not actions:
        actions = [{"type": "no_action"}] if not incident else [{"type": "escalate_to_human"}]
    evidence = [str(e)[:200] for e in (raw.get("evidence") or [])][:5]
    return {"incident": incident, "root_cause": root if incident else "healthy",
            "confidence": raw.get("confidence"), "evidence": evidence, "actions": actions,
            "rejected_actions": rejected, "explanation": str(raw.get("explanation", ""))[:400]}
