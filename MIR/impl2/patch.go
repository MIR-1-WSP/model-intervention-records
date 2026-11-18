package main

// MIR-1.1 Weight Patch checks P-01 through P-05.
//
// This file is the second implementation of MIR-1.1-Patch.md and shares no code
// with patchcheck.py. It is measured by crosscheck.py against the reference, so
// every detail string here is part of the format: two implementations that
// disagree about why a patch failed have not implemented the same document.

import (
	"bytes"
	"encoding/base64"
	"encoding/binary"
	"fmt"
	"math"
	"math/big"
	"os"
	"path/filepath"
	"sort"
	"strings"
)

const (
	arrayVersion    = "0.1"
	maxPatchLineage = 32
)

var sparseOps = map[string]bool{"set": true, "add": true, "scale": true}
var vectorOps = map[string]bool{"add_vector": true}

type patchCheck struct {
	ID     string `json:"id"`
	Result string `json:"result"`
	Detail string `json:"detail"`
}

type patchBlock struct {
	ID         string       `json:"id"`
	Checks     []patchCheck `json:"checks"`
	Qualifiers []string     `json:"qualifiers"`
	Failed     []string     `json:"failed"`
	NotRun     []string     `json:"not_run"`
}

type lineageEntry struct {
	patch  any
	digest string
}

type patchTensor struct {
	shape []int
	data  []byte
}

// patchDigest normalizes a patch identifier: `wpp:sha256:`, `sha256:`, or bare.
func patchDigest(value any) (string, bool) {
	text, ok := value.(string)
	if !ok {
		return "", false
	}
	text = strings.TrimPrefix(referenceTrimSpace(text), "wpp:")
	return normHash(text)
}

func shortDigest(text string) string {
	if len(text) > 12 {
		return text[:12]
	}
	return text
}

func patchIsPatch(document any) bool {
	object, ok := objectValue(document)
	return ok && object.has("wpp_version")
}

func asArray(value any) ([]any, bool) {
	array, ok := value.([]any)
	return array, ok
}

func asString(value any) (string, bool) {
	text, ok := value.(string)
	return text, ok
}

func opKind(op any) string {
	object, ok := objectValue(op)
	if !ok {
		return ""
	}
	kind, _ := object.get("op")
	text, _ := kind.(string)
	return text
}

func knownOp(op any) bool {
	kind := opKind(op)
	return sparseOps[kind] || vectorOps[kind]
}

func opFamily(op any) string {
	if sparseOps[opKind(op)] {
		return "sparse"
	}
	return "vector"
}

func ascending(value any) bool {
	array, ok := asArray(value)
	if !ok {
		return false
	}
	previous := int64(-1)
	for _, item := range array {
		number, ok := integerValue(item)
		if !ok || number.Sign() < 0 || !number.IsInt64() {
			return false
		}
		current := number.Int64()
		if current <= previous {
			return false
		}
		previous = current
	}
	return true
}

// patchID is the SHA-256 of the canonical bytes of the patch without its id.
func patchID(patch any) (string, bool) {
	object, ok := objectValue(patch)
	if !ok {
		return "", false
	}
	body := newObject()
	for _, key := range object.keys {
		if key == "id" {
			continue
		}
		value, _ := object.get(key)
		body.set(key, value)
	}
	payload, err := canonicalBytes(body)
	if err != nil {
		return "", false
	}
	return sha256Hex(payload), true
}

// ------------------------------------------------------------- structure

func structuralProblem(patch any) string {
	object, ok := objectValue(patch)
	if !ok {
		return ""
	}
	edit, ok := objectValue(getField(object, "edit"))
	if !ok {
		return ""
	}
	kind, _ := getField(edit, "type").(string)
	ops, ok := asArray(getField(edit, "ops"))
	if !ok || len(ops) == 0 {
		return ""
	}
	families := map[string]bool{}
	for index, op := range ops {
		if !knownOp(op) {
			continue
		}
		name := opKind(op)
		families[opFamily(op)] = true
		if kind == "sparse_delta" || kind == "operator" {
			allowed := sparseOps
			if kind == "operator" {
				allowed = vectorOps
			}
			if !allowed[name] {
				permitted := "set|add|scale"
				if kind == "operator" {
					permitted = "add_vector"
				}
				return fmt.Sprintf("edit.type '%s' permits %s operations only; op[%d] is '%s'",
					kind, permitted, index, name)
			}
		}
		entry, _ := objectValue(op)
		if sparseOps[name] || name == "add_vector" {
			field := "indices"
			if name == "add_vector" {
				field = "rows"
			}
			if !ascending(getField(entry, field)) {
				return fmt.Sprintf("op[%d] %s are not strictly ascending", index, field)
			}
		}
		if name == "set" || name == "add" {
			field := "values"
			if name == "add" {
				field = "deltas"
			}
			data, dataOK := asArray(getField(entry, field))
			indices, _ := asArray(getField(entry, "indices"))
			if !dataOK || len(data) != len(indices) {
				count := 0
				if dataOK {
					count = len(data)
				}
				return fmt.Sprintf("op[%d] has %d indices and %d %s",
					index, len(indices), count, field)
			}
		}
		if name == "scale" {
			factor, numberOK := numericValue(getField(entry, "factor"))
			if !numberOK {
				return ""
			}
			if factor == 0 {
				return fmt.Sprintf("op[%d] factor is zero", index)
			}
		}
		if name == "add_vector" {
			vector, vectorOK := asArray(getField(entry, "vector"))
			if vectorOK && len(vector) == 0 {
				return fmt.Sprintf("op[%d] vector is empty", index)
			}
		}
	}
	if kind == "mixed" {
		if !families["sparse"] || !families["vector"] {
			return "edit.type 'mixed' needs at least one sparse and one operator operation"
		}
	}
	return ""
}

