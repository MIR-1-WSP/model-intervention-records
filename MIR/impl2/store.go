package main

// Content-addressed store and locators, MIR-1 sections 4.11 and 4.12.

import (
	"crypto/sha256"
	"encoding/hex"
	"fmt"
	"math/big"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"time"
)

const locatorSuffix = ".locator.json"

type store struct {
	roots []string
}

func newStore(roots []string) *store {
	s := &store{}
	for _, root := range roots {
		if root == "" {
			continue
		}
		info, err := os.Stat(root)
		if err == nil && info.IsDir() {
			s.roots = append(s.roots, root)
		}
	}
	return s
}

// find returns "bytes" when the store holds the content under the digest, and
// "locator" when it holds a claim about where the content is.
func (s *store) find(digest string) (kind, path string) {
	if digest == "" {
		return "", ""
	}
	for _, root := range s.roots {
		candidate := filepath.Join(root, digest)
		if isFile(candidate) {
			return "bytes", candidate
		}
		candidate = filepath.Join(root, digest+locatorSuffix)
		if isFile(candidate) {
			return "locator", candidate
		}
	}
	return "", ""
}

func (s *store) present(digest string) bool {
	kind, _ := s.find(digest)
	return kind != ""
}

func isFile(path string) bool {
	info, err := os.Stat(path)
	return err == nil && info.Mode().IsRegular()
}

type locator struct {
	URL  string
	Size *big.Int
}

// readLocator checks a locator against the digest it is named for. A locator is
// a claim, so it has to be internally consistent before it can be reported as
// an artifact that resolves.
func readLocator(path, digest string) (*locator, string) {
	raw, err := os.ReadFile(path)
	if err != nil {
		return nil, "locator unreadable"
	}
	document, err := decodeJSON(raw)
	if err != nil {
		return nil, "locator is not valid JSON"
	}
	object, ok := document.(*jobject)
	if !ok {
		return nil, "locator is not an object"
	}
	if kind, _ := object.get("kind"); kind != "mir-locator" {
		return nil, "not a mir-locator"
	}
	declared, _ := object.get("sha256")
	if value, ok := normHash(declared); !ok || value != digest {
		return nil, "locator sha256 does not match its name"
	}
	sizeValue, _ := object.get("size")
	size, ok := integerValue(sizeValue)
	if !ok || size.Sign() <= 0 {
		return nil, "locator size missing or invalid"
	}
	url, _ := object.get("url")
	text, ok := url.(string)
	if !ok || !(strings.HasPrefix(text, "http://") || strings.HasPrefix(text, "https://")) {
		return nil, "locator url missing or not http(s)"
	}
	return &locator{URL: text, Size: size}, ""
}

// remoteHead asks the host for the digest and the size without downloading.
// Hugging Face answers a HEAD request for a resolve URL with x-linked-etag on
// the redirect and the size on the final response, so this costs one request
// and no bytes. Any other host is accepted if it returns a matching ETag.
func remoteHead(loc *locator, digest string) (bool, string) {
	client := &http.Client{
		Timeout: 20 * time.Second,
		CheckRedirect: func(*http.Request, []*http.Request) error {
			// The digest is on the redirect, not on the object it points at.
			return http.ErrUseLastResponse
		},
	}
	request, err := http.NewRequest("HEAD", loc.URL, nil)
	if err != nil {
		return false, fmt.Sprintf("remote check failed (%v)", err)
	}
	request.Header.Set("User-Agent", "mir-1/1.2")
	response, err := client.Do(request)
	if err != nil {
		return false, fmt.Sprintf("remote check failed (%v)", err)
	}
	defer response.Body.Close()

	etag := response.Header.Get("x-linked-etag")
	if etag == "" {
		etag = response.Header.Get("etag")
	}
	linkedSizes := response.Header.Values("x-linked-size")
	length := response.Header.Get("content-length")
	status := response.StatusCode

	etag = referenceTrimSpace(etag)
	etag = strings.Trim(etag, `"`)
	etag = referenceLower(etag)
	if strings.HasPrefix(etag, "w/") {
		etag = strings.Trim(referenceTrimSpace(etag[2:]), `"`)
	}
	if etag != digest {
		reported := etag
		if len(reported) > 16 {
			reported = reported[:16]
		}
		return false, fmt.Sprintf("host reports etag %s for %s", pyReprOrNone(reported), digest[:16])
	}

	if len(linkedSizes) > 0 && isDigits(linkedSizes[0]) {
		reported, _ := new(big.Int).SetString(linkedSizes[0], 10)
		if reported.Cmp(loc.Size) != 0 {
			return false, fmt.Sprintf("host reports size %s, locator declares %d", linkedSizes[0], loc.Size)
		}
	}
	if len(linkedSizes) == 0 && status == http.StatusOK && isDigits(length) {
		reported, _ := new(big.Int).SetString(length, 10)
		if reported.Cmp(loc.Size) != 0 {
			return false, fmt.Sprintf("host reports size %s, locator declares %d", length, loc.Size)
		}
	}
	return true, ""
}

func sha256Hex(payload []byte) string {
	sum := sha256.Sum256(payload)
	return hex.EncodeToString(sum[:])
}

func isDigits(text string) bool {
	if text == "" {
		return false
	}
	for _, r := range text {
		if r < '0' || r > '9' {
			return false
		}
	}
	return true
}
