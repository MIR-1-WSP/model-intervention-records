#!/usr/bin/env python3
"""MIR-1 conformance test, served as a single page and a JSON endpoint.

The page exists so that a person can check one record without installing
anything. The endpoint exists so that a pipeline can. Both call the reference
validator in a subprocess; neither stores, logs, or forwards the record.

Standard library only, so the Space has no dependencies to pin and the same
file runs on a laptop:

    python3 space/app.py
    curl -s localhost:7860/health

Routes:
    GET  /               the page
    GET  /example        the worked example, as JSON
    GET  /spec           MIR-1-spec.md, as text
    GET  /health         "ok"
    POST /validate       form or JSON in, HTML out
    POST /api/validate   JSON in, the validator's report out unchanged
"""

from __future__ import annotations

import email.policy
import html
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import urllib.parse
from email.parser import BytesParser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
VALIDATOR = os.path.join(HERE, "validate.py")
ARTIFACTS = [os.path.join(HERE, "artifacts"), os.path.join(HERE, "records", "artifacts"),
             os.path.join(HERE, "examples", "patch", "artifacts")]
MAX_BODY = 2 * 1024 * 1024
FORM_TIMEOUT_S = 60
REMOTE_TIMEOUT_S = 150
MAX_CONCURRENT = 8
QUEUE_WAIT_S = 5
IDLE_TIMEOUT_S = 30
PORT = int(os.environ.get("PORT", "7860"))


def read_text(name, default=""):
    try:
        with open(os.path.join(HERE, name), "r", encoding="utf-8") as handle:
            return handle.read()
    except OSError:
        return default


def validate_record(payload, verify_remote):
    """Write the record to a temporary directory and run the validator."""
    workdir = tempfile.mkdtemp(prefix="mir1-")
    path = os.path.join(workdir, "record.json")
    try:
        with open(path, "wb") as handle:
            handle.write(payload)
        command = [sys.executable, VALIDATOR, path, "--json"]
        for directory in ARTIFACTS:
            if os.path.isdir(directory):
                command += ["--artifacts", directory]
        if verify_remote:
            command.append("--verify-remote")
        proc = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=REMOTE_TIMEOUT_S if verify_remote else FORM_TIMEOUT_S,
            cwd=HERE,
        )
        try:
            report = json.loads(proc.stdout)
        except ValueError:
            report = None
        if not isinstance(report, dict):
            sys.stderr.write("validator returned no report (exit %d): %s\n"
                             % (proc.returncode, (proc.stderr or proc.stdout)[:2000]))
            return {
                "suite": "unknown",
                "record": "<submitted>",
                "checks": [{"id": "C-01", "ok": False,
                            "detail": "the validator did not return a report"}],
                "pass": False,
                "failed": ["C-01"],
            }, 1
        # The validator names the temporary file it read; that path is the
        # server's, not the submitter's.
        report["record"] = "<submitted>"
        return report, proc.returncode
    except subprocess.TimeoutExpired:
        return {
            "suite": "unknown",
            "record": "<submitted>",
            "checks": [{"id": "C-01", "ok": False,
                        "detail": "the validator did not finish in time"}],
            "pass": False,
            "failed": ["C-01"],
        }, 1
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def parse_fields(content_type, body):
    """Return {name: bytes} for a multipart, urlencoded, or raw JSON request."""
    media = content_type.split(";", 1)[0].strip().lower()
    if media == "multipart/form-data":
        message = BytesParser(policy=email.policy.default).parsebytes(
            b"Content-Type: " + content_type.encode("latin-1", "replace") + b"\r\n"
            b"MIME-Version: 1.0\r\n\r\n" + body
        )
        fields = {}
        for part in message.iter_parts():
            name = part.get_param("name", header="content-disposition")
            payload = part.get_payload(decode=True)
            if name and payload is not None:
                fields[name] = payload
        return fields
    if media == "application/x-www-form-urlencoded":
        parsed = urllib.parse.parse_qs(body.decode("utf-8", "replace"))
        return {key: value[0].encode("utf-8") for key, value in parsed.items()}
    if media == "application/json":
        return {"text": body}
    return {}