// touchedCounts reports whether the locations are computable without the base,
// and how many there are.
func touchedCounts(edit any) (bool, int64) {
	object, ok := objectValue(edit)
	if !ok {
		return false, 0
	}
	ops, ok := asArray(getField(object, "ops"))
	if !ok || len(ops) == 0 {
		return false, 0
	}
	sparse := false
	vector := false
	for _, op := range ops {
		if sparseOps[opKind(op)] {
			sparse = true
		} else if vectorOps[opKind(op)] {
			vector = true
		}
	}
	if sparse && !vector {
		seen := map[string]bool{}
		for _, op := range ops {
			entry, _ := objectValue(op)
			tensor, _ := asString(getField(entry, "tensor"))
			indices, _ := asArray(getField(entry, "indices"))
			for _, item := range indices {
				number, ok := integerValue(item)
				if !ok {
					continue
				}
				seen[tensor+"\x00"+number.String()] = true
			}
		}
		return true, int64(len(seen))
	}
	if vector && !sparse {
		seen := map[string]bool{}
		for _, op := range ops {
			entry, _ := objectValue(op)
			tensor, _ := asString(getField(entry, "tensor"))
			rows, _ := asArray(getField(entry, "rows"))
			for _, item := range rows {
				number, ok := integerValue(item)
				if !ok {
					continue
				}
				key := tensor + "\x00" + number.String()
				if seen[key] {
					return false, 0
				}
				seen[key] = true
			}
		}
		var total int64
		for _, op := range ops {
			entry, _ := objectValue(op)
			rows, _ := asArray(getField(entry, "rows"))
			vectorValues, _ := asArray(getField(entry, "vector"))
			total += int64(len(rows)) * int64(len(vectorValues))
		}
		return true, total
	}
	return false, 0
}

// exactInverseProblem is "" when the exact inverse is structurally complete.
func exactInverseProblem(patch any) string {
	object, ok := objectValue(patch)
	if !ok {
		return "the patch has no operations"
	}
	inverse, ok := objectValue(getField(object, "inverse"))
	if !ok {
		return "no exact inverse is supplied"
	}
	if kind, _ := getField(inverse, "kind").(string); kind != "exact" {
		return "no exact inverse is supplied"
	}
	edit, ok := objectValue(getField(object, "edit"))
	if !ok {
		return "the patch has no operations"
	}
	ops, ok := asArray(getField(edit, "ops"))
	if !ok || len(ops) == 0 {
		return "the patch has no operations"
	}
	prior, ok := asArray(getField(inverse, "prior"))
	if !ok || len(prior) == 0 {
		return "the exact inverse carries no prior values"
	}
	covered := map[string]bool{}
	for index, raw := range prior {
		entry, ok := objectValue(raw)
		if !ok {
			return fmt.Sprintf("prior[%d] is not an object", index)
		}
		tensor, _ := asString(getField(entry, "tensor"))
		if tensor == "" {
			return fmt.Sprintf("prior[%d] has no tensor", index)
		}
		locations, _ := asArray(getField(entry, "indices"))
		if !ascending(getField(entry, "indices")) {
			return fmt.Sprintf("prior[%d] indices are not strictly ascending", index)
		}
		values, valuesOK := asArray(getField(entry, "values"))
		if !valuesOK || len(values) != len(locations) {
			count := 0
			if valuesOK {
				count = len(values)
			}
			return fmt.Sprintf("prior[%d] has %d indices and %d values", index, len(locations), count)
		}
		for _, item := range locations {
			number, _ := integerValue(item)
			covered[tensor+"\x00"+number.String()] = true
		}
	}
	computable, _ := touchedCounts(edit)
	if computable {
		onlySparse := true
		for _, op := range ops {
			if !sparseOps[opKind(op)] {
				onlySparse = false
			}
		}
		if onlySparse {
			type missing struct {
				tensor string
				index  int64
			}
			wanted := map[string]missing{}
			for _, op := range ops {
				entry, _ := objectValue(op)
				tensor, _ := asString(getField(entry, "tensor"))
				indices, _ := asArray(getField(entry, "indices"))
				for _, item := range indices {
					number, _ := integerValue(item)
					key := tensor + "\x00" + number.String()
					wanted[key] = missing{tensor, number.Int64()}
				}
			}
			absent := []missing{}
			for key, item := range wanted {
				if !covered[key] {
					absent = append(absent, item)
				}
			}
			if len(absent) > 0 {
				sort.Slice(absent, func(i, j int) bool {
					if absent[i].tensor != absent[j].tensor {
						return absent[i].tensor < absent[j].tensor
					}
					return absent[i].index < absent[j].index
				})
				return fmt.Sprintf("the exact inverse does not cover %d location(s); the first is %s[%d]",
					len(absent), absent[0].tensor, absent[0].index)
			}
		}
	}
	return ""
}

