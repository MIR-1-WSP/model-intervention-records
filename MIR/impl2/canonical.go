package main

// Canonical form, MIR-1 section 4.13.
//
// A record's id is the SHA-256 of its canonical bytes, so two implementations
// that serialize the same value differently produce different ids for the same
// record. Everything in this file exists to make that impossible: the decoder
// keeps enough of the input to reproduce the reference implementation's
// messages, and the encoder writes exactly the bytes the spec defines.

import (
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"math"
	"math/big"
	"sort"
	"strconv"
	"strings"
	"unicode/utf8"
)

// jobject is a JSON object that remembers the order its members were written
// in. Canonical output sorts the names, but C-03 reports unresolved hashes in
// the order they appear in the record, and that order is document order.
type jobject struct {
	keys []string
	vals map[string]any
}

func newObject() *jobject {
	return &jobject{vals: make(map[string]any)}
}

func (o *jobject) set(key string, value any) {
	if _, exists := o.vals[key]; !exists {
		o.keys = append(o.keys, key)
	}
	o.vals[key] = value
}

func (o *jobject) get(key string) (any, bool) {
	if o == nil {
		return nil, false
	}
	value, ok := o.vals[key]
	return value, ok
}

func (o *jobject) has(key string) bool {
	if o == nil {
		return false
	}
	_, ok := o.vals[key]
	return ok
}

// decodeJSON reads one JSON value and rejects anything after it. Numbers keep
// their literal spelling, because 4 and 4.0 are different values under 4.13.
// maxNesting bounds document depth. Without a shared bound the reference
// implementation recurses until it crashes and this one does not, so the two
// would disagree about the same record.
const maxNesting = 256

var (
	errNotUTF8       = errors.New("record is not valid UTF-8")
	errLoneSurrogate = errors.New("record contains a lone surrogate")
	errTooDeep       = errors.New("record is nested too deeply")
)

func hexUnit(text string, start int) (int, bool) {
	if start+4 > len(text) {
		return 0, false
	}
	value, err := strconv.ParseUint(text[start:start+4], 16, 16)
	if err != nil {
		return 0, false
	}
	return int(value), true
}

// scanText rejects what the canonical form cannot represent, before parsing. It
// mirrors _scan_text in validate.py so a malformed record fails with the same
// detail in either. The decoder replaces a lone surrogate with U+FFFD while
// parsing, so the escape has to be found in the raw text.
func scanText(text string) error {
	depth := 0
	inString := false
	for i := 0; i < len(text); i++ {
		char := text[i]
		if !inString {
			switch char {
			case '"':
				inString = true
			case '[', '{':
				depth++
				if depth > maxNesting {
					return errTooDeep
				}
			case ']', '}':
				depth--
			}
			continue
		}
		switch char {
		case '"':
			inString = false
		case '\\':
			i++
			if i >= len(text) {
				return nil
			}
			if text[i] != 'u' {
				continue
			}
			unit, ok := hexUnit(text, i+1)
			if !ok {
				return nil
			}
			i += 4
			if unit >= 0xDC00 && unit <= 0xDFFF {
				return errLoneSurrogate
			}
			if unit >= 0xD800 && unit <= 0xDBFF {
				if i+7 > len(text) || text[i+1] != '\\' || text[i+2] != 'u' {
					return errLoneSurrogate
				}
				low, ok := hexUnit(text, i+3)
				if !ok || low < 0xDC00 || low > 0xDFFF {
					return errLoneSurrogate
				}
				i += 6
			}
		}
	}
	return nil
}

func decodeJSON(raw []byte) (any, error) {
	if !utf8.Valid(raw) {
		return nil, errNotUTF8
	}
	if err := scanText(string(raw)); err != nil {
		return nil, err
	}
	dec := json.NewDecoder(bytes.NewReader(raw))
	dec.UseNumber()
	value, err := decodeValue(dec)
	if err != nil {
		return nil, err
	}
	if _, err := dec.Token(); err != io.EOF {
		return nil, errors.New("trailing data after the JSON value")
	}
	return value, nil
}

