package main

// Schema conformance, driven by schema.json.
//
// The validator used to restate the schema in code. That is a second copy of
// the rules, and the two copies drifted: `claimant` was required by the schema
// and missing from both implementations' field lists, so a record without it
// passed. This file reads the published schema and checks the record against
// it, so there is one place for the shape to be wrong.
//
// Only the keywords this schema uses are implemented. A schema that grows a
// keyword outside the list below is a schema this suite cannot check, and the
// differential test is what notices.

import (
	"bytes"
	"encoding/json"
	"fmt"
	"math"
	"os"
	"path/filepath"
	"reflect"
	"regexp"
	"sort"
	"strings"
	"unicode/utf8"
)

var activeSchema map[string]any

// The keywords the walker implements. Kept in step with validate.py by the
// tests, which compare both lists with the schema itself.
var schemaKeywords = map[string]bool{
	"$ref": true, "oneOf": true, "type": true, "const": true, "enum": true,
	"minLength": true, "pattern": true, "minimum": true,
	"exclusiveMinimum": true, "minItems": true,
	"uniqueItems": true, "items": true, "required": true, "properties": true,
	"additionalProperties": true,
}

var schemaMetadata = map[string]bool{
	"$schema": true, "$id": true, "title": true, "description": true,
	"definitions": true,
}

func schemaCandidates(explicit string) []string {
	candidates := []string{}
	if explicit != "" {
		candidates = append(candidates, explicit)
	}
	if fromEnv := os.Getenv("MIR_SCHEMA"); fromEnv != "" {
		candidates = append(candidates, fromEnv)
	}
	if executable, err := os.Executable(); err == nil {
		candidates = append(candidates, filepath.Join(filepath.Dir(executable), "..", "schema.json"))
	}
	if cwd, err := os.Getwd(); err == nil {
		candidates = append(candidates, filepath.Join(cwd, "schema.json"),
			filepath.Join(cwd, "..", "schema.json"))
	}
	return candidates
}

func loadSchema(explicit string) (map[string]any, string) {
	for _, candidate := range schemaCandidates(explicit) {
		if !isFile(candidate) {
			continue
		}
		raw, err := os.ReadFile(candidate)
		if err != nil {
			continue
		}
		document, err := decodeJSON(raw)
		if err != nil {
			return nil, fmt.Sprintf("cannot parse %s: %v", candidate, err)
		}
		object, ok := objectValue(document)
		if !ok {
			return nil, fmt.Sprintf("%s is not an object", candidate)
		}
		converted := make(map[string]any, len(object.keys))
		for _, key := range object.keys {
			value, _ := object.get(key)
			converted[key] = value
		}
		return converted, ""
	}
	return nil, "no schema.json found; pass --schema"
}

func showValue(value any) string {
	buffer := &bytes.Buffer{}
	encoder := json.NewEncoder(buffer)
	encoder.SetEscapeHTML(false)
	if err := encoder.Encode(value); err != nil {
		return fmt.Sprintf("%v", value)
	}
	return strings.TrimRight(buffer.String(), "\n")
}

// integralFloat mirrors float.is_integer() in validate.py, which is false for
// infinity and NaN rather than true.
func integralFloat(value float64) bool {
	return !math.IsInf(value, 0) && !math.IsNaN(value) && math.Trunc(value) == value
}

func actualType(value any) string {
	switch typed := value.(type) {
	case nil:
		return "null"
	case bool:
		return "boolean"
	case string:
		return "string"
	case []any:
		return "array"
	case map[string]any:
		return "object"
	case *jobject:
		return "object"
	case json.Number:
		// An integer literal is an integer at any magnitude. Converting through
		// float64/int64 overflowed above 2^63 and disagreed with validate.py.
		literal := typed.String()
		if !strings.ContainsAny(literal, ".eE") {
			return "integer"
		}
		if value, err := typed.Float64(); err == nil && integralFloat(value) {
			return "integer"
		}
		return "number"
	case float64:
		if integralFloat(typed) {
			return "integer"
		}
		return "number"
	case int64:
		return "integer"
	}
	return "unknown"
}

func typeName(wanted any) string {
	switch typed := wanted.(type) {
	case string:
		return typed
	case []any:
		names := make([]string, 0, len(typed))
		for _, item := range typed {
			names = append(names, fmt.Sprint(item))
		}
		return strings.Join(names, " or ")
	}
	return fmt.Sprint(wanted)
}

func typeMatches(value any, wanted any) bool {
	actual := actualType(value)
	switch typed := wanted.(type) {
	case string:
		if typed == "number" {
			return actual == "number" || actual == "integer"
		}
		return actual == typed
	case []any:
		for _, item := range typed {
			if typeMatches(value, item) {
				return true
			}
		}
		return false
	}
	return false
}

func resolveRef(ref string, root map[string]any) (any, bool) {
	node := any(root)
	for _, part := range strings.Split(strings.TrimPrefix(ref, "#/"), "/") {
		object, ok := objectValue(node)
		if !ok {
			if mapped, isMap := node.(map[string]any); isMap {
				value, present := mapped[part]
				if !present {
					return nil, false
				}
				node = value
				continue
			}
			return nil, false
		}
		value, present := object.get(part)
		if !present {
			return nil, false
		}
		node = value
	}
	return node, true
}