// ------------------------------------------------------------ containers

func parseContainer(raw []byte) (map[string]*patchTensor, string) {
	document, err := decodeJSON(raw)
	if err != nil {
		return nil, "base is not a wpp-array-0.1 container"
	}
	object, ok := objectValue(document)
	if !ok {
		return nil, "base is not a wpp-array-0.1 container"
	}
	if version, _ := getField(object, "wpp_array_version").(string); version != arrayVersion {
		return nil, "base is not a wpp-array-0.1 container"
	}
	tensors, ok := objectValue(getField(object, "tensors"))
	if !ok {
		return nil, "container has no tensors object"
	}
	names := append([]string{}, tensors.keys...)
	sort.Strings(names)
	out := map[string]*patchTensor{}
	for _, name := range names {
		entry, ok := objectValue(getField(tensors, name))
		if !ok {
			return nil, fmt.Sprintf("tensor '%s' is not an object", name)
		}
		if dtype, _ := getField(entry, "dtype").(string); dtype != "float32" {
			return nil, fmt.Sprintf("tensor '%s' is not float32", name)
		}
		shapeValues, ok := asArray(getField(entry, "shape"))
		if !ok || len(shapeValues) == 0 {
			return nil, fmt.Sprintf("tensor '%s' has no shape", name)
		}
		shape := make([]int, 0, len(shapeValues))
		product := big.NewInt(1)
		for _, dimension := range shapeValues {
			number, ok := integerValue(dimension)
			if !ok || number.Sign() <= 0 || !number.IsInt64() {
				return nil, fmt.Sprintf("tensor '%s' has a non-positive dimension", name)
			}
			shape = append(shape, int(number.Int64()))
			product.Mul(product, number)
		}
		text, ok := getField(entry, "data_b64").(string)
		if !ok {
			return nil, fmt.Sprintf("tensor '%s' has no data_b64", name)
		}
		if strings.ContainsAny(text, "\r\n") {
			return nil, fmt.Sprintf("tensor '%s' data is not valid base64", name)
		}
		payload, err := base64.StdEncoding.DecodeString(text)
		if err != nil {
			return nil, fmt.Sprintf("tensor '%s' data is not valid base64", name)
		}
		if product.Cmp(big.NewInt(int64(len(payload)/4))) != 0 || len(payload)%4 != 0 {
			return nil, fmt.Sprintf("tensor '%s' data does not match its shape", name)
		}
		out[name] = &patchTensor{shape: shape, data: payload}
	}
	return out, ""
}

// finite32 is false when the operand has no finite binary32 representation.
func finite32(value float64) bool {
	return !math.IsInf(float64(float32(value)), 0)
}

func readF32(tensor *patchTensor, index int) float32 {
	return math.Float32frombits(binary.LittleEndian.Uint32(tensor.data[4*index:]))
}

func writeF32(tensor *patchTensor, index int, value float32) {
	binary.LittleEndian.PutUint32(tensor.data[4*index:], math.Float32bits(value))
}

