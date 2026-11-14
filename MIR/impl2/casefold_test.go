package main

// The fold tables in casefold.go are transcribed data, and transcribed data
// drifts. Several expansions are decomposed sequences that look identical to a
// precomposed rune in an editor; substituting one would fold to itself and
// silently restore the "strasse" vs "straße" divergence. Three entries were wrong
// that way until these tests walked the whole code point space.
//
// The guarantee is that impl2's folding induces exactly the partition Python's
// str.casefold() induces, which is what validate.py uses. Both folds are
// per-rune concatenations, so proving it for every code point proves it for
// every string. Expectations come from testdata/casefold_vectors.json, generated
// by testdata/make_casefold.py; regenerate it after a Python upgrade.

import (
	"encoding/json"
	"os"
	"strconv"
	"strings"
	"testing"
	"unicode"
)

type casefoldVectors struct {
	UnicodeVersion string            `json:"unicode_version"`
	Folds          map[string]string `json:"folds"`
}

func loadCasefoldVectors(t *testing.T) map[rune]string {
	t.Helper()
	data, err := os.ReadFile("testdata/casefold_vectors.json")
	if err != nil {
		t.Fatalf("read casefold vectors: %v", err)
	}
	var vectors casefoldVectors
	if err := json.Unmarshal(data, &vectors); err != nil {
		t.Fatalf("parse casefold vectors: %v", err)
	}
	folds := map[rune]string{}
	for point, spaced := range vectors.Folds {
		value, err := strconv.ParseUint(point, 16, 32)
		if err != nil {
			t.Fatalf("bad code point %q: %v", point, err)
		}
		var builder strings.Builder
		for _, field := range strings.Fields(spaced) {
			unit, err := strconv.ParseUint(field, 16, 32)
			if err != nil {
				t.Fatalf("bad folded code point %q: %v", field, err)
			}
			builder.WriteRune(rune(unit))
		}
		folds[rune(value)] = builder.String()
	}
	if len(folds) == 0 {
		t.Fatal("casefold vectors are empty")
	}
	return folds
}

// pythonFold is str.casefold() for a single rune. Runes absent from the vectors
// fold to themselves.
func pythonFold(folds map[rune]string, symbol rune) string {
	if folded, ok := folds[symbol]; ok {
		return folded
	}
	return string(symbol)
}

// orbitMin is the test's own reading of Go's simple-folding table. It is kept
// separate from simpleFoldKey so that a mistake in the pin table cannot hide
// inside the expectation.
func orbitMin(symbol rune) rune {
	lowest := symbol
	for next := unicode.SimpleFold(symbol); next != symbol; next = unicode.SimpleFold(next) {
		if next < lowest {
			lowest = next
		}
	}
	return lowest
}

func eachRune(visit func(rune)) {
	for point := rune(0); point <= unicode.MaxRune; point++ {
		if point >= 0xD800 && point <= 0xDFFF {
			continue
		}
		visit(point)
	}
}

// TestFoldTableCoversExactlyTheExpandingRunes pins the expansion table's key set.
// A missing key restores a divergence; an extra key folds a rune Python leaves
// alone.
func TestFoldTableCoversExactlyTheExpandingRunes(t *testing.T) {
	folds := loadCasefoldVectors(t)
	expanding := map[rune]bool{}
	eachRune(func(point rune) {
		if len([]rune(pythonFold(folds, point))) > 1 {
			expanding[point] = true
		}
	})
	for point := range fullFoldExpansions {
		if !expanding[point] {
			t.Errorf("U+%04X is in the table but Python does not expand it", point)
		}
	}
	for point := range expanding {
		if _, ok := fullFoldExpansions[point]; !ok {
			t.Errorf("U+%04X expands to %q in Python but is missing from the table",
				point, pythonFold(folds, point))
		}
	}
}

// TestFullFoldMatchesPythonEverywhere checks the expansion table rune for rune.
// Comparing up to simple folding is deliberate: the table is responsible only for
// the expansion, and the folding of the resulting runes is checked separately.
func TestFullFoldMatchesPythonEverywhere(t *testing.T) {
	folds := loadCasefoldVectors(t)
	eachRune(func(point rune) {
		expected := []rune(pythonFold(folds, point))
		actual := []rune(fullCaseFold(string(point)))
		if len(actual) != len(expected) {
			t.Fatalf("U+%04X: impl2 expands to %q, Python folds to %q", point, actual, expected)
		}
		for i, symbol := range actual {
			if orbitMin(symbol) != orbitMin(expected[i]) {
				t.Fatalf("U+%04X: impl2 expands to %q, Python folds to %q", point, actual, expected)
			}
		}
	})
}

