// MIR-1 conformance validator, second implementation.
//
// This program was written from MIR-1-spec.md, not from validate.py, and it
// exists to test the specification rather than its author: if the text is
// implementable, two implementations that never share code agree on which
// records conform. Where they disagree, the text is what is wrong.
//
// Python 3.8 or later and no third-party dependencies for the reference
// implementation; Go 1.22 or later and the standard library for this one.
//
// Usage:
//
//	mir-validate RECORD.json [--artifacts DIR] [--execute-falsifier] [--verify-remote] [--json]
//
// Exit code 0 when every check passes, 1 otherwise, 2 when the record cannot be
// read. C-04 is checked for declaration only unless --execute-falsifier is
// passed, because running commands from an untrusted record is a code
// execution vector.
package main

import (
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"strings"
)

const suiteVersion = "1.5.0"

type checkResult struct {
	ID     string `json:"id"`
	OK     bool   `json:"ok"`
	Detail string `json:"detail"`
}

type report struct {
	Suite        string        `json:"suite"`
	MIRVersion   string        `json:"mir_version"`
	Record       string        `json:"record"`
	ManifestHash any           `json:"manifest_hash"`
	Checks       []checkResult `json:"checks"`
	Pass         bool          `json:"pass"`
	Failed       []string      `json:"failed"`
}

type invalidReport struct {
	Suite  string        `json:"suite"`
	Record string        `json:"record"`
	Checks []checkResult `json:"checks"`
	Pass   bool          `json:"pass"`
}

func main() {
	os.Exit(run(os.Args[1:]))
}

func run(args []string) int {
	var (
		recordPath       string
		artifacts        []string
		executeFalsifier bool
		verifyRemote     bool
		jsonOutput       bool
		schemaPath       string
	)

	for i := 0; i < len(args); i++ {
		arg := args[i]
		switch {
		case arg == "--artifacts":
			if i+1 >= len(args) {
				fmt.Fprintln(os.Stderr, "--artifacts requires a directory")
				return 2
			}
			i++
			artifacts = append(artifacts, args[i])
		case strings.HasPrefix(arg, "--artifacts="):
			artifacts = append(artifacts, strings.TrimPrefix(arg, "--artifacts="))
		case arg == "--execute-falsifier":
			executeFalsifier = true
		case arg == "--verify-remote":
			verifyRemote = true
		case arg == "--json":
			jsonOutput = true
		case arg == "--schema":
			if i+1 >= len(args) {
				fmt.Fprintln(os.Stderr, "--schema requires a path")
				return 2
			}
			i++
			schemaPath = args[i]
		case strings.HasPrefix(arg, "--schema="):
			schemaPath = strings.TrimPrefix(arg, "--schema=")
		case arg == "-h" || arg == "--help":
			usage()
			return 0
		case strings.HasPrefix(arg, "-"):
			fmt.Fprintf(os.Stderr, "unknown option %s\n", arg)
			return 2
		default:
			if recordPath != "" {
				fmt.Fprintf(os.Stderr, "unexpected argument %s\n", arg)
				return 2
			}
			recordPath = arg
		}
	}
	if recordPath == "" {
		usage()
		return 2
	}

	loaded, why := loadSchema(schemaPath)
	if loaded == nil {
		fmt.Fprintf(os.Stderr, "cannot load the schema: %s\n", why)
		return 2
	}
	activeSchema = loaded

	roots := append([]string{}, artifacts...)
	if cwd, err := os.Getwd(); err == nil {
		roots = append(roots, filepath.Join(cwd, "artifacts"))
	}
	if executable, err := os.Executable(); err == nil {
		roots = append(roots, filepath.Join(filepath.Dir(executable), "artifacts"))
	}
	roots = append(roots, filepath.Join(filepath.Dir(recordPath), "artifacts"))
	artifactsStore := newStore(roots)

	raw, err := os.ReadFile(recordPath)
	if err != nil {
		fmt.Fprintf(os.Stderr, "cannot read record: %v\n", err)
		return 2
	}

	record, err := decodeJSON(raw)
	if err != nil {
		// The parser's own wording differs between languages, so the report
		// carries a shared class and the diagnostic stays on stderr.
		detail := "invalid JSON: record does not parse"
		if errors.Is(err, errNotUTF8) || errors.Is(err, errLoneSurrogate) || errors.Is(err, errTooDeep) {
			detail = "invalid JSON: " + err.Error()
		} else {
			fmt.Fprintf(os.Stderr, "parse error: %v\n", err)
		}
		if jsonOutput {
			emit(invalidReport{
				Suite:  suiteVersion,
				Record: recordPath,
				Checks: []checkResult{{ID: "C-01", OK: false, Detail: detail}},
				Pass:   false,
			})
		} else {
			fmt.Printf("C-01 FAIL  %s\n", detail)
			fmt.Println("RESULT: FAIL")
		}
		return 1
	}

	results := runChecks(record, artifactsStore, executeFalsifier, true, verifyRemote)
	failed := []string{}
	for _, result := range results {
		if !result.OK {
			failed = append(failed, result.ID)
		}
	}

	if jsonOutput {
		emit(report{
			Suite:        suiteVersion,
			MIRVersion:   mirVersion,
			Record:       recordPath,
			ManifestHash: getField(asObject(record), "manifest_hash"),
			Checks:       results,
			Pass:         len(failed) == 0,
			Failed:       failed,
		})
	} else {
		fmt.Printf("MIR-1 conformance   suite %s   record %s\n", suiteVersion, recordPath)
		for _, result := range results {
			verdict := "PASS"
			if !result.OK {
				verdict = "FAIL"
			}
			fmt.Printf("%s %s  %s\n", result.ID, verdict, result.Detail)
		}
		if len(failed) > 0 {
			fmt.Printf("RESULT: FAIL (%d of %d)\n", len(failed), len(results))
		} else {
			fmt.Printf("RESULT: PASS (%d of %d)\n", len(results), len(results))
		}
	}

	if len(failed) > 0 {
		return 1
	}
	return 0
}

