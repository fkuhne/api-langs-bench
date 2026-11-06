// Package fake is the in-process fake: the contract's tokens, at the contract's pace
// (contract/README.md#the-fakes).
package fake

import (
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"path/filepath"
)

// TokensFile is where every image and every gate finds the contract's tokens
// (spec/decisions/0011).
const TokensFile = "/contract/fake-tokens.json"

// ErrMalformedTokens means the file isn't a non-empty JSON list of non-empty strings.
var ErrMalformedTokens = errors.New("malformed tokens file")

// LoadTokens returns the tokens in the file at path, in order.
func LoadTokens(path string) ([]string, error) {
	data, err := os.ReadFile(filepath.Clean(path))
	if err != nil {
		return nil, fmt.Errorf("reading the tokens: %w", err)
	}
	var tokens []string
	if err := json.Unmarshal(data, &tokens); err != nil {
		return nil, fmt.Errorf("%s: %w: %w", path, ErrMalformedTokens, err)
	}
	if len(tokens) == 0 {
		return nil, fmt.Errorf("%s: %w: no tokens", path, ErrMalformedTokens)
	}
	for i, token := range tokens {
		if token == "" {
			return nil, fmt.Errorf("%s: %w: token %d is empty", path, ErrMalformedTokens, i)
		}
	}
	return tokens, nil
}
