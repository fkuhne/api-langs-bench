// Package settings reads the fake server's settings from the environment at start-up: the
// contract's FAKE_* variables, which the in-process fakes read too
// (contract/README.md#settings).
package settings

import (
	"errors"
	"fmt"
	"strconv"
)

// Settings holds the fake's settings.
type Settings struct {
	AnswerTokens    int
	ReasoningTokens int
	FirstTokenMS    int
	TokenGapMS      int
}

// ErrInvalid means a setting has a value the contract doesn't allow.
var ErrInvalid = errors.New("invalid setting")

// Default returns the contract's defaults.
func Default() Settings {
	return Settings{AnswerTokens: 256}
}

// Load reads each setting with lookup, such as os.LookupEnv. An unset variable keeps its
// default; an invalid value is an error, so the server refuses to start.
func Load(lookup func(string) (string, bool)) (Settings, error) {
	s := Default()
	wholes := []struct {
		name string
		min  int
		into *int
	}{
		{"FAKE_ANSWER_TOKENS", 1, &s.AnswerTokens},
		{"FAKE_REASONING_TOKENS", 0, &s.ReasoningTokens},
		{"FAKE_FIRST_TOKEN_MS", 0, &s.FirstTokenMS},
		{"FAKE_TOKEN_GAP_MS", 0, &s.TokenGapMS},
	}
	for _, setting := range wholes {
		value, set := lookup(setting.name)
		if !set {
			continue
		}
		number, err := strconv.Atoi(value)
		if err != nil || number < setting.min {
			return Settings{}, fmt.Errorf("%w: %s must be a whole number, %d or more, not %q",
				ErrInvalid, setting.name, setting.min, value)
		}
		*setting.into = number
	}
	return s, nil
}
