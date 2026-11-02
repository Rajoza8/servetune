"""Explicit Meta CONNECT transport with local fakes; no external requests."""
import io
import json
import os
from pathlib import Path
import ssl
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import urllib.error

from servedoctor.cli import _clients
from servedoctor.llm import (META_COMPLETIONS_URL, ModelClient, PermanentAPIError,
                            _MetaConnectConnection, load_api_transport)

PROXY = "http://127.0.0.1:18888"
ENV = {"MODEL_API_KEY": "invented-ascii-fixture-key", "META_WONDER_MODEL": "muse-wonder-1.0",
       "CONTAINER_ID": "58716527"}
CONFIG = {"project": "servedoctor", "instance_id": 58716527, "meta_https_connect_proxy": PROXY}


class Response:
    status = 200
    def __enter__(self): return self
    def __exit__(self, *_): pass
    def read(self, limit):
        assert limit == 2_000_000
        return b'{"choices":[{"message":{"content":"{}"}}],"usage":{"prompt_tokens":10,"completion_tokens":2}}'


class LedgerFixture:
    def __init__(self): self.reservations = []; self.settlements = []
    def reserve(self, *args): self.reservations.append(args); return "fixture"
    def settle(self, *args): self.settlements.append(args)


class MetaProxyTests(unittest.TestCase):
    def client(self, **kwargs):
        return ModelClient("wonder", ledger=LedgerFixture(), environ=ENV, **kwargs)

    def test_default_direct_http_and_injected_transports_are_unchanged(self):
        client = self.client()
        opener = Mock(); opener.open.return_value = Response()
        with patch("servedoctor.llm.urllib.request.build_opener", return_value=opener) as build, \
                patch("servedoctor.llm._MetaConnectConnection") as proxy:
            client._http({"model": "fixture"})
        build.assert_called_once_with(); proxy.assert_not_called()
        request = opener.open.call_args.args[0]
        self.assertEqual(request.full_url, META_COMPLETIONS_URL)
        self.assertEqual(request.get_method(), "POST")
        calls = []
        def transport(body):
            calls.append(body)
            return json.loads(Response().read(2_000_000))
        injected = self.client(meta_https_connect_proxy=PROXY, transport=transport)
        with patch("servedoctor.llm._MetaConnectConnection") as proxy:
            injected.chat("fixture system", "fixture observation", max_tokens=10)
        proxy.assert_not_called()
        self.assertEqual(len(calls), 1)
        self.assertEqual(len(injected.ledger.reservations), 1)
        self.assertEqual(injected.spec["url"], META_COMPLETIONS_URL)
        self.assertEqual(injected.spec["model"], "muse-wonder-1.0")
        self.assertEqual(str(injected.spec["input_per_m"]), "4")

    def test_config_requires_exact_schema_numeric_loopback_and_current_instance(self):
        invalid_urls = ["https://127.0.0.1:18888", "http://localhost:18888", "http://192.0.2.1:18888",
                        "http://127.0.0.1", "http://127.0.0.1:0", "http://user@127.0.0.1:18888",
                        "http://127.0.0.1:18888/", "http://127.0.0.1:18888?", "http://127.0.0.1:18888#x",
                        "http://127.0.0.1:18888\n"]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); path = root / "api-transport.json"
            self.assertIsNone(load_api_transport(root, environ={}))
            path.write_text(json.dumps(CONFIG))
            self.assertEqual(load_api_transport(root, environ=ENV), PROXY)
            for value in [*[{**CONFIG, "meta_https_connect_proxy": url} for url in invalid_urls],
                          {**CONFIG, "project": "other"}, {**CONFIG, "instance_id": True},
                          {**CONFIG, "instance_id": -1}, {**CONFIG, "extra": "field"}, []]:
                with self.subTest(config=value):
                    path.write_text(json.dumps(value))
                    with self.assertRaises(ValueError): load_api_transport(root, environ=ENV)
            path.write_text(json.dumps(CONFIG))
            for environ in ({}, {"CONTAINER_ID": "999"}):
                with self.assertRaises(ValueError): load_api_transport(root, environ=environ)
            path.write_text('{"project":"servedoctor","project":"servedoctor"}')
            with self.assertRaises(ValueError): load_api_transport(root, environ=ENV)
            path.write_text(" " * 4097)
            with self.assertRaises(ValueError): load_api_transport(root, environ=ENV)
            path.unlink(); path.symlink_to(root / "missing.json")
            with self.assertRaises(ValueError): load_api_transport(root, environ=ENV)
        with self.assertRaises(ValueError):
            ModelClient("glimmer-local", meta_https_connect_proxy=PROXY, environ={})

    def test_cli_reads_transport_only_for_meta_and_passes_it_to_both_experts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); path = root / "api-transport.json"
            path.write_text(json.dumps(CONFIG))
            args = SimpleNamespace(study_dir=root, ledger=root / "ledger.json", glimmer="local")
            with patch.object(os, "environ", dict(ENV)):
                clients, _ = _clients(args, ["spark", "wonder", "glimmer"])
            self.assertEqual(clients["spark"].meta_https_connect_proxy, PROXY)
            self.assertEqual(clients["wonder"].meta_https_connect_proxy, PROXY)
            self.assertIsNone(clients["glimmer"].meta_https_connect_proxy)
            # Invalid config is deliberately irrelevant to rules/Glimmer-only use.
            path.write_text("invalid JSON")
            with patch.object(os, "environ", {}):
                self.assertEqual(_clients(args, ["rules"])[0], {})
                self.assertIn("glimmer", _clients(args, ["glimmer"])[0])
                with self.assertRaises(ValueError): _clients(args, ["spark"])
            self.assertFalse((root / "ledger.json").exists())

    def test_explicit_connect_is_selected_even_when_no_proxy_matches_everything(self):
        connection = Mock(); connection.getresponse.return_value = Response()
        client = self.client(meta_https_connect_proxy=PROXY)
        with patch.object(os, "environ", {"NO_PROXY": "*", "HTTPS_PROXY": "http://192.0.2.1:9"}), \
                patch("servedoctor.llm._MetaConnectConnection", return_value=connection) as factory, \
                patch("servedoctor.llm.urllib.request.build_opener") as opener:
            client._http({"model": "fixture"})
        factory.assert_called_once_with(("127.0.0.1", 18888), 120)
        opener.assert_not_called(); connection.close.assert_called_once()
        self.assertEqual(connection.request.call_args.args, ("POST", "/v1/chat/completions"))
        self.assertEqual(connection.request.call_args.kwargs["headers"]["Authorization"], "Bearer " + ENV["MODEL_API_KEY"])

    def test_connect_handshake_has_no_bearer_and_tls_uses_official_server_hostname(self):
        class SocketFixture:
            def __init__(self): self.sent = []; self.reply = io.BytesIO(b"HTTP/1.1 200 Connection established\r\n\r\n")
            def setsockopt(self, *_): pass
            def sendall(self, value): self.sent.append(value)
            def makefile(self, *_): return self.reply
            def close(self): pass
        raw = SocketFixture(); tls = Mock()
        context = ssl.create_default_context()
        self.assertTrue(context.check_hostname)
        self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)
        with patch("servedoctor.llm.ssl.create_default_context", return_value=context), \
                patch.object(context, "wrap_socket", return_value=tls) as wrap:
            connection = _MetaConnectConnection(("127.0.0.1", 18888), 3)
            connection._create_connection = Mock(return_value=raw)
            connection.connect()
        connection._create_connection.assert_called_once_with(("127.0.0.1", 18888), 3, None)
        self.assertTrue(b"".join(raw.sent).startswith(b"CONNECT api.meta.ai:443 HTTP/1."))
        self.assertNotIn(b"Bearer", b"".join(raw.sent))
        wrap.assert_called_once_with(raw, server_hostname="api.meta.ai")
        self.assertIs(connection.sock, tls)
        connection.request("POST", "/v1/chat/completions", body=b"fixture body",
                           headers={"Authorization": "Bearer fixture"})
        secured = b"".join(call.args[0] for call in tls.sendall.call_args_list)
        self.assertIn(b"Host: api.meta.ai\r\n", secured)
        self.assertIn(b"Authorization: Bearer fixture\r\n", secured)
        self.assertIn(b"fixture body", secured)
        self.assertNotIn(b"Bearer", b"".join(raw.sent))
        self.assertNotIn(b"fixture body", b"".join(raw.sent))
        connection.close()

    def test_redirect_and_http_failure_close_connection_without_following_or_reading_body(self):
        for status in (302, 404):
            with self.subTest(status=status):
                connection = Mock(); connection.getresponse.return_value.status = status
                client = self.client(meta_https_connect_proxy=PROXY)
                expected = PermanentAPIError if status == 302 else urllib.error.HTTPError
                with patch("servedoctor.llm._MetaConnectConnection", return_value=connection), self.assertRaises(expected):
                    client._http({"model": "fixture"})
                connection.request.assert_called_once()
                connection.getresponse.return_value.read.assert_not_called()
                connection.close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
