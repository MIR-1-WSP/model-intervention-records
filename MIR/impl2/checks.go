package main

// Checks C-01 through C-11 of MIR-1. Each function returns the same (ok,
// detail) pair the reference implementation reports, because a second
// implementation is only useful if a disagreement is visible.

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io"
	"math/big"
	"os"
	"os/exec"
	"regexp"
	"sort"
	"strconv"
	"strings"
	"time"
)

const (
	mirVersion       = "1"
	falsifierTimeout = 30 * time.Second
)

var (
	hex64 = regexp.MustCompile(`^[0-9a-f]{64}$`)
)

// fileDigest is the SHA-256 of the bytes on disk. A store entry is
// content-addressed only if its bytes hash to the name it is filed under.
func fileDigest(path string) string {
	fh, err := os.Open(path)
	if err != nil {
		return ""
	}
	defer fh.Close()
	hasher := sha256.New()
	if _, err := io.Copy(hasher, fh); err != nil {
		return ""
	}
	return hex.EncodeToString(hasher.Sum(nil))
}

func contains(list []string, value string) bool {
	for _, item := range list {
		if item == value {
			return true
		}
	}
	return false
}

// normHash accepts a digest with or without the sha256: prefix, in either case,
// and returns it lowercase. Malformed values are not digests.
func normHash(value any) (string, bool) {
	text, ok := value.(string)
	if !ok {
		return "", false
	}
	text = referenceTrimSpace(text)
	text = strings.TrimPrefix(text, "sha256:")
	text = referenceLower(text)
	if !hex64.MatchString(text) {
		return "", false
	}
	return text, true
}

func integerValue(value any) (*big.Int, bool) {
	number, ok := value.(json.Number)
	if !ok {
		return nil, false
	}
	literal := string(number)
	if strings.ContainsAny(literal, ".eE") {
		return nil, false
	}
	parsed, ok := new(big.Int).SetString(literal, 10)
	return parsed, ok
}

// numericValue mirrors Python's isinstance(value, (int, float)): any number
// literal is accepted, booleans are not.
func numericValue(value any) (float64, bool) {
	number, ok := value.(json.Number)
	if !ok {
		return 0, false
	}
	parsed, err := number.Float64()
	if err != nil {
		if rangeError, ok := err.(*strconv.NumError); ok && rangeError.Err == strconv.ErrRange {
			return parsed, true
		}
		return 0, false
	}
	return parsed, true
}

func objectValue(value any) (*jobject, bool) {
	object, ok := value.(*jobject)
	return object, ok
}

func getField(object *jobject, key string) any {
	if object == nil {
		return nil
	}
	value, _ := object.get(key)
	return value
}

// ------------------------------------------------------------------ C-01

// C-01: the id is the content address of the record without the id.
func checkC01(record any) (bool, string) {
	object, ok := record.(*jobject)
	if !ok {
		return false, "record is not a JSON object"
	}
	declared, present := object.get("id")
	if !present || declared == nil {
		return true, "parses; no id declared"
	}
	body := newObject()
	for _, key := range object.keys {
		if key != "id" {
			body.set(key, object.vals[key])
		}
	}
	payload, err := canonicalBytes(body)
	if err != nil {
		return false, "record contains a number that cannot be represented"
	}
	digest, ok := normHash(declared)
	if !ok || digest != sha256Hex(payload) {
		return false, "id does not match the content address"
	}
	return true, "parses; id matches content address"
}

// ------------------------------------------------------------------ C-02

func checkC02(record any) (bool, string) {
	if activeSchema == nil {
		return false, "schema not loaded"
	}
	if problem := schemaProblem(record, activeSchema, activeSchema, "/"); problem != "" {
		return false, problem
	}
	return true, "matches the schema"
}

type namedValue struct {
	name  string
	value any
}

