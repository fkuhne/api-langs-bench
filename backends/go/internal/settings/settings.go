// Package settings reads the backend's settings from the environment at start-up
// (contract/README.md#settings).
package settings

import (
	"errors"
	"fmt"
	"strconv"
)

// Settings holds every setting the contract names.
type Settings struct {
	// LLMProvider is "fake" for the in-process fake. "openai-compatible" arrives with the
	// upstream's client, in plan step 2.2.
	LLMProvider         string
	FakeAnswerTokens    int
	FakeReasoningTokens int
	FakeFirstTokenMS    int
	FakeTokenGapMS      int
}

// ErrInvalid means a setting has a value the contract doesn't allow.
var ErrInvalid = errors.New("invalid setting")

// Default returns the contract's defaults.
func Default() Settings {
	return Settings{LLMProvider: "fake", FakeAnswerTokens: 256}
}

// Load reads each setting with lookup, such as os.LookupEnv. An unset variable keeps its
// default; an invalid value is an error, so the backend refuses to start.
func Load(lookup func(string) (string, bool)) (Settings, error) {
	s := Default()
	if value, set := lookup("LLM_PROVIDER"); set {
		if value != "fake" {
			return Settings{}, fmt.Errorf("%w: LLM_PROVIDER must be fake, not %q", ErrInvalid, value)
		}
		s.LLMProvider = value
	}
	wholes := []struct {
		name string
		min  int
		into *int
	}{
		{"FAKE_ANSWER_TOKENS", 1, &s.FakeAnswerTokens},
		{"FAKE_REASONING_TOKENS", 0, &s.FakeReasoningTokens},
		{"FAKE_FIRST_TOKEN_MS", 0, &s.FakeFirstTokenMS},
		{"FAKE_TOKEN_GAP_MS", 0, &s.FakeTokenGapMS},
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