// TestFoldKeyAgreesWithPythonEverywhere is the merging direction: whatever Python
// folds a rune to must land on the same key as the rune itself.
func TestFoldKeyAgreesWithPythonEverywhere(t *testing.T) {
	folds := loadCasefoldVectors(t)
	eachRune(func(point rune) {
		expected := pythonFold(folds, point)
		if foldKey(string(point)) != foldKey(expected) {
			t.Fatalf("U+%04X: key %q, but its Python fold %q has key %q",
				point, foldKey(string(point)), expected, foldKey(expected))
		}
	})
}

// TestFoldingDoesNotOverMerge is the splitting direction, which the test above
// cannot see: it compares each rune against its own fold, so two runes Go merges
// but Python keeps apart both look self-consistent. Every pair Go actually
// merges must therefore be equal under Python too.
//
// Only runes in a non-trivial orbit need visiting. A rune whose orbit is trivial
// and which is not pinned keys to itself, and no other rune can key to it without
// sharing its orbit. Expansion runes are excluded because Go compares their
// multi-rune expansions, which no single rune can match;
// TestExpandingRunesPairwise covers those.
func TestFoldingDoesNotOverMerge(t *testing.T) {
	folds := loadCasefoldVectors(t)
	eachRune(func(point rune) {
		if _, expanded := fullFoldExpansions[point]; expanded {
			return
		}
		if orbitMin(point) == point {
			return
		}
		expected := pythonFold(folds, point)
		for next := unicode.SimpleFold(point); next != point; next = unicode.SimpleFold(next) {
			if _, expanded := fullFoldExpansions[next]; expanded {
				continue
			}
			if foldKey(string(point)) != foldKey(string(next)) {
				continue
			}
			if other := pythonFold(folds, next); other != expected {
				t.Fatalf("impl2 merges U+%04X and U+%04X, but Python folds them to %q and %q",
					point, next, expected, other)
			}
		}
	})
}

// TestPinnedRunesAreNotFoldedByPython keeps the pin from breaking a fold that is
// supposed to happen: every pinned rune must be one Python folds to itself. A
// missing pin is caught by TestFoldingDoesNotOverMerge, which fails on any pair
// impl2 merges and Python does not.
func TestPinnedRunesAreNotFoldedByPython(t *testing.T) {
	folds := loadCasefoldVectors(t)
	for point := range pinnedUnfolded {
		if pythonFold(folds, point) != string(point) {
			t.Errorf("U+%04X is pinned but Python folds it to %q", point, pythonFold(folds, point))
		}
	}
}

func TestExpandingRunesPairwise(t *testing.T) {
	folds := loadCasefoldVectors(t)
	points := make([]rune, 0, len(fullFoldExpansions))
	for point := range fullFoldExpansions {
		points = append(points, point)
	}
	for _, left := range points {
		for _, right := range points {
			want := pythonFold(folds, left) == pythonFold(folds, right)
			if got := foldEqual(string(left), string(right)); got != want {
				t.Fatalf("U+%04X vs U+%04X: impl2 says %v, Python says %v", left, right, got, want)
			}
		}
	}
}

func TestFundingEqualOnEveryFoldedRune(t *testing.T) {
	folds := loadCasefoldVectors(t)
	for point, expected := range folds {
		if !foldEqual(string(point), expected) {
			t.Fatalf("U+%04X should equal its fold %q", point, expected)
		}
	}
}

// TestFundingEqualProbes does not read the vectors, so it still means something if
// the vectors are ever regenerated from a broken authority. Trimming is the
// caller's job, so these probes are already trimmed.
func TestFundingEqualProbes(t *testing.T) {
	equal := [][2]string{
		{"strasse", "straße"},
		{"STRASSE", "straße"},
		{"Straße", "STRASSE"},
		{"ACME", "acme"},
		{"office", "oﬃce"},
		{"ﬀ", "ff"},
		{"İ", "i̇"},
		{"ǰ", "ǰ"},
		{"ẞ", "ss"},
		{"ẗ", "ẗ"},
		{"ﬅ", "st"},
		{"ﬆ", "st"},
		{"մն", "ՄՆ"},
		{"ACME Stiftung", "acme stiftung"},
	}
	for _, pair := range equal {
		if !foldEqual(pair[0], pair[1]) {
			t.Errorf("%q and %q should be the same funding source", pair[0], pair[1])
		}
	}
	different := [][2]string{
		{"acme", "acme corp"},
		{"acme", "acmé"},
		{"istanbul", "İstanbul"},
		{"ss", "s"},
		{"", "acme"},
		{"꟎", "꟏"},
	}
	for _, pair := range different {
		if foldEqual(pair[0], pair[1]) {
			t.Errorf("%q and %q should be different funding sources", pair[0], pair[1])
		}
	}
}
