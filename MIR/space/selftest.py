#!/usr/bin/env python3
"""Exercise the Space's routes without a browser and without a network.

    python3 space/selftest.py

Starts the same handler the container runs, on an ephemeral port, and checks
each route against the expected verdict. Exits non-zero on the first
disagreement. No dependencies.
"""

from __future__ import annotations

import json
import os
import sys
import threading
import urllib.error
import urllib.request
import uuid
from http.server import ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import app  # noqa: E402


def request(method, url, data=None, content_type=None):
    req = urllib.request.Request(url, data=data, method=method)
    if content_type:
        req.add_header("content-type", content_type)
    try:
        with urllib.request.urlopen(req, timeout=60) as response:
            return response.status, response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as error:
        return error.code, error.read().decode("utf-8", "replace")


def multipart(filename, payload):
    boundary = "----mir1" + uuid.uuid4().hex
    body = (
        "--%s\r\n"
        'Content-Disposition: form-data; name="record"; filename="%s"\r\n'
        "Content-Type: application/json\r\n\r\n" % (boundary, filename)
    ).encode("utf-8") + payload + ("\r\n--%s--\r\n" % boundary).encode("utf-8")
    return body, "multipart/form-data; boundary=" + boundary


def main():
    server = ThreadingHTTPServer(("127.0.0.1", 0), app.Handler)
    base = "http://127.0.0.1:%d" % server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    failures = 0

    def check(label, condition, detail=""):
        nonlocal failures
        if condition:
            print("%-52s ok" % label)
        else:
            failures += 1
            print("%-52s FAILED %s" % (label, detail))

    try:
        status, body = request("GET", base + "/health")
        check("GET /health", status == 200 and body == "ok", repr(body[:40]))

        status, body = request("GET", base + "/")
        check("GET / is the form", status == 200 and "MIR-1 conformance" in body)

        status, body = request("GET", base + "/spec")
        check("GET /spec is the specification", status == 200 and body.startswith("# MIR-1"))

        status, body = request("GET", base + "/example")
        example = json.loads(body)
        check("GET /example is the worked example",
              status == 200 and example.get("id", "").startswith("sha256:"))

        worked = body.encode("utf-8")
        status, response = request("POST", base + "/api/validate", worked, "application/json")
        report = json.loads(response)
        check("POST /api/validate: worked example fails C-07",
              status == 200 and report.get("pass") is False and report.get("failed") == ["C-07"],
              repr(report.get("failed")))

        status, response = request("POST", base + "/api/validate",
                                   json.dumps(json.load(open(os.path.join(
                                       HERE, "records", "MIR-R1.json")))).encode("utf-8"),
                                   "application/json")
        report = json.loads(response)
        check("the worked example earns its derived qualifiers",
              status == 200 and "baseline-present" in (report.get("qualifiers") or [])
              and "unpriced-reproduction" in (report.get("qualifiers") or []),
              repr(report.get("qualifiers")))

        with open(os.path.join(HERE, "records", "MIR-R1.json"), "rb") as handle:
            uploaded = handle.read()
        body, content_type = multipart("MIR-R1.json", uploaded)
        status, response = request("POST", base + "/validate", body, content_type)
        check("POST /validate multipart returns a table",
              status == 200 and "FAIL — 11 checks" in response and "C-07" in response)

        with open(os.path.join(HERE, "examples", "patch", "record-a.json"), "rb") as handle:
            patched = handle.read()
        status, response = request("POST", base + "/api/validate", patched, "application/json")
        report = json.loads(response)
        patch = report.get("patch") or {}
        check("POST /api/validate: a Weight Patch reports its five checks",
              status == 200 and report.get("pass") is True
              and [item.get("id") for item in patch.get("checks", [])]
              == ["P-01", "P-02", "P-03", "P-04", "P-05"]
              and "reversible" in (patch.get("qualifiers") or []),
              repr(patch.get("qualifiers")))

        status, response = request("POST", base + "/validate", patched, "application/json")
        check("the table shows the patch block",
              status == 200 and "5 patch checks" in response and "P-05" in response)

        status, response = request("POST", base + "/api/validate", b"{not json", "application/json")
        report = json.loads(response) if response.startswith("{") else {}
        check("invalid JSON is rejected by C-01",
              status == 200 and report.get("pass") is False
              and report.get("checks", [{}])[0].get("id") == "C-01")

        status, response = request("POST", base + "/api/validate",
                                   b"x" * (app.MAX_BODY + 1), "application/json")
        check("oversized body is refused", status == 413, str(status))

        status, response = request("GET", base + "/nope")
        check("unknown path is 404", status == 404, str(status))
    finally:
        server.shutdown()
        server.server_close()

    print("\n%d checks, %s" % (12, "all pass" if not failures else "%d failed" % failures))
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
