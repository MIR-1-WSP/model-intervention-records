package main

// Message formatting. The details in a report are read by people comparing two
// implementations, so this file reproduces the reference implementation's
// Python repr rather than Go's quoting. A difference here would look like a
// disagreement about the record.

import (
	"encoding/json"
	"fmt"
	"math"
	"math/big"
	"strconv"
	"strings"
)

func pyRepr(value any) string {
	if text, ok := value.(string); ok {
		return pyStringRepr(text)
	}
	return pyStr(value)
}

// pyStr reproduces str(). For every JSON type except str, repr and str produce
// the same text, so the two share everything below the string case. Objects are
// walked in document order, which is the order Python's dict preserves.
func pyStr(value any) string {
	switch typed := value.(type) {
	case nil:
		return "None"
	case bool:
		if typed {
			return "True"
		}
		return "False"
	case string:
		return typed
	case json.Number:
		return pyNumberStr(typed)
	case []any:
		parts := make([]string, len(typed))
		for i, item := range typed {
			parts[i] = pyRepr(item)
		}
		return "[" + strings.Join(parts, ", ") + "]"
	case *jobject:
		parts := make([]string, 0, len(typed.keys))
		for _, key := range typed.keys {
			parts = append(parts, pyStringRepr(key)+": "+pyRepr(typed.vals[key]))
		}
		return "{" + strings.Join(parts, ", ") + "}"
	default:
		return fmt.Sprintf("%v", typed)
	}
}

func pyNumberStr(number json.Number) string {
	literal := string(number)
	if !strings.ContainsAny(literal, ".eE") {
		value, _ := new(big.Int).SetString(literal, 10)
		return value.String()
	}
	// The decoder has already validated the literal. ParseFloat yields an
	// infinity beyond the float range and a signed zero below it, which is what
	// Python's json module produces for the same spellings.
	value, _ := strconv.ParseFloat(literal, 64)
	return pyFloatRepr(value)
}

// pyFloatRepr reproduces repr() for a float: the shortest decimal that
// round-trips, written with an exponent only when the decimal point falls
// outside -4..16. Go's 'g' format switches at a different threshold, so 1e15
// would come out as 1e+15 where Python writes 1000000000000000.0.
func pyFloatRepr(value float64) string {
	switch {
	case math.IsNaN(value):
		return "nan"
	case math.IsInf(value, 1):
		return "inf"
	case math.IsInf(value, -1):
		return "-inf"
	case value == 0:
		if math.Signbit(value) {
			return "-0.0"
		}
		return "0.0"
	}
	mantissa, exponent, _ := strings.Cut(strconv.FormatFloat(value, 'e', -1, 64), "e")
	power, _ := strconv.Atoi(exponent)
	negative := strings.HasPrefix(mantissa, "-")
	digits := strings.Replace(strings.TrimPrefix(mantissa, "-"), ".", "", 1)
	point := power + 1

	var text string
	if point <= -4 || point > 16 {
		text = digits[:1]
		if len(digits) > 1 {
			text += "." + digits[1:]
		}
		text += fmt.Sprintf("e%+03d", point-1)
	} else if point <= 0 {
		text = "0." + strings.Repeat("0", -point) + digits
	} else if point >= len(digits) {
		text = digits + strings.Repeat("0", point-len(digits)) + ".0"
	} else {
		text = digits[:point] + "." + digits[point:]
	}
	if negative {
		return "-" + text
	}
	return text
}

func pyReprOrNone(text string) string {
	if text == "" {
		return "None"
	}
	return pyStringRepr(text)
}

// pyStringRepr reproduces repr() for a str. Two rules are easy to miss and both
// are reachable from a report: Python switches to double quotes when the text
// contains an apostrophe and no double quote, and it escapes every rune that is
// not printable by Unicode category, not just the ASCII control characters.
// referencePrintable pins that category test to the reference Unicode version.
func pyStringRepr(text string) string {
	quote := '\''
	if strings.ContainsRune(text, '\'') && !strings.ContainsRune(text, '"') {
		quote = '"'
	}
	var builder strings.Builder
	builder.WriteRune(quote)
	for _, r := range text {
		switch {
		case r == quote || r == '\\':
			builder.WriteByte('\\')
			builder.WriteRune(r)
		case r == '\t':
			builder.WriteString(`\t`)
		case r == '\n':
			builder.WriteString(`\n`)
		case r == '\r':
			builder.WriteString(`\r`)
		case referencePrintable(r):
			builder.WriteRune(r)
		case r < 0x100:
			fmt.Fprintf(&builder, `\x%02x`, r)
		case r < 0x10000:
			fmt.Fprintf(&builder, `\u%04x`, r)
		default:
			fmt.Fprintf(&builder, `\U%08x`, r)
		}
	}
	builder.WriteRune(quote)
	return builder.String()
}

func pyListRepr(items []string) string {
	quoted := make([]string, len(items))
	for i, item := range items {
		quoted[i] = pyStringRepr(item)
	}
	return "[" + strings.Join(quoted, ", ") + "]"
}