func joinPath(path string, key any) string {
	prefix := path
	if prefix == "/" {
		prefix = ""
	}
	return fmt.Sprintf("%s/%v", prefix, key)
}

func sameJSON(left, right any) bool {
	return reflect.DeepEqual(left, right) || showValue(left) == showValue(right)
}

func asObjectMap(value any) (map[string]any, bool) {
	switch typed := value.(type) {
	case map[string]any:
		return typed, true
	case *jobject:
		converted := make(map[string]any, len(typed.keys))
		for _, key := range typed.keys {
			item, _ := typed.get(key)
			converted[key] = item
		}
		return converted, true
	}
	return nil, false
}

func asSlice(value any) ([]any, bool) {
	items, ok := value.([]any)
	return items, ok
}

func schemaProblem(value any, schema any, root map[string]any, path string) string {
	node, ok := asObjectMap(schema)
	if !ok {
		return ""
	}
	if ref, ok := node["$ref"].(string); ok {
		target, resolved := resolveRef(ref, root)
		if !resolved {
			return fmt.Sprintf("%s: unresolvable reference %s", path, ref)
		}
		return schemaProblem(value, target, root, path)
	}
	if alternatives, ok := asSlice(node["oneOf"]); ok {
		matches := 0
		for _, alternative := range alternatives {
			if schemaProblem(value, alternative, root, path) == "" {
				matches++
			}
		}
		if matches != 1 {
			return fmt.Sprintf("%s: matches %d of %d alternatives", path, matches, len(alternatives))
		}
	}
	if wanted, ok := node["type"]; ok {
		if !typeMatches(value, wanted) {
			return fmt.Sprintf("%s: expected %s, got %s", path, typeName(wanted), actualType(value))
		}
	}
	if declared, ok := node["const"]; ok {
		if !sameJSON(value, declared) {
			return fmt.Sprintf("%s: expected %s, got %s", path, showValue(declared), showValue(value))
		}
	}
	if allowed, ok := asSlice(node["enum"]); ok {
		found := false
		shown := make([]string, 0, len(allowed))
		for _, item := range allowed {
			shown = append(shown, showValue(item))
			if sameJSON(value, item) {
				found = true
			}
		}
		if !found {
			return fmt.Sprintf("%s: %s is not one of %s", path, showValue(value), strings.Join(shown, ", "))
		}
	}
	if text, ok := value.(string); ok {
		if minimum, ok := numericValue(node["minLength"]); ok && utf8.RuneCountInString(text) < int(minimum) {
			return fmt.Sprintf("%s: shorter than %d character(s)", path, int(minimum))
		}
		if pattern, ok := node["pattern"].(string); ok {
			compiled, err := regexp.Compile(pattern)
			if err != nil || !compiled.MatchString(text) {
				return fmt.Sprintf("%s: does not match the pattern", path)
			}
		}
	}
	if number, ok := numericValue(value); ok {
		if minimum, ok := numericValue(node["minimum"]); ok && number < minimum {
			return fmt.Sprintf("%s: less than %s", path, showValue(minimum))
		}
		if minimum, ok := numericValue(node["exclusiveMinimum"]); ok && number <= minimum {
			return fmt.Sprintf("%s: not greater than %s", path, showValue(minimum))
		}
	}
	if items, ok := asSlice(value); ok {
		if minimum, ok := numericValue(node["minItems"]); ok && len(items) < int(minimum) {
			return fmt.Sprintf("%s: fewer than %d item(s)", path, int(minimum))
		}
		if unique, ok := node["uniqueItems"].(bool); ok && unique {
			seen := make([]string, 0, len(items))
			for _, item := range items {
				shown := showValue(item)
				for _, previous := range seen {
					if previous == shown {
						return fmt.Sprintf("%s: duplicate item %s", path, shown)
					}
				}
				seen = append(seen, shown)
			}
		}
		if itemSchema, ok := node["items"]; ok {
			for index, item := range items {
				if problem := schemaProblem(item, itemSchema, root, joinPath(path, index)); problem != "" {
					return problem
				}
			}
		}
	}
	if object, ok := asObjectMap(value); ok {
		if required, ok := asSlice(node["required"]); ok {
			for _, name := range required {
				key, isString := name.(string)
				if !isString {
					continue
				}
				if _, present := object[key]; !present {
					return fmt.Sprintf("%s: missing required field %s", path, showValue(key))
				}
			}
		}
		declared, hasProperties := asObjectMap(node["properties"])
		if additional, ok := node["additionalProperties"].(bool); ok && !additional && hasProperties {
			keys := make([]string, 0, len(object))
			for key := range object {
				keys = append(keys, key)
			}
			sort.Strings(keys)
			for _, key := range keys {
				if _, known := declared[key]; !known {
					return fmt.Sprintf("%s: unexpected field %s", path, showValue(key))
				}
			}
		}
		if hasProperties {
			keys := make([]string, 0, len(declared))
			for key := range declared {
				keys = append(keys, key)
			}
			sort.Strings(keys)
			for _, key := range keys {
				if item, present := object[key]; present {
					if problem := schemaProblem(item, declared[key], root, joinPath(path, key)); problem != "" {
						return problem
					}
				}
			}
		}
	}
	return ""
}