// hashFields lists every hash the record declares, by path. Two sources: the
// structural fields a record cannot omit, and any other string written as
// sha256:<digest>, so a record cannot carry a hash outside the checked fields
// and be treated as if it had not.
func hashFields(record any) []namedValue {
	items := []namedValue{}
	seen := map[string]bool{}
	add := func(name string, value any) {
		items = append(items, namedValue{name: name, value: value})
		seen[name] = true
	}
	addField := func(object *jobject, key, path string) {
		value, _ := object.get(key)
		add(path, value)
	}

	base, _ := objectValue(getField(asObject(record), "base"))
	addField(base, "hash", "base.hash")
	intervention, _ := objectValue(getField(asObject(record), "intervention"))
	addField(intervention, "payload_hash", "intervention.payload_hash")
	harness, _ := objectValue(getField(asObject(record), "harness"))
	addField(harness, "hash", "harness.hash")
	if asObject(record).has("supersedes") {
		add("supersedes", getField(asObject(record), "supersedes"))
	}

	runs, _ := getField(asObject(record), "runs").([]any)
	for i, run := range runs {
		runObject, ok := objectValue(run)
		if !ok {
			add(fmt.Sprintf("runs[%d]", i), nil)
			continue
		}
		for _, field := range []string{"harness_hash", "base_hash", "intervention_hash"} {
			value, _ := runObject.get(field)
			add(fmt.Sprintf("runs[%d].%s", i, field), value)
		}
	}

	// The schema accepts a lineage digest with or without the `sha256:` prefix.
	// Collecting only prefixed strings let a bare-hex entry name a file whose
	// bytes were never checked against it, so C-03 reported a resolved lineage
	// that did not resolve. Normalise here so both spellings are verified.
	lineage, _ := getField(asObject(record), "lineage").([]any)
	for i, entry := range lineage {
		if digest, ok := normHash(entry); ok {
			add(fmt.Sprintf("lineage[%d]", i), "sha256:"+digest)
		}
	}

	// Canonical form sorts keys, so document order is not a property of the
	// record. Sorting the discovered paths keeps the report a function of the
	// canonical bytes, which is what C-09 asserts when it re-imports.
	extra := []namedValue{}
	walkStrings(record, "", func(path string, value string) {
		if seen[path] {
			return
		}
		if strings.HasPrefix(referenceLower(referenceTrimSpace(value)), "sha256:") {
			extra = append(extra, namedValue{name: path, value: value})
		}
	})
	sort.Slice(extra, func(i, j int) bool { return extra[i].name < extra[j].name })
	return append(items, extra...)
}

func asObject(record any) *jobject {
	object, _ := record.(*jobject)
	return object
}

func walkStrings(node any, path string, visit func(string, string)) {
	switch value := node.(type) {
	case *jobject:
		for _, key := range value.keys {
			child := key
			if path != "" {
				child = path + "." + key
			}
			walkStrings(value.vals[key], child, visit)
		}
	case []any:
		for i, item := range value {
			walkStrings(item, fmt.Sprintf("%s[%d]", path, i), visit)
		}
	case string:
		visit(path, value)
	}
}

func checkC03(record any, store *store, verifyRemote bool) (bool, string) {
	items := hashFields(record)
	filtered := items[:0]
	for _, item := range items {
		// The record's own id is a content address of itself, checked by C-01.
		if item.name != "id" {
			filtered = append(filtered, item)
		}
	}
	items = filtered

	bad := []string{}
	located := 0
	verified := 0
	unverified := []string{}
	for _, item := range items {
		if item.value == nil {
			// An explicit null is declared absence, not a malformed hash. The
			// schema decides where null is allowed; C-03 decides what resolves.
			if strings.HasSuffix(item.name, "intervention_hash") || item.name == "supersedes" {
				continue
			}
			bad = append(bad, item.name+" (null)")
			continue
		}
		digest, ok := normHash(item.value)
		if !ok {
			bad = append(bad, item.name+" (malformed)")
			continue
		}
		kind, path := store.find(digest)
		if kind == "" {
			bad = append(bad, item.name+" (not in store)")
			continue
		}
		if kind == "locator" {
			loc, why := readLocator(path, digest)
			if loc == nil {
				bad = append(bad, fmt.Sprintf("%s (%s)", item.name, why))
				continue
			}
			located++
			if verifyRemote {
				if ok, why := remoteHead(loc, digest); !ok {
					bad = append(bad, fmt.Sprintf("%s (%s)", item.name, why))
					continue
				}
				verified++
			} else {
				unverified = append(unverified, item.name)
			}
		} else if kind == "bytes" {
			if fileDigest(path) != digest {
				bad = append(bad, item.name+" (bytes do not match the digest)")
			}
		}
	}
	if len(bad) > 0 {
		shown := bad
		if len(shown) > 6 {
			shown = shown[:6]
		}
		return false, fmt.Sprintf("%d of %d do not resolve: %s", len(bad), len(items), strings.Join(shown, ", "))
	}
	detail := fmt.Sprintf("%d/%d hashes resolve", len(items), len(items))
	if located > 0 {
		if verifyRemote {
			detail += fmt.Sprintf("; %d by locator, %d verified against the host", located, verified)
		} else {
			detail += fmt.Sprintf("; %d by locator, not checked against the host (--verify-remote)", located)
		}
	}
	return true, detail
}

