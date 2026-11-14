package main

import (
	"strings"
	"unicode"
)

// Unicode full case folding, without a dependency.
//
// validate.py decides funding independence with str.casefold(). A full fold is a
// simple fold except for the runes in fullFoldExpansions, whose folding expands
// to several runes. Expanding those and then folding each resulting rune
// reproduces str.casefold(), so the two implementations decide independence
// identically. strings.EqualFold alone does simple folding and treated "strasse"
// and "straße" as different funding sources.
//
// Both tables are data, not a library, and both are written as escapes on
// purpose. Several expansions are decomposed sequences that look identical to a
// precomposed rune in an editor; a precomposed rune would fold to itself and
// silently restore the divergence. Three entries were in fact wrong that way
// before casefold_test.go walked the whole code point space.
//
// Regenerate expectations with testdata/make_casefold.py after a Python upgrade.

var fullFoldExpansions = map[rune]string{
	0x00DF: "\u0073\u0073",
	0x0130: "\u0069\u0307",
	0x0149: "\u02bc\u006e",
	0x01F0: "\u006a\u030c",
	0x0390: "\u03b9\u0308\u0301",
	0x03B0: "\u03c5\u0308\u0301",
	0x0587: "\u0565\u0582",
	0x1E96: "\u0068\u0331",
	0x1E97: "\u0074\u0308",
	0x1E98: "\u0077\u030a",
	0x1E99: "\u0079\u030a",
	0x1E9A: "\u0061\u02be",
	0x1E9E: "\u0073\u0073",
	0x1F50: "\u03c5\u0313",
	0x1F52: "\u03c5\u0313\u0300",
	0x1F54: "\u03c5\u0313\u0301",
	0x1F56: "\u03c5\u0313\u0342",
	0x1F80: "\u1f00\u03b9",
	0x1F81: "\u1f01\u03b9",
	0x1F82: "\u1f02\u03b9",
	0x1F83: "\u1f03\u03b9",
	0x1F84: "\u1f04\u03b9",
	0x1F85: "\u1f05\u03b9",
	0x1F86: "\u1f06\u03b9",
	0x1F87: "\u1f07\u03b9",
	0x1F88: "\u1f00\u03b9",
	0x1F89: "\u1f01\u03b9",
	0x1F8A: "\u1f02\u03b9",
	0x1F8B: "\u1f03\u03b9",
	0x1F8C: "\u1f04\u03b9",
	0x1F8D: "\u1f05\u03b9",
	0x1F8E: "\u1f06\u03b9",
	0x1F8F: "\u1f07\u03b9",
	0x1F90: "\u1f20\u03b9",
	0x1F91: "\u1f21\u03b9",
	0x1F92: "\u1f22\u03b9",
	0x1F93: "\u1f23\u03b9",
	0x1F94: "\u1f24\u03b9",
	0x1F95: "\u1f25\u03b9",
	0x1F96: "\u1f26\u03b9",
	0x1F97: "\u1f27\u03b9",
	0x1F98: "\u1f20\u03b9",
	0x1F99: "\u1f21\u03b9",
	0x1F9A: "\u1f22\u03b9",
	0x1F9B: "\u1f23\u03b9",
	0x1F9C: "\u1f24\u03b9",
	0x1F9D: "\u1f25\u03b9",
	0x1F9E: "\u1f26\u03b9",
	0x1F9F: "\u1f27\u03b9",
	0x1FA0: "\u1f60\u03b9",
	0x1FA1: "\u1f61\u03b9",
	0x1FA2: "\u1f62\u03b9",
	0x1FA3: "\u1f63\u03b9",
	0x1FA4: "\u1f64\u03b9",
	0x1FA5: "\u1f65\u03b9",
	0x1FA6: "\u1f66\u03b9",
	0x1FA7: "\u1f67\u03b9",
	0x1FA8: "\u1f60\u03b9",
	0x1FA9: "\u1f61\u03b9",
	0x1FAA: "\u1f62\u03b9",
	0x1FAB: "\u1f63\u03b9",
	0x1FAC: "\u1f64\u03b9",
	0x1FAD: "\u1f65\u03b9",
	0x1FAE: "\u1f66\u03b9",
	0x1FAF: "\u1f67\u03b9",
	0x1FB2: "\u1f70\u03b9",
	0x1FB3: "\u03b1\u03b9",
	0x1FB4: "\u03ac\u03b9",
	0x1FB6: "\u03b1\u0342",
	0x1FB7: "\u03b1\u0342\u03b9",
	0x1FBC: "\u03b1\u03b9",
	0x1FC2: "\u1f74\u03b9",
	0x1FC3: "\u03b7\u03b9",
	0x1FC4: "\u03ae\u03b9",
	0x1FC6: "\u03b7\u0342",
	0x1FC7: "\u03b7\u0342\u03b9",
	0x1FCC: "\u03b7\u03b9",
	0x1FD2: "\u03b9\u0308\u0300",
	0x1FD3: "\u03b9\u0308\u0301",
	0x1FD6: "\u03b9\u0342",
	0x1FD7: "\u03b9\u0308\u0342",
	0x1FE2: "\u03c5\u0308\u0300",
	0x1FE3: "\u03c5\u0308\u0301",
	0x1FE4: "\u03c1\u0313",
	0x1FE6: "\u03c5\u0342",
	0x1FE7: "\u03c5\u0308\u0342",
	0x1FF2: "\u1f7c\u03b9",
	0x1FF3: "\u03c9\u03b9",
	0x1FF4: "\u03ce\u03b9",
	0x1FF6: "\u03c9\u0342",
	0x1FF7: "\u03c9\u0342\u03b9",
	0x1FFC: "\u03c9\u03b9",
	0xFB00: "\u0066\u0066",
	0xFB01: "\u0066\u0069",
	0xFB02: "\u0066\u006c",
	0xFB03: "\u0066\u0066\u0069",
	0xFB04: "\u0066\u0066\u006c",
	0xFB05: "\u0073\u0074",
	0xFB06: "\u0073\u0074",
	0xFB13: "\u0574\u0576",
	0xFB14: "\u0574\u0565",
	0xFB15: "\u0574\u056b",
	0xFB16: "\u057e\u0576",
	0xFB17: "\u0574\u056d",
}

