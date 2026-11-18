package main

// The schema is the published contract, and the validator now runs it. That
// leaves one way for the two to drift: a schema that uses a keyword the walker
// does not implement would be silently ignored. This test reads the schema,
// collects the keywords it uses, and fails if any of them is not implemented.

import (
	"encoding/json"
	"os"
	"sort"
	"testing"
)

func schemaKeywordsUsed(node any, found map[string]bool) map[string]bool {
	object, ok := node.(map[string]any)
	if !ok {
		return found
	}
	for key, value := range object {
		found[key] = true
		switch key {
		case "properties", "definitions":
			if children, ok := value.(map[string]any); ok {
				for _, child := range children {
					schemaKeywordsUsed(child, found)
				}
			}
		case "items":
			schemaKeywordsUsed(value, found)
		case "oneOf", "allOf", "anyOf":
			if children, ok := value.([]any); ok {
				for _, child := range children {
					schemaKeywordsUsed(child, found)
				}
			}
		}
	}
	return found
}

func TestSchemaKeywords(t *testing.T) {
	data, err := os.ReadFile("../schema.json")
	if err != nil {
		t.Fatalf("read schema: %v", err)
	}
	var schema any
	if err := json.Unmarshal(data, &schema); err != nil {
		t.Fatalf("parse schema: %v", err)
	}
	used := schemaKeywordsUsed(schema, map[string]bool{})
	unsupported := []string{}
	for keyword := range used {
		if schemaMetadata[keyword] {
			continue
		}
		if !schemaKeywords[keyword] {
			unsupported = append(unsupported, keyword)
		}
	}
	if len(unsupported) > 0 {
		sort.Strings(unsupported)
		t.Fatalf("the schema uses keywords this walker ignores: %v", unsupported)
	}
}