// ------------------------------------------------------------------ C-04

func checkC04(record any, execute bool) (bool, string) {
	falsifier, ok := objectValue(getField(asObject(record), "falsifier"))
	if !ok {
		return false, "falsifier is not an object"
	}
	command, _ := falsifier.get("command")
	text, ok := command.(string)
	if !ok || referenceTrimSpace(text) == "" {
		return false, "falsifier.command missing or empty"
	}
	if returns, _ := falsifier.get("returns"); returns != "boolean" {
		return false, "falsifier.returns must be 'boolean'"
	}
	if !execute {
		return true, "declared, returns boolean (not executed; pass --execute-falsifier)"
	}

	ctx, cancel := context.WithTimeout(context.Background(), falsifierTimeout)
	defer cancel()
	cmd := exec.CommandContext(ctx, "sh", "-c", text)
	var stdout bytes.Buffer
	cmd.Stdout = &stdout
	cmd.Stderr = nil // the verdict is stdout; diagnostics are not part of it
	err := cmd.Run()
	if ctx.Err() == context.DeadlineExceeded {
		return false, fmt.Sprintf("falsifier exceeded %ds", int(falsifierTimeout.Seconds()))
	}
	_ = err // a non-zero exit is not a verdict; the output is

	output := referenceLower(referenceTrimSpace(stdout.String()))
	switch output {
	case "true", "false", "1", "0":
		return true, "executed; returned " + output
	default:
		shown := output
		if len(shown) > 40 {
			shown = shown[:40]
		}
		return false, fmt.Sprintf("falsifier output %s is not boolean", pyRepr(shown))
	}
}

// ------------------------------------------------------------------ C-05

func checkC05(record any) (bool, string) {
	invariants, ok := getField(asObject(record), "invariants").([]any)
	if !ok || len(invariants) == 0 {
		return false, "invariants missing or empty"
	}
	claim, _ := objectValue(getField(asObject(record), "claim"))
	rawScored, _ := claim.get("scoring_metrics")
	scoredList, ok := rawScored.([]any)
	if !ok || len(scoredList) == 0 {
		return false, "claim.scoring_metrics missing or empty"
	}
	scored := map[string]bool{}
	for _, m := range scoredList {
		if s, ok := m.(string); ok {
			scored[s] = true
		}
	}
	behavior, _ := claim.get("behavior")
	behaviorName, isString := behavior.(string)
	if !isString || !scored[behaviorName] {
		return false, fmt.Sprintf("claim.behavior \"%s\" is not among claim.scoring_metrics", pyStr(behavior))
	}
	problems := []string{}
	outside := 0
	for i, item := range invariants {
		invariant, ok := objectValue(item)
		if !ok {
			problems = append(problems, fmt.Sprintf("[%d] not an object", i))
			continue
		}
		for _, key := range []string{"property", "measurement", "metric", "direction", "bound"} {
			if !invariant.has(key) {
				problems = append(problems, fmt.Sprintf("[%d] missing %s", i, key))
			}
		}
		direction, _ := invariant.get("direction")
		if s, _ := direction.(string); s != "floor" && s != "ceiling" && s != "delta" {
			problems = append(problems, fmt.Sprintf("[%d] direction not one of floor|ceiling|delta", i))
		}
		bound, _ := invariant.get("bound")
		if _, ok := numericValue(bound); !ok {
			problems = append(problems, fmt.Sprintf("[%d] bound not numeric", i))
		}
		if metric, ok := invariant.get("metric"); ok {
			if s, _ := metric.(string); s != "" && !scored[s] {
				outside++
			}
		}
	}
	if len(problems) > 0 {
		shown := problems
		if len(shown) > 3 {
			shown = shown[:3]
		}
		return false, strings.Join(shown, "; ")
	}
	if outside == 0 {
		return false, fmt.Sprintf("no invariant outside the scoring function (%d declared, all inside)", len(invariants))
	}
	return true, fmt.Sprintf("%d invariants, %d outside scoring (scoring function declares %d)", len(invariants), outside, len(scored))
}

