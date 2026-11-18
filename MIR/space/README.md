---
title: MIR-1 conformance
emoji: 🔎
colorFrom: gray
colorTo: gray
sdk: docker
app_port: 7860
pinned: false
license: apache-2.0
short_description: Check a Model Intervention Record against MIR-1
---

# MIR-1 conformance

A Model Intervention Record states what was done to a model, what followed, and
what was required not to follow. MIR-1 defines eleven mechanical requirements
for such a record, and this Space runs the reference implementation of the test.
A `weights` payload that declares itself a Weight Patch is also measured by the
five checks of MIR-1.1, reported beside the eleven. The page also prints the
record-level qualifiers of MIR-1.2, which refine what the evidence says without
changing a verdict.

Paste a record on the page, or upload one. Nothing is stored: each request gets
a temporary directory that is deleted before the reply is written, and no
record content is logged.

## Endpoints

```
POST /api/validate      the record as the request body (application/json,
                        multipart with a field named "record", or urlencoded
                        with a field named "text")
GET  /example           the worked example, as JSON
GET  /spec              the specification, as plain text
GET  /health            "ok"
```

The API returns the validator's report unchanged, so a pipeline can depend on
it:

```sh
curl -s -X POST --data-binary @record.json \
  -H 'content-type: application/json' \
  https://<space-host>/api/validate
```

Add `?remote=1` to confirm locators against their hosts. A locator is a claim
that a file of a given size is at a URL; confirmation costs one HEAD request
per locator and no download. Without it, the report says plainly that locators
were accepted and not checked.

## What this does not do

The test emits no aggregate score, and it does not report on importance,
novelty, evaluation quality, operator reputation, or safety. Those are not
mechanical, and a suite that scored them would be a rating with an owner. It
also does not execute a record's falsifier by default: a record is untrusted
input, and a validator that runs commands from untrusted input cannot be run on
the records it is meant to check.

## Run it yourself

```
python3 sync.py
PORT=7860 python3 app.py
```

`sync.py` copies the validator, the schema, the specification and the worked
example from the repository this Space belongs to; `sync.py --check` fails if
those copies have drifted. The container has no third-party dependencies.

## Licence

The specification text is CC BY 4.0. The code, including this Space, is
Apache-2.0.