// applyOps applies operations in order. Arithmetic is binary64 rounded once to
// binary32 (MIR-1.1 5.3), so the last bit does not depend on the compiler.
func applyOps(tensors map[string]*patchTensor, ops []any) (int, string) {
	changed := 0
	for index, raw := range ops {
		op, _ := objectValue(raw)
		name := opKind(raw)
		tensorName, _ := asString(getField(op, "tensor"))
		tensor, ok := tensors[tensorName]
		if !ok {
			return changed, fmt.Sprintf("op[%d] names unknown tensor '%s'", index, tensorName)
		}
		total := len(tensor.data) / 4
		if sparseOps[name] {
			locations, _ := asArray(getField(op, "indices"))
			var data []any
			if name == "set" {
				data, _ = asArray(getField(op, "values"))
			} else if name == "add" {
				data, _ = asArray(getField(op, "deltas"))
			}
			var factor float64
			if name == "scale" {
				factor, _ = numericValue(getField(op, "factor"))
			}
			for offset, item := range locations {
				number, _ := integerValue(item)
				if !number.IsInt64() || number.Int64() >= int64(total) {
					return changed, fmt.Sprintf("op[%d] index %s is outside tensor '%s' (%d values)",
						index, number.String(), tensorName, total)
				}
				location := int(number.Int64())
				before := readF32(tensor, location)
				var after float32
				switch name {
				case "set":
					value, _ := numericValue(data[offset])
					if !finite32(value) {
						return changed, fmt.Sprintf("op[%d] carries a value outside the binary32 range", index)
					}
					after = float32(value)
				case "add":
					value, _ := numericValue(data[offset])
					if !finite32(value) {
						return changed, fmt.Sprintf("op[%d] carries a value outside the binary32 range", index)
					}
					after = float32(float64(before) + value)
				default:
					if !finite32(factor) {
						return changed, fmt.Sprintf("op[%d] carries a value outside the binary32 range", index)
					}
					after = float32(float64(before) * factor)
				}
				writeF32(tensor, location, after)
				if readF32(tensor, location) != before {
					changed++
				}
			}
			continue
		}
		if name == "add_vector" {
			if len(tensor.shape) < 2 {
				return changed, fmt.Sprintf("op[%d] add_vector needs a tensor of rank 2 or more", index)
			}
			trailing := 1
			for _, dimension := range tensor.shape[1:] {
				trailing *= dimension
			}
			vectorValues, _ := asArray(getField(op, "vector"))
			if len(vectorValues) != trailing {
				return changed, fmt.Sprintf("op[%d] vector has %d values; tensor '%s' has %d trailing dimensions",
					index, len(vectorValues), tensorName, trailing)
			}
			factor := 1.0
			if value, present := op.get("scale"); present {
				parsed, ok := numericValue(value)
				if !ok {
					return changed, fmt.Sprintf("op[%d] scale is not a number", index)
				}
				factor = parsed
			}
			if !finite32(factor) {
				return changed, fmt.Sprintf("op[%d] carries a value outside the binary32 range", index)
			}
			rows, _ := asArray(getField(op, "rows"))
			for _, item := range rows {
				number, _ := integerValue(item)
				if !number.IsInt64() || number.Int64() >= int64(tensor.shape[0]) {
					return changed, fmt.Sprintf("op[%d] row %s is outside tensor '%s' (%d rows)",
						index, number.String(), tensorName, tensor.shape[0])
				}
				base := int(number.Int64()) * trailing
				for column := 0; column < trailing; column++ {
					location := base + column
					value, _ := numericValue(vectorValues[column])
					if !finite32(value) {
						return changed, fmt.Sprintf("op[%d] carries a value outside the binary32 range", index)
					}
					before := readF32(tensor, location)
					writeF32(tensor, location, float32(float64(before)+factor*value))
					if readF32(tensor, location) != before {
						changed++
					}
				}
			}
			continue
		}
		return changed, fmt.Sprintf("op[%d] has unknown kind", index)
	}
	return changed, ""
}

func applyPrior(tensors map[string]*patchTensor, prior []any) string {
	for index, raw := range prior {
		entry, _ := objectValue(raw)
		tensorName, _ := asString(getField(entry, "tensor"))
		tensor, ok := tensors[tensorName]
		if !ok {
			return fmt.Sprintf("prior[%d] names unknown tensor '%s'", index, tensorName)
		}
		total := len(tensor.data) / 4
		locations, _ := asArray(getField(entry, "indices"))
		values, _ := asArray(getField(entry, "values"))
		for offset, item := range locations {
			number, _ := integerValue(item)
			if !number.IsInt64() || number.Int64() >= int64(total) {
				return fmt.Sprintf("prior[%d] index %s is outside tensor '%s' (%d values)",
					index, number.String(), tensorName, total)
			}
			value, _ := numericValue(values[offset])
			if !finite32(value) {
				return fmt.Sprintf("prior[%d] carries a value outside the binary32 range", index)
			}
			writeF32(tensor, int(number.Int64()), float32(value))
		}
	}
	return ""
}