// pinnedUnfolded holds the case pairs Go folds but the reference Unicode version
// does not. Go 1.27 ships Unicode 17.0.0; validate.py runs on Python 3.14, which
// ships 16.0.0. Every rune below is unassigned in 16.0.0 except the two lowercase
// letters whose uppercase partners are, so Python folds each of them to itself
// while unicode.SimpleFold merges the pair. Left alone, the two implementations
// would disagree about independence for a funding source containing any of them.
//
// Pinning them to themselves makes impl2 fold exactly the repertoire validate.py
// folds. This is a version pin, not a correction: when Python catches up, the
// exhaustive tests fail and the table must be regenerated, not extended.
var pinnedUnfolded = map[rune]bool{
	0xA7CE: true, 0xA7CF: true,
	0xA7D2: true, 0xA7D3: true,
	0xA7D4: true, 0xA7D5: true,
	0x16EA0: true, 0x16EBB: true,
	0x16EA1: true, 0x16EBC: true,
	0x16EA2: true, 0x16EBD: true,
	0x16EA3: true, 0x16EBE: true,
	0x16EA4: true, 0x16EBF: true,
	0x16EA5: true, 0x16EC0: true,
	0x16EA6: true, 0x16EC1: true,
	0x16EA7: true, 0x16EC2: true,
	0x16EA8: true, 0x16EC3: true,
	0x16EA9: true, 0x16EC4: true,
	0x16EAA: true, 0x16EC5: true,
	0x16EAB: true, 0x16EC6: true,
	0x16EAC: true, 0x16EC7: true,
	0x16EAD: true, 0x16EC8: true,
	0x16EAE: true, 0x16EC9: true,
	0x16EAF: true, 0x16ECA: true,
	0x16EB0: true, 0x16ECB: true,
	0x16EB1: true, 0x16ECC: true,
	0x16EB2: true, 0x16ECD: true,
	0x16EB3: true, 0x16ECE: true,
	0x16EB4: true, 0x16ECF: true,
	0x16EB5: true, 0x16ED0: true,
	0x16EB6: true, 0x16ED1: true,
	0x16EB7: true, 0x16ED2: true,
	0x16EB8: true, 0x16ED3: true,
}

func fullCaseFold(text string) string {
	var builder strings.Builder
	for _, symbol := range text {
		if expanded, ok := fullFoldExpansions[symbol]; ok {
			builder.WriteString(expanded)
		} else {
			builder.WriteRune(symbol)
		}
	}
	return builder.String()
}

// simpleFoldKey is the lowest rune in a simple-folding orbit, which is what
// strings.EqualFold compares, except for the pinned pairs.
func simpleFoldKey(symbol rune) rune {
	if pinnedUnfolded[symbol] {
		return symbol
	}
	lowest := symbol
	for next := unicode.SimpleFold(symbol); next != symbol; next = unicode.SimpleFold(next) {
		if next < lowest {
			lowest = next
		}
	}
	return lowest
}

func foldKey(text string) string {
	var builder strings.Builder
	for _, symbol := range fullCaseFold(text) {
		builder.WriteRune(simpleFoldKey(symbol))
	}
	return builder.String()
}

// foldEqual reports whether two names name the same entity under Unicode full
// case folding. MIR-1-05 compares both operators and funding sources this way:
// a name that differs only in case is the same name. Callers trim surrounding
// whitespace.
func foldEqual(left, right string) bool {
	return foldKey(left) == foldKey(right)
}