func emit(value any) {
	encoder := json.NewEncoder(os.Stdout)
	encoder.SetIndent("", "  ")
	encoder.SetEscapeHTML(false)
	_ = encoder.Encode(value)
}

func usage() {
	fmt.Fprintln(os.Stderr, "usage: mir-validate RECORD.json [--artifacts DIR] [--execute-falsifier] [--verify-remote] [--json]")
}

// runChecks aggregates the checks in the order the spec numbers them.
func runChecks(record any, artifacts *store, executeFalsifier, includeC09, verifyRemote bool) []checkResult {
	specs := []struct {
		id  string
		run func() (bool, string)
	}{
		{"C-01", func() (bool, string) { return checkC01(record) }},
		{"C-02", func() (bool, string) { return checkC02(record) }},
		{"C-03", func() (bool, string) { return checkC03(record, artifacts, verifyRemote) }},
		{"C-04", func() (bool, string) { return checkC04(record, executeFalsifier) }},
		{"C-05", func() (bool, string) { return checkC05(record) }},
		{"C-06", func() (bool, string) { return checkC06(record, artifacts) }},
		{"C-07", func() (bool, string) { return checkC07(record) }},
		{"C-08", func() (bool, string) { return checkC08(record, artifacts) }},
	}
	if includeC09 {
		specs = append(specs, struct {
			id  string
			run func() (bool, string)
		}{"C-09", func() (bool, string) {
			return checkC09(record, artifacts, executeFalsifier, verifyRemote)
		}})
	}
	specs = append(specs, struct {
		id  string
		run func() (bool, string)
	}{"C-10", func() (bool, string) {
		return checkC10(record, artifacts)
	}})
	specs = append(specs, struct {
		id  string
		run func() (bool, string)
	}{"C-11", func() (bool, string) {
		return checkC11(record)
	}})

	results := make([]checkResult, 0, len(specs))
	for _, spec := range specs {
		ok, detail := spec.run()
		results = append(results, checkResult{ID: spec.id, OK: ok, Detail: detail})
	}
	return results
}