func snapshot(tensors map[string]*patchTensor) map[string][]byte {
	out := make(map[string][]byte, len(tensors))
	for name, tensor := range tensors {
		out[name] = append([]byte{}, tensor.data...)
	}
	return out
}

func sameTensors(left, right map[string][]byte) (bool, string) {
	names := make([]string, 0, len(right))
	for name := range right {
		names = append(names, name)
	}
	sort.Strings(names)
	for _, name := range names {
		if !bytes.Equal(right[name], left[name]) {
			return false, name
		}
	}
	return true, ""
}

// ------------------------------------------------------- record access

func payloadBytes(record any, artifacts *store) (string, []byte, bool) {
	object, ok := objectValue(record)
	if !ok {
		return "", nil, false
	}
	intervention, ok := objectValue(getField(object, "intervention"))
	if !ok {
		return "", nil, false
	}
	if kind, _ := getField(intervention, "type").(string); kind != "weights" {
		return "", nil, false
	}
	digestValue, ok := normHash(getField(intervention, "payload_hash"))
	if !ok {
		return "", nil, false
	}
	kind, path := artifacts.find(digestValue)
	if kind != "bytes" {
		return "", nil, false
	}
	raw, err := os.ReadFile(path)
	if err != nil {
		return "", nil, false
	}
	return digestValue, raw, true
}

func loadPatch(raw []byte) (any, bool) {
	document, err := decodeJSON(raw)
	if err != nil || !patchIsPatch(document) {
		return nil, false
	}
	return document, true
}

func patchLineage(record any, artifacts *store) ([]lineageEntry, string) {
	entries := []lineageEntry{}
	var walk func(node any, seen map[string]bool, depth int) string
	walk = func(node any, seen map[string]bool, depth int) string {
		if depth > maxPatchLineage {
			return fmt.Sprintf("patch lineage is deeper than %d records", maxPatchLineage)
		}
		object, ok := objectValue(node)
		if !ok {
			return ""
		}
		lineage, ok := asArray(getField(object, "lineage"))
		if !ok {
			return ""
		}
		for _, value := range lineage {
			parentDigest, ok := normHash(value)
			if !ok {
				return "malformed lineage entry"
			}
			if seen[parentDigest] {
				return "lineage contains a cycle"
			}
			path := artifacts.resolvePath(parentDigest)
			if path == "" {
				return "lineage entry " + shortDigest(parentDigest) + " is not readable bytes"
			}
			raw, err := os.ReadFile(path)
			if err != nil {
				return "lineage entry " + shortDigest(parentDigest) + " is not readable bytes"
			}
			parent, err := decodeJSON(raw)
			if err != nil {
				return "lineage entry " + shortDigest(parentDigest) + " is not JSON"
			}
			next := map[string]bool{parentDigest: true}
			for key := range seen {
				next[key] = true
			}
			if problem := walk(parent, next, depth+1); problem != "" {
				return problem
			}
			_, parentRaw, ok := payloadBytes(parent, artifacts)
			if !ok {
				continue
			}
			patch, ok := loadPatch(parentRaw)
			if !ok {
				continue
			}
			identifier, _ := patchID(patch)
			entries = append(entries, lineageEntry{patch: patch, digest: identifier})
		}
		return ""
	}
	problem := walk(record, map[string]bool{}, 0)
	return entries, problem
}

// store.resolve returns the path of stored bytes, or "" for a locator.
func (s *store) resolvePath(digest string) string {
	kind, path := s.find(digest)
	if kind != "bytes" {
		return ""
	}
	return path
}

// --------------------------------------------------------------- checks

func checkP01(record, patch any, artifacts *store) (string, string) {
	object, _ := objectValue(patch)
	base, ok := objectValue(getField(object, "base"))
	if !ok {
		return "fail", "patch.base is missing or malformed"
	}
	declared, ok := patchDigest(getField(base, "checkpoint_hash"))
	if !ok {
		return "fail", "base.checkpoint_hash is missing or malformed"
	}
	recordObject, _ := objectValue(record)
	recordBase, _ := objectValue(getField(recordObject, "base"))
	actual, ok := normHash(getField(recordBase, "hash"))
	if !ok {
		return "fail", "the record's base.hash is missing or malformed"
	}
	if declared != actual {
		return "fail", "base.checkpoint_hash does not match the record's base.hash"
	}
	if kind, _ := artifacts.find(declared); kind == "" {
		return "fail", "base checkpoint does not resolve"
	}
	return "pass", "base checkpoint resolves and matches the record's base.hash"
}

