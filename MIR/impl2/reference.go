package main

import (
	"sort"
	"strings"
)

// Text handling pinned to the reference implementation.
//
// Go's strings package is not Python's str methods, and the differences reach
// reports: C-04 quotes the falsifier's lowercased output, C-07 quotes the host's
// lowercased etag, and C-10 trims operators and funding sources before comparing
// them. Three gaps were measured across the whole code point space:
//
//   - strings.TrimSpace misses U+001C..U+001F, which str.strip() removes.
//   - strings.ToLower ignores SpecialCasing, so U+0130 became "i" instead of
//     "i̇", and it ignores Final_Sigma, so "ΟΔΟΣ" became "οδοσ" instead of "οδος".
//   - Go ships a newer Unicode table than validate.py runs on, so it folds case
//     pairs Python does not know about.
//
// The tables in unicode_tables.go are generated from Python, so none of this
// depends on Go's Unicode version. reference_test.go checks every code point.

func inSpans(spans [][2]rune, symbol rune) bool {
	index := sort.Search(len(spans), func(i int) bool { return spans[i][1] >= symbol })
	return index < len(spans) && symbol >= spans[index][0]
}

// referenceSpace is str.isspace().
func referenceSpace(symbol rune) bool {
	index := sort.Search(len(referenceWhitespace), func(i int) bool {
		return referenceWhitespace[i] >= symbol
	})
	return index < len(referenceWhitespace) && referenceWhitespace[index] == symbol
}

// referenceTrimSpace is str.strip().
func referenceTrimSpace(text string) string {
	return strings.TrimFunc(text, referenceSpace)
}

func referenceCased(symbol rune) bool {
	return inSpans(referenceCasedSpans, symbol)
}

func referenceCaseIgnorable(symbol rune) bool {
	return inSpans(referenceCaseIgnorableSpans, symbol)
}

func referenceLowerRune(symbol rune) string {
	if expanded, ok := referenceLowerExpansions[symbol]; ok {
		return expanded
	}
	index := sort.Search(len(referenceLowerSpans), func(i int) bool {
		return referenceLowerSpans[i].hi >= symbol
	})
	if index < len(referenceLowerSpans) {
		span := referenceLowerSpans[index]
		if symbol >= span.lo {
			return string(symbol + span.delta)
		}
	}
	return string(symbol)
}

// finalSigma decides whether a capital sigma is at the end of a word: preceded by
// a cased rune and not followed by one, ignoring case-ignorable runes on both
// sides. This is the only context-sensitive rule in str.lower().
func finalSigma(runes []rune, at int) bool {
	before := at - 1
	for before >= 0 && referenceCaseIgnorable(runes[before]) {
		before--
	}
	if before < 0 || !referenceCased(runes[before]) {
		return false
	}
	for after := at + 1; after < len(runes); after++ {
		if referenceCased(runes[after]) {
			return false
		}
		if !referenceCaseIgnorable(runes[after]) {
			break
		}
	}
	return true
}

// referenceLower is str.lower().
func referenceLower(text string) string {
	runes := []rune(text)
	var builder strings.Builder
	for at, symbol := range runes {
		if symbol == 0x03A3 && finalSigma(runes, at) {
			builder.WriteRune(0x03C2)
			continue
		}
		builder.WriteString(referenceLowerRune(symbol))
	}
	return builder.String()
}