// ------------------------------------------------------------------ C-06

func looksLikeRecord(document any) bool {
	object, ok := objectValue(document)
	if !ok {
		return false
	}
	for _, key := range []string{"mir_version", "claim", "runs"} {
		if !object.has(key) {
			return false
		}
	}
	return true
}

func lineageWalk(record any, store *store, seen map[string]bool, depth int) (bool, int, string) {
	lineage, ok := getField(asObject(record), "lineage").([]any)
	if !ok {
		return false, 0, "lineage is not a list"
	}
	if len(lineage) == 0 {
		base, _ := objectValue(getField(asObject(record), "base"))
		digest, resolved := normHash(getField(base, "hash"))
		if resolved && store.present(digest) {
			return true, 0, ""
		}
		return false, 0, "a chain ends at a base that does not resolve"
	}
	if depth > 32 {
		return false, 0, "lineage is deeper than 32 records"
	}
	parents := 0
	for _, entry := range lineage {
		digest, ok := normHash(entry)
		if !ok {
			return false, 0, "malformed lineage entry"
		}
		if seen[digest] {
			return false, 0, "lineage contains a cycle"
		}
		kind, path := store.find(digest)
		if kind != "bytes" {
			return false, 0, fmt.Sprintf("lineage entry %s is not readable bytes", digest[:12])
		}
		raw, err := os.ReadFile(path)
		if err != nil {
			return false, 0, fmt.Sprintf("lineage entry %s is not JSON", digest[:12])
		}
		document, err := decodeJSON(raw)
		if err != nil {
			return false, 0, fmt.Sprintf("lineage entry %s is not JSON", digest[:12])
		}
		if !looksLikeRecord(document) {
			return false, 0, fmt.Sprintf("lineage entry %s is not a record", digest[:12])
		}
		next := map[string]bool{digest: true}
		for key := range seen {
			next[key] = true
		}
		ok, nested, why := lineageWalk(document, store, next, depth+1)
		if !ok {
			return false, 0, why
		}
		parents += 1 + nested
	}
	return true, parents, ""
}

func checkC06(record any, store *store) (bool, string) {
	lineage, ok := getField(asObject(record), "lineage").([]any)
	if !ok {
		return false, "lineage is not a list"
	}
	if len(lineage) == 0 {
		base, _ := objectValue(getField(asObject(record), "base"))
		digest, resolved := normHash(getField(base, "hash"))
		if resolved && store.present(digest) {
			return true, "empty lineage; applies directly to base"
		}
		return false, "empty lineage and base does not resolve"
	}
	ok, parents, why := lineageWalk(record, store, map[string]bool{}, 0)
	if !ok {
		return false, why
	}
	return true, fmt.Sprintf("lineage resolves to a base (%d parent record(s))", parents)
}

func checkC07(record any) (bool, string) {
	runs, ok := getField(asObject(record), "runs").([]any)
	if !ok || len(runs) == 0 {
		return false, "no runs"
	}
	missing := []string{}
	undisclosed := []string{}
	invalid := []string{}
	undisclosedRuns := map[int]bool{}
	for i, run := range runs {
		runObject, ok := objectValue(run)
		if !ok {
			return false, fmt.Sprintf("runs[%d] is not an object", i)
		}
		for _, key := range []string{"cost", "wall_time_s"} {
			value, present := runObject.get(key)
			if !present {
				missing = append(missing, fmt.Sprintf("runs[%d].%s", i, key))
				continue
			}
			if value == nil {
				undisclosed = append(undisclosed, fmt.Sprintf("runs[%d].%s", i, key))
				undisclosedRuns[i] = true
			} else if number, ok := numericValue(value); !ok {
				invalid = append(invalid, fmt.Sprintf("runs[%d].%s", i, key))
			} else if number < 0 || (key == "wall_time_s" && number == 0) {
				invalid = append(invalid, fmt.Sprintf("runs[%d].%s", i, key))
			}
		}
	}
	if len(missing) > 0 || len(invalid) > 0 {
		missingText := "none"
		if len(missing) > 0 {
			missingText = strings.Join(missing, ", ")
		}
		invalidText := "none"
		if len(invalid) > 0 {
			invalidText = strings.Join(invalid, ", ")
		}
		return false, fmt.Sprintf("missing: %s; non-numeric or out of range: %s", missingText, invalidText)
	}
	if len(undisclosed) > 0 {
		// MIR-1-04: an undisclosed run counts toward no requirement. The field is
		// present and null so that the omission is visible in the record rather
		// than absent from it; the check still fails.
		shown := undisclosed
		if len(shown) > 6 {
			shown = shown[:6]
		}
		return false, fmt.Sprintf("%d of %d runs declare cost or wall time as undisclosed: %s",
			len(undisclosedRuns), len(runs), strings.Join(shown, ", "))
	}
	return true, fmt.Sprintf("cost and wall_time_s present on %d run(s)", len(runs))
}