func checkP02(patch any, raw []byte, schema map[string]any) (string, string) {
	if schema == nil {
		return "fail", "not a conforming patch: the patch schema could not be loaded"
	}
	if problem := schemaProblem(patch, schema, schema, "/"); problem != "" {
		return "fail", "not a conforming patch: " + problem
	}
	if problem := structuralProblem(patch); problem != "" {
		return "fail", problem
	}
	object, _ := objectValue(patch)
	declared, ok := patchDigest(getField(object, "id"))
	if !ok {
		return "fail", "id is missing or malformed"
	}
	actual, ok := patchID(patch)
	if !ok {
		return "fail", "the patch contains a number that cannot be represented"
	}
	if declared != actual {
		return "fail", "id does not match the content address"
	}
	canonical := false
	if payload, err := canonicalBytes(patch); err == nil {
		canonical = bytes.Equal(raw, payload)
	}
	edit, _ := objectValue(getField(object, "edit"))
	computable, count := touchedCounts(edit)
	if computable {
		declaredCount, ok := integerValue(getField(edit, "num_changed"))
		if !ok {
			return "fail", "num_changed is not an integer"
		}
		if !declaredCount.IsInt64() || declaredCount.Int64() != count {
			return "fail", fmt.Sprintf("num_changed is %s; the operations address %d location(s)",
				declaredCount.String(), count)
		}
	}
	location := "stored canonically"
	if !canonical {
		location = "stored bytes are not canonical"
	}
	changed := fmt.Sprintf("recomputed (%d)", count)
	if !computable {
		changed = fmt.Sprintf("declared (%s), not recomputable without the base",
			showValue(getField(edit, "num_changed")))
	}
	return "pass", fmt.Sprintf("conforms; id matches; %s; num_changed %s", location, changed)
}

func touched(patch any) map[string]map[string]map[string]bool {
	out := map[string]map[string]map[string]bool{}
	object, _ := objectValue(patch)
	edit, _ := objectValue(getField(object, "edit"))
	ops, _ := asArray(getField(edit, "ops"))
	for _, op := range ops {
		entry, _ := objectValue(op)
		tensor, _ := asString(getField(entry, "tensor"))
		if out[tensor] == nil {
			out[tensor] = map[string]map[string]bool{"sparse": {}, "vector": {}}
		}
		kind := opKind(op)
		if sparseOps[kind] {
			indices, _ := asArray(getField(entry, "indices"))
			for _, item := range indices {
				number, _ := integerValue(item)
				out[tensor]["sparse"][number.String()] = true
			}
		} else if vectorOps[kind] {
			rows, _ := asArray(getField(entry, "rows"))
			for _, item := range rows {
				number, _ := integerValue(item)
				out[tensor]["vector"][number.String()] = true
			}
		}
	}
	return out
}

func overlapTouched(left, right map[string]map[string]map[string]bool) (int, int) {
	locations := 0
	undetermined := 0
	for tensor, one := range left {
		two, ok := right[tensor]
		if !ok {
			continue
		}
		for key := range one["sparse"] {
			if two["sparse"][key] {
				locations++
			}
		}
		for key := range one["vector"] {
			if two["vector"][key] {
				locations++
			}
		}
		if (len(one["sparse"]) > 0 && len(two["vector"]) > 0) ||
			(len(one["vector"]) > 0 && len(two["sparse"]) > 0) {
			undetermined++
		}
	}
	return locations, undetermined
}

func checkP03(patch any, ancestors []lineageEntry) (string, string) {
	object, _ := objectValue(patch)
	dependencies, _ := asArray(getField(object, "dependencies"))
	external, _ := asArray(getField(object, "external_dependencies"))
	reachable := map[string]any{}
	for _, ancestor := range ancestors {
		if ancestor.digest == "" {
			continue
		}
		if _, present := reachable[ancestor.digest]; !present {
			reachable[ancestor.digest] = ancestor.patch
		}
	}
	externalDigests := map[string]bool{}
	for _, value := range external {
		normalized, ok := patchDigest(value)
		if !ok {
			return "fail", "external_dependencies contains a malformed identifier"
		}
		externalDigests[normalized] = true
	}
	resolved := 0
	skipped := 0
	for _, value := range dependencies {
		normalized, ok := patchDigest(value)
		if !ok {
			return "fail", "dependencies contains a malformed identifier"
		}
		if externalDigests[normalized] {
			skipped++
			continue
		}
		ancestor, present := reachable[normalized]
		if !present {
			return "fail", "dependency " + shortDigest(normalized) +
				" is not in the patch lineage before this patch"
		}
		if problem := structuralProblem(ancestor); problem != "" {
			return "fail", fmt.Sprintf("dependency %s is not a conforming patch (%s)",
				shortDigest(normalized), problem)
		}
		actual, ok := patchID(ancestor)
		if !ok || actual != normalized {
			return "fail", "dependency " + shortDigest(normalized) +
				" does not match its content address"
		}
		resolved++
	}
	locations := 0
	undetermined := 0
	own := touched(patch)
	for _, ancestor := range ancestors {
		if externalDigests[ancestor.digest] {
			continue
		}
		found, unknown := overlapTouched(own, touched(ancestor.patch))
		locations += found
		undetermined += unknown
	}
	conflict := "no overlap with earlier patches"
	if undetermined > 0 {
		conflict = "overlap with an earlier patch undetermined without base shapes"
	} else if locations > 0 {
		conflict = fmt.Sprintf("%d overlapping location(s) with earlier patches", locations)
	}
	detail := fmt.Sprintf("dependencies resolve in order: %d", resolved)
	if skipped > 0 {
		detail += fmt.Sprintf("; declared external: %d", skipped)
	}
	detail += "; " + conflict
	return "pass", detail
}

