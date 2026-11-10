// Package tokens loads the contract's tokens, which both fakes answer with
// (contract/README.md#the-answer).
package tokens

import (
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"path/filepath"
)

// File is where every image and every gate finds the contract's tokens
// (spec/decisions/0011).
const File = "/contract/fake-tokens.json"

// ErrMalformed means the file isn't a non-empty JSON list of non-empty strings.
var ErrMalformed = errors.New("malformed tokens file")

// Load returns the tokens in the file at path, in order.
func Load(path string) ([]string, error) {
	data, err := os.ReadFile(filepath.Clean(path))
	if err != nil {
		return nil, fmt.Errorf("reading the tokens: %w", err)
	}
	var tokens []string
	if err := json.Unmarshal(data, &tokens); err != nil {
		return nil, fmt.Errorf("%s: %w: %w", path, ErrMalformed, err)
	}
	if len(tokens) == 0 {
		return nil, fmt.Errorf("%s: %w: no tokens", path, ErrMalformed)
	}
	for i, token := range tokens {
		if token == "" {
			return nil, fmt.Errorf("%s: %w: token %d is empty", path, ErrMalformed, i)
		}
	}
	return tokens, nil
}