STYLE = """
:root { color-scheme: light; }
body { margin: 0 auto; max-width: 54rem; padding: 2rem 1.25rem 4rem;
       font: 16px/1.55 -apple-system, "Segoe UI", Roboto, sans-serif;
       color: #1a1a1a; background: #fbfbf9; }
h1 { font-size: 1.5rem; letter-spacing: -0.01em; margin: 0 0 .25rem; }
p.lead { margin: 0 0 2rem; color: #555; }
h2 { font-size: 1.05rem; margin: 2rem 0 .6rem; }
code, pre, textarea, input[type=file] { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: .85rem; }
textarea { width: 100%; box-sizing: border-box; padding: .75rem; border: 1px solid #ccc;
           border-radius: 4px; background: #fff; resize: vertical; }
input[type=submit] { margin-top: .75rem; padding: .5rem 1rem; font: inherit;
                     border: 1px solid #1a1a1a; background: #1a1a1a; color: #fff;
                     border-radius: 4px; cursor: pointer; }
label.opt { display: block; margin: .6rem 0; color: #444; font-size: .9rem; }
table { border-collapse: collapse; width: 100%; margin-top: .5rem; }
th, td { text-align: left; padding: .4rem .5rem; border-bottom: 1px solid #e2e2e2;
         vertical-align: top; font-size: .88rem; }
th { font-weight: 600; color: #555; }
td.id { white-space: nowrap; font-family: ui-monospace, Menlo, monospace; }
td.detail { color: #444; word-break: break-word; }
.pass { color: #0a6b2d; font-weight: 600; }
.fail { color: #a1261b; font-weight: 600; }
.skip { color: #6a6a6a; font-weight: 600; }
pre.report { background: #fff; border: 1px solid #e2e2e2; border-radius: 4px;
             padding: .75rem; overflow-x: auto; }
footer { margin-top: 3rem; border-top: 1px solid #e2e2e2; padding-top: 1rem;
         color: #666; font-size: .85rem; }
a { color: #1a4fa0; }
"""


def page(body, status=""):
    title = "MIR-1 conformance"
    if status:
        title = status + " — " + title
    return (
        "<!doctype html><html lang=en><head><meta charset=utf-8>"
        "<meta name=viewport content='width=device-width,initial-scale=1'>"
        "<title>" + html.escape(title) + "</title><style>" + STYLE + "</style></head><body>"
        + body +
        "<footer>Conformance is a claim anyone may check. No accounts, no scores, "
        "no repository. The validator is the reference implementation published with "
        "the specification; <a href='/spec'>the text</a> is the authority.</footer>"
        "</body></html>"
    )


def form_page(message=""):
    notice = ""
    if message:
        notice = "<p class=lead><strong>" + html.escape(message) + "</strong></p>"
    body = (
        "<h1>MIR-1 conformance</h1>"
        "<p class=lead>Check a Model Intervention Record against the nine mechanical "
        "requirements. Nothing you paste is stored.</p>"
        + notice +
        "<form method=post action=/validate enctype=multipart/form-data>"
        "<textarea name=text rows=16 spellcheck=false placeholder='{ ... }'></textarea>"
        "<label class=opt>or upload a record: <input type=file name=record accept='.json,application/json'></label>"
        "<label class=opt><input type=checkbox name=remote value=1> "
        "confirm locators against their hosts (one HEAD request each; slower)</label>"
        "<input type=submit value='Run the test'>"
        "</form>"
        "<h2>Try the worked example</h2>"
        "<p>A published weight edit, re-recorded: <a href='/validate/example'>run it</a> "
        "or <a href='/example'>read the JSON</a>.</p>"
        "<h2>From a pipeline</h2>"
        "<pre class=report>curl -s -X POST --data-binary @record.json \\\n"
        "  -H 'content-type: application/json' " + "http://localhost:%d/api/validate" % PORT + "</pre>"
    )
    return page(body)


def result_page(report):
    rows = []
    for check in report.get("checks", []):
        ok = bool(check.get("ok"))
        rows.append(
            "<tr><td class=id>" + html.escape(str(check.get("id", ""))) + "</td>"
            "<td class='" + ("pass" if ok else "fail") + "'>" + ("PASS" if ok else "FAIL") + "</td>"
            "<td class=detail>" + html.escape(str(check.get("detail", ""))) + "</td></tr>"
        )
    failed = list(report.get("failed") or [])
    patch = report.get("patch") or {}
    patch_rows = patch.get("checks") or []
    for check in patch_rows:
        state = check.get("result", "fail")
        style = {"pass": "pass", "fail": "fail"}.get(state, "skip")
        rows.append(
            "<tr><td class=id>" + html.escape(str(check.get("id", ""))) + "</td>"
            "<td class='" + style + "'>" + state.upper() + "</td>"
            "<td class=detail>" + html.escape(str(check.get("detail", ""))) + "</td></tr>"
        )
    failed += list(patch.get("failed") or [])
    summary = ("PASS" if report.get("pass") else "FAIL") + " — " + str(len(rows) - len(patch_rows)) + " checks"
    if patch_rows:
        summary += ", " + str(len(patch_rows)) + " patch checks"
    qualifiers = report.get("qualifiers") or []
    if qualifiers:
        summary += ", qualifiers: " + ", ".join(str(item) for item in qualifiers)
    if failed:
        summary += ", failing " + ", ".join(str(item) for item in failed)
    body = (
        "<h1>MIR-1 conformance</h1>"
        "<p class=lead>" + html.escape(summary) + "</p>"
        "<table><thead><tr><th>Check</th><th>Result</th><th>Detail</th></tr></thead><tbody>"
        + "".join(rows) + "</tbody></table>"
        "<h2>Report</h2><pre class=report>" + html.escape(json.dumps(report, indent=2, ensure_ascii=False)) + "</pre>"
        "<p><a href='/'>Check another record</a></p>"
    )
    return page(body, "Pass" if report.get("pass") else "Fail")


