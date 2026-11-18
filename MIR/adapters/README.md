# Adapters

A record format is adopted when the tools people already use emit it. An adapter
turns a tool's own run artifacts into a MIR-1 record, so that nothing is retyped
and nothing is remembered after the fact.

## dspy-wsp

`dspy_wsp.py` reads a run directory and writes a MIR-1.1 record whose payload is
a Weight Patch:

```
python3 adapters/dspy_wsp.py --run DIR --out record.json
python3 adapters/dspy_wsp.py --selftest
```

It expects three files:

| File | What it is |
|---|---|
| `manifest.json` | the tool's manifest; hashed as the harness and copied into the store |
| `edit.npz` | tensor name → float32 or float64 array of the edit |
| `run.json` | the fields the tool does not carry: `base`, `claim`, `invariants`, `falsifier`, `claimant`, `status`, `lineage`, and one or more `runs` with `cost`, `wall_time_s`, `operator`, `funding_source`, `started_at`, `n_units`, `samples_per_unit`, and any extra `results` |

The `.npz` is read with the standard library: an npz file is a zip of npy files.
No numpy is needed to run the adapter. `testdata/make_npz.py` uses numpy once,
to cut the committed fixture that the selftest reads, so the reader is exercised
on bytes a real numpy wrote rather than on bytes it wrote itself.

### Two conversions, stated rather than guessed

- `--mode add` (default): each array is a **delta**, and the patch carries an
  `add` operation at every index whose float32 value is non-zero. This is the
  form `edit.npz` names.
- `--mode set`: each array is an **absolute** value for the tensor it names, and
  the patch carries `set` operations for every index.

Both conversions are exercised by `--selftest`, because a documented path that
nothing runs is a path that stops working silently.

The adapter does not infer which one a tool meant. A wrong choice produces a
record that is conforming and wrong, which is the failure mode MIR-1 exists to
make visible rather than to add.

### Inverses

An additive edit inverts algebraically by negating its deltas, and the adapter
emits that inverse when it has no base bytes. It is not bit-identical, so P-05
reports `NOT RUN` rather than claiming a round trip it did not perform.

When `base` is a `wpp-array-0.1` container, the adapter reads the values the
edit will overwrite and emits an **exact** inverse. P-05 then executes the round
trip and passes, and the patch is reported `reversible`.

### Cost is captured, not remembered

MIR-1-04 fails a run that states no cost. The adapter therefore refuses to write
a record whose runs do not state `cost` and `wall_time_s`, unless
`--allow-undisclosed` is passed — and then it writes a record that fails C-07,
which is the honest outcome. `--cost` and `--wall-time` override the values in
`run.json`, so a wrapper that measures a run can pass them at the moment the run
finishes.

### What has not been tested

The adapter has been run against `testdata/edit.npz`, a fixture cut by numpy in
the shape the upstream tool publishes, and against nothing else. `dspy-wsp` was
not installed on the machine that wrote it. The file names and the delta
convention come from the tool's published artifacts, not from its source. If
the real layout differs, the adapter should be changed and the fixture re-cut;
a record produced from the wrong convention is still conforming, which is why
this paragraph exists.

### Size

A sparse edit produces one index and one delta per changed weight. A dense edit
of a large tensor produces a large JSON patch; that is a property of the format,
not of the adapter. `--mode add` on a tensor whose deltas are mostly zero is the
cheap case, and it is the case the tool publishes.

## Adding an adapter

An adapter is a script that reads a tool's artifacts and a run description, and
writes a record. It must not restate the conformance rules: it writes a record,
and the suite says whether the record conforms. The two adapters here share that
shape, and a third should start from whichever is closer.