func memberMatches(record, patch any, member string, artifacts *store) string {
	patchObject, _ := objectValue(patch)
	recordObject, _ := objectValue(record)
	reference, hasReference := patchDigest(getField(patchObject, member+"_hash"))
	_, carried := patchObject.get(member)
	expected, err := canonicalBytes(getField(recordObject, member))
	if err != nil {
		return fmt.Sprintf("the record's %s cannot be serialized", member)
	}
	if carried {
		actual, err := canonicalBytes(getField(patchObject, member))
		if err != nil {
			return fmt.Sprintf("the patch's %s cannot be serialized", member)
		}
		if !bytes.Equal(actual, expected) {
			return fmt.Sprintf("the patch's %s differ from the record's", member)
		}
	}
	if hasReference {
		path := artifacts.resolvePath(reference)
		if path == "" {
			return fmt.Sprintf("%s_hash does not resolve", member)
		}
		raw, err := os.ReadFile(path)
		if err != nil {
			return fmt.Sprintf("%s_hash does not resolve", member)
		}
		if !bytes.Equal(raw, expected) {
			return fmt.Sprintf("%s_hash does not resolve to the record's %s", member, member)
		}
	}
	if !carried && !hasReference {
		return fmt.Sprintf("the patch carries neither %s nor %s_hash", member, member)
	}
	return ""
}

func checkP04(record, patch any, artifacts *store) (string, string) {
	for _, member := range []string{"invariants", "falsifier"} {
		if problem := memberMatches(record, patch, member, artifacts); problem != "" {
			return "fail", problem
		}
	}
	return "pass", "invariants and falsifier match the record"
}

func checkP05(record, patch any, ancestors []lineageEntry, artifacts *store) (string, string) {
	object, _ := objectValue(patch)
	inverse, ok := objectValue(getField(object, "inverse"))
	if !ok {
		return "not run", "no exact inverse is supplied; algebraic or absent"
	}
	if kind, _ := getField(inverse, "kind").(string); kind != "exact" {
		return "not run", "no exact inverse is supplied; algebraic or absent"
	}
	recordObject, _ := objectValue(record)
	recordBase, _ := objectValue(getField(recordObject, "base"))
	baseDigest, ok := normHash(getField(recordBase, "hash"))
	if !ok {
		return "not run", "base bytes are not held in the store"
	}
	path := artifacts.resolvePath(baseDigest)
	if path == "" {
		return "not run", "base bytes are not held in the store"
	}
	raw, err := os.ReadFile(path)
	if err != nil {
		return "not run", "base bytes are not readable"
	}
	tensors, why := parseContainer(raw)
	if tensors == nil {
		return "not run", why
	}
	for _, ancestor := range ancestors {
		ancestorObject, _ := objectValue(ancestor.patch)
		edit, _ := objectValue(getField(ancestorObject, "edit"))
		ops, _ := asArray(getField(edit, "ops"))
		if _, why := applyOps(tensors, ops); why != "" {
			return "not run", fmt.Sprintf("ancestor patch %s does not apply to the base (%s)",
				shortDigest(ancestor.digest), why)
		}
	}
	before := snapshot(tensors)
	edit, _ := objectValue(getField(object, "edit"))
	ops, _ := asArray(getField(edit, "ops"))
	changed, why := applyOps(tensors, ops)
	if why != "" {
		return "fail", "the patch does not apply to its base (" + why + ")"
	}
	if changed == 0 {
		return "fail", "the patch changes no weights"
	}
	prior, _ := asArray(getField(inverse, "prior"))
	if why := applyPrior(tensors, prior); why != "" {
		return "fail", why
	}
	after := snapshot(tensors)
	if same, name := sameTensors(before, after); !same {
		return "fail", fmt.Sprintf("the exact inverse does not restore bit-identical weights (tensor '%s')", name)
	}
	return "pass", fmt.Sprintf("round-trip restores bit-identically; tensors: %d, values changed: %d",
		len(after), changed)
}