class Handler(BaseHTTPRequestHandler):
    server_version = "mir1-space/1.2"
    protocol_version = "HTTP/1.1"
    timeout = IDLE_TIMEOUT_S

    def log_message(self, format, *args):  # noqa: A002 - signature from the base class
        # Do not log record content or client addresses.
        sys.stderr.write("%s %s\n" % (getattr(self, "command", "-"),
                                      urllib.parse.urlsplit(getattr(self, "path", "/")).path))

    def send_body(self, status, body, content_type="text/html; charset=utf-8"):
        payload = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        if self.close_connection:
            self.send_header("Connection", "close")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(payload)

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        path = urllib.parse.urlsplit(self.path).path
        if path in ("/", "/index.html"):
            self.send_body(200, form_page())
        elif path == "/health":
            self.send_body(200, "ok", "text/plain; charset=utf-8")
        elif path == "/example":
            self.send_body(200, read_text(os.path.join("records", "MIR-R1.json"), "{}"),
                           "application/json; charset=utf-8")
        elif path == "/spec":
            self.send_body(200, read_text("MIR-1-spec.md", "the specification is not bundled"),
                           "text/plain; charset=utf-8")
        elif path == "/validate/example":
            payload = read_text(os.path.join("records", "MIR-R1.json"), "").encode("utf-8")
            report, _ = validate_record(payload, False)
            self.send_body(200, result_page(report))
        else:
            self.send_body(404, page("<h1>Not found</h1><p><a href='/'>Back</a></p>"))

    def do_POST(self):
        path = urllib.parse.urlsplit(self.path).path
        if path not in ("/validate", "/api/validate"):
            self.send_body(404, "not found", "text/plain; charset=utf-8")
            return
        try:
            length = int(self.headers.get("content-length", "0"))
        except ValueError:
            length = 0
        if length <= 0:
            self.send_body(411, "a request body is required", "text/plain; charset=utf-8")
            return
        if length > MAX_BODY:
            # Read a bounded amount so the client is not reset mid-write, then
            # close. A body far beyond the limit is not read at all.
            self.close_connection = True
            if length <= MAX_BODY + 1024 * 1024:
                self.rfile.read(length)
            self.send_body(413, "record larger than %d bytes" % MAX_BODY, "text/plain; charset=utf-8")
            return
        body = self.rfile.read(length)
        content_type = self.headers.get("content-type") or ""
        fields = parse_fields(content_type, body)
        payload = fields.get("text") or fields.get("record") or body
        verify_remote = bool(fields.get("remote")) or "remote=1" in urllib.parse.urlsplit(self.path).query

        if path == "/api/validate":
            report, _ = validate_record(payload, verify_remote)
            self.send_body(200, json.dumps(report, indent=2) + "\n",
                           "application/json; charset=utf-8")
        else:
            report, _ = validate_record(payload, verify_remote)
            self.send_body(200, result_page(report))


class Server(ThreadingHTTPServer):
    """A threading server that admits at most MAX_CONCURRENT requests at once."""

    # The accept loop waits for a slot, so pending connections must queue in the
    # kernel rather than be reset by a full backlog.
    request_queue_size = 128

    def __init__(self, address, handler):
        super().__init__(address, handler)
        self.slots = threading.BoundedSemaphore(MAX_CONCURRENT)

    def process_request(self, request, client_address):
        if not self.slots.acquire(timeout=QUEUE_WAIT_S):
            self.refuse(request)
            return
        try:
            super().process_request(request, client_address)
        except Exception:
            self.slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self.slots.release()

    def refuse(self, request):
        body = b"the server is busy; try again shortly\n"
        head = ("HTTP/1.1 503 Service Unavailable\r\n"
                "Content-Type: text/plain; charset=utf-8\r\n"
                "Content-Length: %d\r\n"
                "Connection: close\r\n\r\n" % len(body)).encode("ascii")
        try:
            request.sendall(head + body)
        except OSError:
            pass
        self.shutdown_request(request)


def main():
    if not os.path.isfile(VALIDATOR):
        sys.exit("validate.py is missing; run space/sync.py first")
    server = Server(("0.0.0.0", PORT), Handler)
    sys.stderr.write("MIR-1 conformance on http://0.0.0.0:%d\n" % PORT)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
