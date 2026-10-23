"""Synthetic HAR interoperability and evidence preservation; no device or routing changes."""
import base64
import gzip
import importlib.util
import io
import json
import os
import subprocess
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from urllib.parse import parse_qsl, urlsplit
import zipfile
import zlib

try:
    from mitmproxy import connection, http, io as flow_io
except ImportError:
    connection = http = flow_io = None

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("har_export_addon", ROOT / "CaptureRuntime/network_addon.py")
addon_module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(addon_module)


class Pairs(dict):
    def items(self, multi=False):
        return super().items()


class MessageFixture:
    def __init__(self, raw, content_type, content_encoding):
        self.raw_content = raw
        self.headers = Pairs({"content-type": content_type})
        if content_encoding:
            self.headers["content-encoding"] = content_encoding
        self.method = "POST"
        self.pretty_url = "https://example.test/fixture"
        self.http_version = "HTTP/1.1"
        self.query = Pairs()
        self.timestamp_start = 1.0
        self.timestamp_end = 2.0
        self.status_code = 200
        self.reason = "OK"

    def get_content(self, strict=True):
        if self.raw_content is None:
            return None
        try:
            encoding = self.headers.get("content-encoding", "identity")
            if encoding == "identity":
                return self.raw_content
            if encoding == "gzip":
                return gzip.decompress(self.raw_content)
            if encoding == "deflate":
                return zlib.decompress(self.raw_content)
            raise ValueError("Unsupported synthetic content encoding")
        except (OSError, zlib.error) as error:
            raise ValueError("Invalid synthetic content encoding") from error

    @property
    def content(self):
        return self.get_content()



class HarExportTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="capture-har-fixture-")
        self.addCleanup(self.temporary.cleanup)
        environment = patch.dict(os.environ, {"CAPTURE_SESSION_DIR": self.temporary.name, "CAPTURE_SETUP_NONCE": ""})
        environment.start()
        self.addCleanup(environment.stop)
        self.addon = addon_module.CaptureAddon()
        self.addon.running()

    def message(self, body, mime="application/json", encoding=None, response=False):
        if http is None:
            return MessageFixture(body, mime, encoding)
        headers = {"content-type": mime}
        if encoding:
            headers["content-encoding"] = encoding
        message = http.Response.make(200) if response else http.Request.make("POST", "https://example.test/fixture")
        message.headers = http.Headers([(name.encode(), value.encode()) for name, value in headers.items()])
        message.raw_content = body
        message.timestamp_start = 1.0
        message.timestamp_end = 2.0
        return message

    def flow(self, request, response=None):
        return SimpleNamespace(id="synthetic-flow", request=request, response=response, error=None, metadata={},
                               client_conn=SimpleNamespace(peername=("127.0.0.1", 12345)))

    def post(self, message):
        return self.addon.entry(self.flow(message))["request"]["postData"]

    def test_json_unicode_and_base64_looking_sdk_token_are_plain_text(self):
        text = json.dumps({"user": {"uidapi": "YWJjZA=="}, "message": "café 日本語"}, ensure_ascii=False)
        post = self.post(self.message(text.encode()))
        self.assertEqual(post["text"], text)
        self.assertEqual(json.loads(post["text"])["user"]["uidapi"], "YWJjZA==")
        self.assertNotIn("encoding", post)
        self.assertNotIn("_encoding", post)
        self.assertNotIn("params", post)

    def test_urlencoded_forms_keep_plain_text_repetitions_and_escaped_unicode(self):
        text = "pub_extra_data=UID2+LRE&label=caf%C3%A9&empty=&label=second"
        post = self.post(self.message(text.encode(), "application/x-www-form-urlencoded; charset=utf-8"))
        self.assertEqual(post["text"], text)
        self.assertEqual(parse_qsl(post["text"], keep_blank_values=True),
                         [("pub_extra_data", "UID2 LRE"), ("label", "café"), ("empty", ""), ("label", "second")])
        self.assertNotIn("encoding", post)
        self.assertNotIn("params", post)

    def test_declared_charsets_and_structured_text_media_types(self):
        for charset in ("iso-8859-1", "utf-16", "utf-16-le", "utf-32"):
            text = '{"label":"café"}'
            with self.subTest(charset=charset):
                post = self.post(self.message(text.encode(charset), "application/problem+json; charset=" + charset))
                self.assertEqual(post["text"], text)
                self.assertNotIn("encoding", post)
        self.assertEqual(self.post(self.message(b"<ad>fixture</ad>", "application/xml"))["text"], "<ad>fixture</ad>")

    def test_unicode_without_declared_charset_and_bom_are_readable(self):
        text = "café 日本語"
        for mime in ("text/plain", "application/json", "application/x-www-form-urlencoded"):
            for charset in ("utf-8", "utf-8-sig", "utf-16", "utf-32"):
                with self.subTest(mime=mime, charset=charset):
                    post = self.post(self.message(text.encode(charset), mime))
                    self.assertEqual(post["text"], text)
                    self.assertNotIn("encoding", post)
        post = self.post(self.message(text.encode(), 'text/plain; Charset="UTF-8"'))
        self.assertEqual(post["text"], text)

    def test_gzip_and_deflate_are_decoded_before_text_export(self):
        original = '{"message":"café 日本語"}'.encode()
        for encoding, raw in (("gzip", gzip.compress(original)), ("deflate", zlib.compress(original))):
            message = self.message(raw, "application/json; charset=utf-8", encoding)
            with self.subTest(encoding=encoding):
                entry = self.addon.entry(self.flow(message))
                self.assertEqual(entry["request"]["postData"]["text"].encode(), original)
                self.assertNotIn("encoding", entry["request"]["postData"])
                self.assertEqual(entry["request"]["bodySize"], len(raw))
                self.assertEqual(message.raw_content, raw)

    def test_binary_and_invalid_text_are_explicit_extensions(self):
        for raw, mime in ((b"ascii binary", "application/octet-stream"), (b"\x00\xff\x80", "image/png"),
                          (b"\xff\xfe", "application/json; charset=utf-8"), (b"a\x00b", "text/plain"),
                          (b"abc", "application/json; charset=unknown-fixture-charset"),
                          (b"\\ud800", "text/plain; charset=unicode-escape")):
            with self.subTest(raw=raw, mime=mime):
                post = self.post(self.message(raw, mime))
                self.assertEqual(post["encoding"], "base64")
                self.assertEqual(post["_encoding"], "base64")
                self.assertEqual(base64.b64decode(post["text"], validate=True), raw)

    def test_broken_or_unsupported_content_encoding_is_not_text(self):
        for encoding in ("gzip", "unsupported-fixture"):
            raw = b'{"not":"decoded"}'
            with self.subTest(encoding=encoding):
                post = self.post(self.message(raw, "application/json", encoding))
                self.assertEqual(post["_encoding"], "base64")
                self.assertTrue(post["_contentDecodingError"])
                self.assertEqual(post["_byteBasis"], "raw_content")
                self.assertEqual(base64.b64decode(post["text"]), raw)

    def test_empty_is_distinct_from_unavailable_and_incomplete(self):
        empty = self.addon.entry(self.flow(self.message(b"")))["request"]
        self.assertEqual(empty["bodySize"], 0)
        self.assertEqual(empty["postData"]["text"], "")
        self.assertNotIn("_bodyUnavailable", empty)
        entry = self.addon.entry(self.flow(self.message(None)))
        self.assertTrue(entry["request"]["_bodyUnavailable"])
        self.assertEqual(entry["request"]["bodySize"], -1)
        self.assertNotIn("postData", entry["request"])
        self.assertTrue(entry["_incomplete"])
        response = self.addon.entry(self.flow(self.message(b""), self.message(None, response=True)))["response"]
        self.assertEqual(response["content"]["size"], -1)
        self.assertTrue(response["content"]["_bodyUnavailable"])
        self.assertNotIn("text", response["content"])

    def test_har_and_evidence_retain_bytes_without_mutating_messages(self):
        for encoding, raw in ((None, b'{"value":"YWJjZA=="}'), ("gzip", gzip.compress(b'{"value":"YWJjZA=="}'))):
            for response_raw in (b"\x00\xff", gzip.compress(b"synthetic response")):
                with self.subTest(encoding=encoding, response_raw=response_raw):
                    request = self.message(raw, encoding=encoding)
                    response_encoding = "gzip" if response_raw.startswith(b"\x1f\x8b") else None
                    response = self.message(response_raw, "application/octet-stream", response_encoding, response=True)
                    flow = self.flow(request, response)
                    self.addon.request(flow)
                    self.addon.response(flow)
                    har = json.loads((self.addon.root / "capture.har").read_text())
                    self.assertEqual(har["log"]["entries"][0]["request"]["postData"]["text"], '{"value":"YWJjZA=="}')
                    events = [json.loads(line) for line in (self.addon.root / "events.jsonl").read_text().splitlines()]
                    for name, original in (("request_body", raw), ("response_body", response_raw)):
                        detail = events[-1]["detail"][name]
                        exact = detail.get("raw", detail)
                        preserved = base64.b64decode(exact["text"]) if exact["encoding"] == "base64" else exact["text"].encode()
                        self.assertEqual(preserved, original)
                    self.assertEqual(request.raw_content, raw)
                    self.assertEqual(response.raw_content, response_raw)
                    exported_response = har["log"]["entries"][0]["response"]
                    self.assertEqual(exported_response["bodySize"], len(response_raw))
                    self.assertEqual(base64.b64decode(exported_response["content"]["text"]), response.content)

    def test_malformed_compressed_response_and_missing_evidence_are_explicit(self):
        raw = b"not a gzip stream"
        response = self.message(raw, "text/plain", "gzip", response=True)
        flow = self.flow(self.message(b""), response)
        self.addon.response(flow)
        entry = self.addon.entry(flow)["response"]
        self.assertTrue(entry["content"]["_contentDecodingError"])
        self.assertEqual(entry["content"]["_byteBasis"], "raw_content")
        self.assertEqual(base64.b64decode(entry["content"]["text"]), raw)
        events = [json.loads(line) for line in (self.addon.root / "events.jsonl").read_text().splitlines()]
        detail = events[-1]["detail"]["response_body"]
        self.assertTrue(detail["content_decoding_error"])
        self.assertEqual(detail["byte_basis"], "raw_content")
        self.assertEqual(detail["text"].encode(), raw)
        missing = self.addon.body_detail(self.message(None))
        self.assertTrue(missing["unavailable"])
        self.assertIsNone(missing["text"])
        self.assertIsNone(missing["bytes"])
        self.assertEqual(self.addon.body_detail(self.message(b""))["bytes"], 0)

    @unittest.skipUnless(os.environ.get("CAPTURE_HAR_ANALYZER"), "Set CAPTURE_HAR_ANALYZER to an existing identity analyzer")
    def test_existing_identity_analyzer_reads_exported_json_and_form_text(self):
        payload = json.dumps({"user": {"fpd": {"custom_data": {
            "uidapi": "YWJjZA==", "liveramp_envelope": "synthetic-envelope"}}}})
        for number, (url, data, mime) in enumerate((
                ("https://adx.ads.vungle.com/api/v7/ads", payload.encode(), "application/json"),
                ("https://wv.inner-active.mobi/simpleM2M/clientRequestEnhancedXmlAd", b"pub_extra_data=UID2+LRE", "application/x-www-form-urlencoded"))):
            request = self.message(data, mime)
            if http is None:
                request.pretty_url = url
            else:
                request.url = url
            flow = self.flow(request)
            flow.id = "synthetic-identity-" + str(number)
            self.addon.request(flow)
        result = subprocess.run([os.environ["CAPTURE_HAR_ANALYZER"], "--json", str(self.addon.root / "capture.har")],
                                check=True, capture_output=True, text=True)
        report = json.loads(result.stdout)[0]
        self.assertEqual(report["liftoff"]["uid2_requests"], 1)
        self.assertEqual(report["liftoff"]["liveramp_envelope_requests"], 1)
        self.assertEqual(report["dt"]["uid2_requests"], 1)
        self.assertEqual(report["dt"]["lre_requests"], 1)

    @unittest.skipIf(http is None, "Run inside the pinned engine for Brotli and Zstandard decoding")
    def test_real_engine_decodes_brotli_and_zstandard_before_har_text(self):
        text = '{"message":"café 日本語"}'
        for encoding in ("br", "zstd"):
            with self.subTest(encoding=encoding):
                message = self.message(text.encode())
                message.encode(encoding)
                raw = message.raw_content
                self.assertEqual(self.post(message)["text"], text)
                self.assertNotIn("encoding", self.post(message))
                self.assertEqual(message.raw_content, raw)

    @unittest.skipIf(http is None, "Run inside the pinned mitmproxy engine for real native-flow byte preservation")
    def test_real_native_flow_roundtrip_preserves_compressed_wire_bytes(self):
        request_raw = gzip.compress('{"message":"café"}'.encode())
        response_raw = gzip.compress(b"synthetic response")
        flow = http.HTTPFlow(connection.Client(peername=("127.0.0.1", 12345), sockname=("127.0.0.1", 8080)),
                             connection.Server(address=("example.test", 443)))
        flow.request = self.message(request_raw, encoding="gzip")
        flow.response = self.message(response_raw, "text/plain", "gzip", response=True)
        self.addon.request(flow)
        self.addon.response(flow)
        stream = io.BytesIO()
        flow_io.FlowWriter(stream).add(flow)
        stream.seek(0)
        restored = next(flow_io.FlowReader(stream).stream())
        self.assertEqual(restored.request.raw_content, request_raw)
        self.assertEqual(restored.response.raw_content, response_raw)
        (self.addon.root / "capture.mitm").write_bytes(stream.getvalue())
        spec = importlib.util.spec_from_file_location("har_export_evidence", ROOT / "CaptureRuntime/evidence.py")
        evidence = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(evidence)
        state = {"id": "synthetic-har", "platform": "android", "phase": "saved",
                 "sources": {"network": "observed"}, "routing_restored": True}
        with zipfile.ZipFile(evidence.finalize_package(Path(self.temporary.name), state)) as archive:
            for name in ("capture.har", "capture.mitm", "events.jsonl"):
                self.assertEqual(archive.read("network/" + name), (self.addon.root / name).read_bytes())
            packaged = next(flow_io.FlowReader(io.BytesIO(archive.read("network/capture.mitm"))).stream())
            self.assertEqual(packaged.request.raw_content, request_raw)
            self.assertEqual(packaged.response.raw_content, response_raw)


if __name__ == "__main__":
    unittest.main()