func decodeValue(dec *json.Decoder) (any, error) {
	token, err := dec.Token()
	if err != nil {
		return nil, err
	}
	delim, isDelim := token.(json.Delim)
	if !isDelim {
		return token, nil
	}
	switch delim {
	case '{':
		object := newObject()
		for dec.More() {
			keyToken, err := dec.Token()
			if err != nil {
				return nil, err
			}
			key, ok := keyToken.(string)
			if !ok {
				return nil, errors.New("object key is not a string")
			}
			value, err := decodeValue(dec)
			if err != nil {
				return nil, err
			}
			object.set(key, value)
		}
		if _, err := dec.Token(); err != nil { // closing brace
			return nil, err
		}
		return object, nil
	case '[':
		array := []any{}
		for dec.More() {
			value, err := decodeValue(dec)
			if err != nil {
				return nil, err
			}
			array = append(array, value)
		}
		if _, err := dec.Token(); err != nil { // closing bracket
			return nil, err
		}
		return array, nil
	default:
		return nil, fmt.Errorf("unexpected %q in JSON", delim)
	}
}

// canonicalBytes implements MIR-1 section 4.13.
func canonicalBytes(value any) ([]byte, error) {
	var buf bytes.Buffer
	if err := writeCanonical(&buf, value); err != nil {
		return nil, err
	}
	return buf.Bytes(), nil
}

func writeCanonical(buf *bytes.Buffer, node any) error {
	switch value := node.(type) {
	case nil:
		buf.WriteString("null")
	case bool:
		if value {
			buf.WriteString("true")
		} else {
			buf.WriteString("false")
		}
	case string:
		return writeCanonicalString(buf, value)
	case json.Number:
		text, err := canonicalNumber(value)
		if err != nil {
			return err
		}
		buf.WriteString(text)
	case []any:
		buf.WriteByte('[')
		for i, item := range value {
			if i > 0 {
				buf.WriteByte(',')
			}
			if err := writeCanonical(buf, item); err != nil {
				return err
			}
		}
		buf.WriteByte(']')
	case *jobject:
		names := append([]string(nil), value.keys...)
		sort.Strings(names)
		buf.WriteByte('{')
		for i, name := range names {
			if i > 0 {
				buf.WriteByte(',')
			}
			if err := writeCanonicalString(buf, name); err != nil {
				return err
			}
			buf.WriteByte(':')
			if err := writeCanonical(buf, value.vals[name]); err != nil {
				return err
			}
		}
		buf.WriteByte('}')
	default:
		return fmt.Errorf("cannot canonicalize %T", node)
	}
	return nil
}

// writeCanonicalString escapes only what has to be escaped. Non-ASCII is
// written as UTF-8, so the bytes do not depend on a locale or on a serializer's
// ASCII policy.
func writeCanonicalString(buf *bytes.Buffer, value string) error {
	if !utf8.ValidString(value) {
		return errors.New("string is not valid UTF-8")
	}
	buf.WriteByte('"')
	for _, r := range value {
		switch r {
		case '"':
			buf.WriteString(`\"`)
		case '\\':
			buf.WriteString(`\\`)
		case '\b':
			buf.WriteString(`\b`)
		case '\f':
			buf.WriteString(`\f`)
		case '\n':
			buf.WriteString(`\n`)
		case '\r':
			buf.WriteString(`\r`)
		case '\t':
			buf.WriteString(`\t`)
		default:
			if r < 0x20 {
				fmt.Fprintf(buf, `\u%04x`, r)
			} else {
				buf.WriteRune(r)
			}
		}
	}
	buf.WriteByte('"')
	return nil
}

// canonicalNumber writes an integer as digits and a fractional value as plain
// decimal with at least one digit after the point. Exponent notation does not
// conform, and neither does dropping the fraction from 100.0.
func canonicalNumber(number json.Number) (string, error) {
	literal := string(number)
	if !strings.ContainsAny(literal, ".eE") {
		value, ok := new(big.Int).SetString(literal, 10)
		if !ok {
			return "", fmt.Errorf("invalid integer literal %q", literal)
		}
		return value.String(), nil
	}
	value, err := strconv.ParseFloat(literal, 64)
	if err != nil {
		return "", fmt.Errorf("invalid number %q: %v", literal, err)
	}
	return canonicalFloat(value)
}

func canonicalFloat(value float64) (string, error) {
	if math.IsNaN(value) || math.IsInf(value, 0) {
		return "", errors.New("non-finite number")
	}
	// 'f' never uses an exponent; precision -1 keeps only the digits needed to
	// round-trip, which is the shortest correct decimal for the value.
	text := strconv.FormatFloat(value, 'f', -1, 64)
	if !strings.Contains(text, ".") {
		text += ".0"
	}
	return text, nil
}
