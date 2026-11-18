package main

import "unicode"

// Printability, pinned to the reference Unicode version.
//
// repr() escapes every rune that is not printable by Unicode category, and
// unicode.IsPrint applies exactly that rule — but to Go's Unicode table, which is
// newer than the one validate.py runs on. Go 1.27 ships Unicode 17.0.0; Python
// 3.14 ships 16.0.0. The runes below are assigned in 17.0.0 and unassigned in
// 16.0.0, so Go prints them literally where Python escapes them. Report details
// quote the falsifier's output and the host's etag, so the difference would show
// up as a disagreement between the two implementations.
//
// This is a version pin, not a correction. TestPrintabilityPinsAreExactlyTheDrift
// derives the table from testdata/repr_vectors.json and Go's own table, and fails
// if either moves; regenerate with testdata/make_repr.py after a Python upgrade.
var referenceUnprintable = [][2]rune{
	{0x088F, 0x088F},
	{0x0C5C, 0x0C5C},
	{0x0CDC, 0x0CDC},
	{0x1ACF, 0x1ADD},
	{0x1AE0, 0x1AEB},
	{0x20C1, 0x20C1},
	{0x2B96, 0x2B96},
	{0xA7CE, 0xA7CF},
	{0xA7D2, 0xA7D2},
	{0xA7D4, 0xA7D4},
	{0xA7F1, 0xA7F1},
	{0xFBC3, 0xFBD2},
	{0xFD90, 0xFD91},
	{0xFDC8, 0xFDCE},
	{0x10940, 0x10959},
	{0x10EC5, 0x10EC7},
	{0x10ED0, 0x10ED8},
	{0x10EFA, 0x10EFB},
	{0x11B60, 0x11B67},
	{0x11DB0, 0x11DDB},
	{0x11DE0, 0x11DE9},
	{0x16EA0, 0x16EB8},
	{0x16EBB, 0x16ED3},
	{0x16FF2, 0x16FF6},
	{0x187F8, 0x187FF},
	{0x18D09, 0x18D1E},
	{0x18D80, 0x18DF2},
	{0x1CCFA, 0x1CCFC},
	{0x1CEBA, 0x1CED0},
	{0x1CEE0, 0x1CEF0},
	{0x1E6C0, 0x1E6DE},
	{0x1E6E0, 0x1E6F5},
	{0x1E6FE, 0x1E6FF},
	{0x1F6D8, 0x1F6D8},
	{0x1F777, 0x1F77A},
	{0x1F8D0, 0x1F8D8},
	{0x1FA54, 0x1FA57},
	{0x1FA8A, 0x1FA8A},
	{0x1FA8E, 0x1FA8E},
	{0x1FAC8, 0x1FAC8},
	{0x1FACD, 0x1FACD},
	{0x1FAEA, 0x1FAEA},
	{0x1FAEF, 0x1FAEF},
	{0x1FBFA, 0x1FBFA},
	{0x2B73A, 0x2B73F},
	{0x2CEA2, 0x2CEAD},
	{0x323B0, 0x33479},
}

// referencePrintable reports whether repr() would print the rune literally.
// The spans are sorted and disjoint, so the scan stops at the first one past it.
func referencePrintable(symbol rune) bool {
	for _, span := range referenceUnprintable {
		if symbol < span[0] {
			break
		}
		if symbol <= span[1] {
			return false
		}
	}
	return unicode.IsPrint(symbol)
}