// ------------------------------------------------------------ evaluation

func loadPatchSchema() map[string]any {
	candidates := []string{}
	if executable, err := os.Executable(); err == nil {
		candidates = append(candidates,
			filepath.Join(filepath.Dir(executable), "..", "patch-schema.json"),
			filepath.Join(filepath.Dir(executable), "patch-schema.json"))
	}
	if cwd, err := os.Getwd(); err == nil {
		candidates = append(candidates, filepath.Join(cwd, "patch-schema.json"),
			filepath.Join(cwd, "..", "patch-schema.json"))
	}
	for _, candidate := range candidates {
		raw, err := os.ReadFile(candidate)
		if err != nil {
			continue
		}
		document, err := decodeJSON(raw)
		if err != nil {
			return nil
		}
		object, ok := objectValue(document)
		if !ok {
			return nil
		}
		converted := make(map[string]any, len(object.keys))
		for _, key := range object.keys {
			value, _ := object.get(key)
			converted[key] = value
		}
		return converted
	}
	return nil
}

// samePatchBlocks compares two patch blocks field by field, the way sameResults
// compares the eleven checks.
func samePatchBlocks(left, right *patchBlock) bool {
	if left == nil || right == nil {
		return left == nil && right == nil
	}
	if left.ID != right.ID || len(left.Checks) != len(right.Checks) ||
		len(left.Qualifiers) != len(right.Qualifiers) ||
		len(left.Failed) != len(right.Failed) || len(left.NotRun) != len(right.NotRun) {
		return false
	}
	for i := range left.Checks {
		if left.Checks[i] != right.Checks[i] {
			return false
		}
	}
	for i := range left.Qualifiers {
		if left.Qualifiers[i] != right.Qualifiers[i] {
			return false
		}
	}
	for i := range left.Failed {
		if left.Failed[i] != right.Failed[i] {
			return false
		}
	}
	for i := range left.NotRun {
		if left.NotRun[i] != right.NotRun[i] {
			return false
		}
	}
	return true
}

// evaluatePatch returns the patch block, or nil when the payload is not a patch.
func evaluatePatch(record any, artifacts *store) *patchBlock {
	_, raw, ok := payloadBytes(record, artifacts)
	if !ok {
		return nil
	}
	patch, ok := loadPatch(raw)
	if !ok {
		return nil
	}
	schema := loadPatchSchema()
	ancestors, lineageProblem := patchLineage(record, artifacts)

	results := []patchCheck{}
	add := func(id string, state string, detail string) {
		results = append(results, patchCheck{ID: id, Result: state, Detail: detail})
	}
	state, detail := checkP01(record, patch, artifacts)
	add("P-01", state, detail)
	state, detail = checkP02(patch, raw, schema)
	add("P-02", state, detail)
	if lineageProblem != "" {
		add("P-03", "fail", lineageProblem)
	} else {
		state, detail = checkP03(patch, ancestors)
		add("P-03", state, detail)
	}
	state, detail = checkP04(record, patch, artifacts)
	add("P-04", state, detail)
	if lineageProblem != "" {
		add("P-05", "not run", "the patch lineage does not resolve")
	} else {
		state, detail = checkP05(record, patch, ancestors, artifacts)
		add("P-05", state, detail)
	}

	byID := map[string]string{}
	for _, check := range results {
		byID[check.ID] = check.Result
	}
	qualifiers := []string{}
	if byID["P-02"] == "pass" {
		qualifiers = append(qualifiers, "patch-executable")
		if byID["P-03"] == "pass" {
			qualifiers = append(qualifiers, "stackable")
		}
		if exactInverseProblem(patch) == "" && byID["P-05"] != "fail" {
			qualifiers = append(qualifiers, "reversible")
		}
	}

	failed := []string{}
	notRun := []string{}
	for _, check := range results {
		if check.Result == "fail" {
			failed = append(failed, check.ID)
		} else if check.Result == "not run" {
			notRun = append(notRun, check.ID)
		}
	}
	identifier := ""
	if digest, ok := patchID(patch); ok {
		identifier = "wpp:sha256:" + digest
	}
	return &patchBlock{
		ID:         identifier,
		Checks:     results,
		Qualifiers: qualifiers,
		Failed:     failed,
		NotRun:     notRun,
	}
}
