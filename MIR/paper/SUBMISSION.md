# arXiv submission

Everything arXiv needs is in `dist/`, built by `python3 make_arxiv.py`. Nothing
in this file is uploaded; it is the runbook.

## What gets uploaded

| File | Size | Contents |
|---|---|---|
| `dist/mir-1-source.tar.gz` | 13,457 bytes | `mir-1.tex`, and nothing else |
| `dist/mir-1-ancillary.tar.gz` | 332,624 bytes | both companions, both implementations, the examples, the adapter, the record, and the store |

Compiling the source archive with `pdflatex` under `SOURCE_DATE_EPOCH` reproduces
`mir-1.pdf` byte for byte, so what arXiv builds is what this release ships.

The ancillary archive is the reason this submission needs no repository and no
account anywhere: the paper carries its own checker. A reader who downloads it
can run the test in the paper without installing anything:

```
tar xzf mir-1-ancillary.tar.gz && cd mir-1-ancillary 2>/dev/null || true
python3 validate.py records/MIR-R1.json
python3 records/selfcheck.py
```

If arXiv flattens the archive into the extraction root, `README-ANCILLARY.md`
is the file to open first.

## Metadata

**Title**

```
Model Intervention Records: A Conformance Test for Weight-Space Claims
```

**Authors**

Empty in the source, deliberately: the title page names no individual. The PDF's
info dictionary names the collective identity as its author, and `CITATION.cff`
states the same. arXiv requires at least one
author in its own metadata, and the policy below is why this is the blocking
field.

**Abstract** (plain text, no LaTeX; line breaks are for this file only)

```
Claims that an intervention changes a language model's behavior are currently
not comparable. The interventions at issue are the ones now described as
weight-space programming: a model's weights read and edited directly, without
gradient descent or a training loop. Two reports of the same intervention can
both be accurate and still disagree about what happened, because neither record
states what was required not to change. We specify a record format with three
mandatory components: an executable falsifier; an invariant set containing at
least one metric outside the claim's own declared scoring function; and
content-addressed lineage to a base checkpoint. We then specify a mechanical
test that checks them, and we apply it to a published intervention: the record
satisfies ten of eleven checks and fails the one on cost disclosure. The test
emits no aggregate score and does not assess importance, safety, or
desirability. We release two dependency-free implementations, written from the
same text in different languages, and they agree on every input in the
repository. Adoption requires no authority: conformance is a claim that anyone
may check.
```

**Keywords**

`weight-space programming; model intervention records; weight editing;
conformance testing; reproducibility; evaluation validity`

Carried in the PDF metadata, the visible line under the title, the opening of
the abstract, the specification header, the repository README, and the
repository topics. The first term is the one current work uses for the subject,
and a reader who searches for it should find this document without anyone
pointing at it; the rest describe what the document adds to that term. arXiv has
no keyword field, so the same terms are in the abstract and in the PDF.

**Categories.** Primary `cs.LG`. Cross-list `cs.SE` (conformance testing of a
format) and `cs.CY` (research reporting practice). Secondary choices are
judgement calls; the primary is not.

**Comments.** `10 pages, 1 table. Specification, two reference implementations, and the worked example are in the ancillary files.`

**License.** CC BY 4.0. It is one of arXiv's selectable licences and it matches
the licence stated in the paper and in the specification.

**Journal reference / DOI.** None.

## Preflight, before touching the web form

```sh
cd paper
python3 make_pdf.py                        # rebuild the PDF, deterministically
python3 make_arxiv.py                      # rebuild both archives, deterministically
shasum -a 256 mir-1.pdf dist/*.tar.gz      # record the digests

# the ancillary archive is self-contained
rm -rf /tmp/anc && mkdir /tmp/anc && tar xzf dist/mir-1-ancillary.tar.gz -C /tmp/anc
cd /tmp/anc && python3 validate.py records/MIR-R1.json | tail -2
python3 records/selfcheck.py | tail -6
```

`make_pdf.py` needs `pdflatex` on PATH and compiles with the engine arXiv uses.
Verified 2026-11-14: pdfTeX 1.40.29 (TeX Live 2026), 10 pages, two builds
byte-identical, `/CreationDate D:20261114030000Z`.

An earlier PDF was obtained from a remote compilation service and carried
`/Producer xdvipdfmx`, which is XeTeX's driver, not pdfTeX. It embedded Latin
Modern where arXiv's pdflatex produces Computer Modern, so the shipped PDF and
the arXiv rendering were two different papers. Compiling locally removes both the
mismatch and the dependency on a third party seeing the source before release.

Expected: `RESULT: FAIL (1 of 11)`, and a selfcheck table containing
`the record as published  C-07  C-07  ok` and ending in
`every schema keyword is implemented  yes  yes  ok`. A pass on the record would mean the
worked example had been altered, not that the format works.

## The blocker

arXiv's identity policy, from `info.arxiv.org/help/policies/identity_and_affiliation.html`:

> Claimed affiliation should be current in the conventional sense: e.g.,
> physical presence, funding, e-mail address, etc.
>
> It is a violation of our policies to misrepresent your identity or
> organizational affiliation. Misrepresentation of identity or affiliation, for
> any reason, is possible grounds for immediate and permanent suspension.

A submission under a name that is not the submitter's is therefore not a grey
area; it is the one thing that gets an account suspended permanently, and the
paper is a claim about honest recording, so it cannot be introduced with a false
identity record. Endorsement compounds it: a new submitter in most subject areas
needs a code from someone who knows them or has read the paper, which is a
person, not a form.

So the package is ready and the last step is a decision that is not technical:

1. **Submit under a real name.** Ten minutes of form-filling; the disappearance
   rule is broken at the metadata field, permanently, and the name is indexed.
2. **Do not submit.** Publish `mir-1.pdf`, the spec, and the archives. No
   gatekeeper, no account, no identity. Costs the arXiv identifier, which is
   what makes a paper citable by people who do not already have the link.
3. **Submit to a double-blind venue.** The reviewers do not see the name; the
   organisers do. Requires a real identity at submission time and a deadline.

Nothing in this document chooses between them.