// ------------------------------------------------------------------ C-08

func checkC08(record any, store *store) (bool, string) {
	digest, ok := normHash(getField(asObject(record), "manifest_hash"))
	if !ok {
		return false, "manifest_hash missing or malformed"
	}
	if !store.present(digest) {
		return false, "manifest hash does not resolve"
	}
	return true, "manifest hash resolves"
}

// ------------------------------------------------------------------ C-09

func checkC09(record any, store *store, executeFalsifier, verifyRemote bool) (bool, string) {
	payload, err := canonicalBytes(record)
	if err != nil {
		return false, "record contains a number that cannot be represented"
	}
	reloaded, err := decodeJSON(payload)
	if err != nil {
		return false, "re-import failed: " + err.Error()
	}
	again, err := canonicalBytes(reloaded)
	if err != nil || !bytes.Equal(again, payload) {
		return false, "re-import is not canonical"
	}

	before := runChecks(record, store, executeFalsifier, false, verifyRemote)
	after := runChecks(reloaded, store, executeFalsifier, false, verifyRemote)
	if !sameResults(before, after) {
		return false, "results differ after round-trip"
	}
	return true, "byte-identical round-trip; results reproduce"
}

func sameResults(left, right []checkResult) bool {
	if len(left) != len(right) {
		return false
	}
	for i := range left {
		if left[i].ID != right[i].ID || left[i].OK != right[i].OK || left[i].Detail != right[i].Detail {
			return false
		}
	}
	return true
}

// ------------------------------------------------------------------ C-10

// foldSet keys a word set by its fold, so membership can be decided with foldKey.
func foldSet(words []string) map[string]bool {
	set := make(map[string]bool, len(words))
	for _, word := range words {
		set[foldKey(word)] = true
	}
	return set
}

var undisclosed = foldSet([]string{
	"", "not disclosed", "undisclosed", "not stated",
	"unknown", "none", "n/a", "na", "null",
	"anonymous", "withheld", "unattributed",
})

// disclosed mirrors value.strip().casefold() not in UNDISCLOSED. Lowercasing is
// not folding: "not ſtated" with a long s folds to "not stated" and must count as
// undisclosed, which strings.ToLower would have missed.
func disclosed(value any) bool {
	s, ok := value.(string)
	if !ok {
		return false
	}
	return !undisclosed[foldKey(referenceTrimSpace(s))]
}

func manifestMinReplications(record any, store *store) (int, bool) {
	digest, ok := normHash(getField(asObject(record), "manifest_hash"))
	if !ok {
		return 0, false
	}
	kind, path := store.find(digest)
	if kind != "bytes" {
		return 0, false
	}
	data, err := os.ReadFile(path)
	if err != nil {
		return 0, false
	}
	var manifest map[string]any
	if err := json.Unmarshal(data, &manifest); err != nil {
		return 0, false
	}
	params, _ := manifest["parameters"].(map[string]any)
	value, ok := params["min_independent_replications"].(float64)
	if !ok || value < 1 || value != float64(int(value)) {
		return 0, false
	}
	return int(value), true
}

func disclosedRun(run *jobject) bool {
	cost, okCost := numericValue(getField(run, "cost"))
	wall, okWall := numericValue(getField(run, "wall_time_s"))
	if !okCost || !okWall {
		return false
	}
	return cost >= 0 && wall > 0
}

