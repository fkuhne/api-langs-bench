// Package settings reads the backend's settings from the environment at start-up
// (contract/README.md#settings).
package settings

import (
	"errors"
	"fmt"
	"math"
	"net/url"
	"strconv"
	"time"
)

// The providers LLM_PROVIDER can name.
const (
	// ProviderFake answers from the in-process fake.
	ProviderFake = "fake"
	// ProviderOpenAICompatible calls the upstream.
	ProviderOpenAICompatible = "openai-compatible"
)

// Settings holds every setting the contract names.
type Settings struct {
	LLMProvider string

	// The upstream (contract/README.md#the-upstream).
	LLMBaseURL        string
	LLMModel          string
	LLMAPIKey         string
	LLMTimeout        time.Duration
	LLMMaxConnections int

	// The in-process fake (contract/README.md#the-fakes).
	FakeAnswerTokens    int
	FakeReasoningTokens int
	FakeFirstTokenMS    int
	FakeTokenGapMS      int
}

// ErrInvalid means a setting has a value the contract doesn't allow.
var ErrInvalid = errors.New("invalid setting")

// Default returns the contract's defaults.
func Default() Settings {
	return Settings{
		LLMProvider:       ProviderFake,
		LLMBaseURL:        "http://fake-server:8080/v1",
		LLMModel:          "local",
		LLMAPIKey:         "local",
		LLMTimeout:        300 * time.Second,
		LLMMaxConnections: 1000,
		FakeAnswerTokens:  256,
	}
}

// Load reads each setting with lookup, such as os.LookupEnv. An unset variable keeps its
// default; an invalid value is an error, so the backend refuses to start.
func Load(lookup func(string) (string, bool)) (Settings, error) {
	s := Default()
	if value, set := lookup("LLM_PROVIDER"); set {
		if value != ProviderFake && value != ProviderOpenAICompatible {
			return Settings{}, fmt.Errorf("%w: LLM_PROVIDER must be %s or %s, not %q",
				ErrInvalid, ProviderFake, ProviderOpenAICompatible, value)
		}
		s.LLMProvider = value
	}
	if value, set := lookup("LLM_BASE_URL"); set {
		parsed, err := url.Parse(value)
		if err != nil || (parsed.Scheme != "http" && parsed.Scheme != "https") || parsed.Host == "" {
			return Settings{}, fmt.Errorf("%w: LLM_BASE_URL must be an http or https URL, not %q",
				ErrInvalid, value)
		}
		s.LLMBaseURL = value
	}
	texts := []struct {
		name string
		into *string
	}{
		{"LLM_MODEL", &s.LLMModel},
		{"LLM_API_KEY", &s.LLMAPIKey},
	}
	for _, setting := range texts {
		value, set := lookup(setting.name)
		if !set {
			continue
		}
		if value == "" {
			return Settings{}, fmt.Errorf("%w: %s must not be empty", ErrInvalid, setting.name)
		}
		*setting.into = value
	}
	if value, set := lookup("LLM_TIMEOUT_SECONDS"); set {
		seconds, err := strconv.ParseFloat(value, 64)
		if err != nil || math.IsNaN(seconds) || math.IsInf(seconds, 0) || seconds <= 0 {
			return Settings{}, fmt.Errorf("%w: LLM_TIMEOUT_SECONDS must be a number above 0, not %q",
				ErrInvalid, value)
		}
		s.LLMTimeout = time.Duration(seconds * float64(time.Second))
	}
	wholes := []struct {
		name string
		min  int
		into *int
	}{
		{"LLM_MAX_CONNECTIONS", 1, &s.LLMMaxConnections},
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