func checkC10(record any, store *store) (bool, string) {
	object := asObject(record)
	status, ok := getField(object, "status").(string)
	if !ok || status == "" {
		return false, "status missing or empty"
	}
	if status == "draft" {
		return true, "status 'draft' makes no claim"
	}
	lineageOK, _ := checkC06(record, store)
	if status == "orphan" {
		if lineageOK {
			return false, "status 'orphan' with lineage that resolves"
		}
		return true, "status 'orphan'; lineage does not resolve"
	}
	if !lineageOK {
		return false, fmt.Sprintf("status '%s' requires lineage that resolves; MIR-1-06 requires the status orphan", status)
	}
	if status == "submitted" {
		return true, "status 'submitted'; lineage resolves"
	}
	claimant, ok := objectValue(getField(object, "claimant"))
	if !ok {
		return false, "claimant missing"
	}
	operator, _ := getField(claimant, "operator").(string)
	funding, _ := getField(claimant, "funding_source").(string)
	if referenceTrimSpace(operator) == "" {
		return false, "claimant.operator missing or empty"
	}
	if referenceTrimSpace(funding) == "" {
		return false, "claimant.funding_source missing or empty"
	}
	if !disclosed(funding) {
		return false, "claimant.funding_source is not a disclosed source, so independence cannot be established against it"
	}
	runs, _ := getField(object, "runs").([]any)
	independent := 0
	undisclosed := 0
	for _, item := range runs {
		run, ok := objectValue(item)
		if !ok {
			continue
		}
		if getField(run, "intervention_hash") == nil {
			continue // baseline: measures the base, never applies the claim
		}
		if !disclosedRun(run) {
			undisclosed++
			continue
		}
		otherOperator, isText := getField(run, "operator").(string)
		otherFunding := getField(run, "funding_source")
		if !isText || foldEqual(referenceTrimSpace(otherOperator), referenceTrimSpace(operator)) {
			continue
		}
		if !disclosed(otherFunding) {
			continue
		}
		if foldEqual(referenceTrimSpace(otherFunding.(string)), referenceTrimSpace(funding)) {
			continue
		}
		independent++
	}
	required, readable := manifestMinReplications(record, store)
	if !readable {
		return false, "the manifest is not held as bytes, so the replication threshold cannot be read"
	}
	if independent < required {
		detail := fmt.Sprintf("status 'replicated' with %d independent run(s); the declared manifest requires %d", independent, required)
		if undisclosed > 0 {
			detail += fmt.Sprintf(" (%d run(s) not counted: cost or wall time undisclosed)", undisclosed)
		}
		return false, detail
	}
	detail := fmt.Sprintf("status 'replicated'; %d independent run(s), %d required", independent, required)
	if undisclosed > 0 {
		detail += fmt.Sprintf(" (%d run(s) not counted: cost or wall time undisclosed)", undisclosed)
	}
	return true, detail
}

// ------------------------------------------------------------------ C-11

func checkC11(record any) (bool, string) {
	object := asObject(record)
	claim, _ := objectValue(getField(object, "claim"))
	behavior, _ := getField(claim, "behavior").(string)
	if referenceTrimSpace(behavior) == "" {
		return false, "claim.behavior missing or empty"
	}
	runs, ok := getField(object, "runs").([]any)
	if !ok || len(runs) == 0 {
		return false, "runs missing or empty"
	}
	missing := []string{}
	for index, item := range runs {
		run, ok := objectValue(item)
		if !ok {
			missing = append(missing, fmt.Sprintf("runs[%d]", index))
			continue
		}
		result, ok := objectValue(getField(run, "result"))
		if !ok {
			missing = append(missing, fmt.Sprintf("runs[%d]", index))
			continue
		}
		value := getField(result, behavior)
		if _, numeric := numericValue(value); !numeric {
			missing = append(missing, fmt.Sprintf("runs[%d]", index))
		}
	}
	if len(missing) > 0 {
		shown := missing
		if len(shown) > 3 {
			shown = shown[:3]
		}
		return false, fmt.Sprintf("%d of %d run(s) do not report claim.behavior '%s': %s", len(missing), len(runs), behavior, strings.Join(shown, ", "))
	}
	return true, fmt.Sprintf("all %d run(s) report '%s'", len(runs), behavior)
}
