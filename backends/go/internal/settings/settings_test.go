package settings_test

import (
	"errors"
	"testing"
	"time"

	"github.com/fkuhne/api-langs-bench/backends/go/internal/settings"
)

func environment(values map[string]string) func(string) (string, bool) {
	return func(name string) (string, bool) {
		value, set := values[name]
		return value, set
	}
}

func TestUnsetVariablesKeepTheContractsDefaults(t *testing.T) {
	got, err := settings.Load(environment(nil))
	if err != nil {
		t.Fatal(err)
	}

	want := settings.Settings{
		LLMProvider: "fake", LLMBaseURL: "http://fake-server:8080/v1", LLMModel: "local",
		LLMAPIKey: "local", LLMTimeout: 300 * time.Second, LLMMaxConnections: 1000,
		FakeAnswerTokens: 256,
	}
	if got != want {
		t.Errorf("got %+v, want %+v", got, want)
	}
}

func TestEachVariableSetsItsSetting(t *testing.T) {
	got, err := settings.Load(environment(map[string]string{
		"LLM_PROVIDER":          "openai-compatible",
		"LLM_BASE_URL":          "https://upstream.example/v1",
		"LLM_MODEL":             "a-model",
		"LLM_API_KEY":           "a-key",
		"LLM_TIMEOUT_SECONDS":   "1.5",
		"LLM_MAX_CONNECTIONS":   "8",
		"FAKE_ANSWER_TOKENS":    "5",
		"FAKE_REASONING_TOKENS": "2",
		"FAKE_FIRST_TOKEN_MS":   "100",
		"FAKE_TOKEN_GAP_MS":     "20",
	}))
	if err != nil {
		t.Fatal(err)
	}

	want := settings.Settings{
		LLMProvider: "openai-compatible", LLMBaseURL: "https://upstream.example/v1",
		LLMModel: "a-model", LLMAPIKey: "a-key", LLMTimeout: 1500 * time.Millisecond,
		LLMMaxConnections: 8, FakeAnswerTokens: 5, FakeReasoningTokens: 2,
		FakeFirstTokenMS: 100, FakeTokenGapMS: 20,
	}
	if got != want {
		t.Errorf("got %+v, want %+v", got, want)
	}
}

func TestAnInvalidValueIsRefused(t *testing.T) {
	cases := map[string]map[string]string{
		"an unknown provider":         {"LLM_PROVIDER": "psychic"},
		"a URL without a scheme":      {"LLM_BASE_URL": "fake-server:8080"},
		"a URL that isn't one":        {"LLM_BASE_URL": "http://bad host"},
		"a URL without a host":        {"LLM_BASE_URL": "http://"},
		"an empty URL":                {"LLM_BASE_URL": ""},
		"an empty model":              {"LLM_MODEL": ""},
		"an empty key":                {"LLM_API_KEY": ""},
		"no timeout":                  {"LLM_TIMEOUT_SECONDS": "0"},
		"an endless timeout":          {"LLM_TIMEOUT_SECONDS": "inf"},
		"a timeout that isn't a time": {"LLM_TIMEOUT_SECONDS": "soon"},
		"a timeout that isn't one":    {"LLM_TIMEOUT_SECONDS": "nan"},
		"no connections":              {"LLM_MAX_CONNECTIONS": "0"},
		"half a connection":           {"LLM_MAX_CONNECTIONS": "1.5"},
		"no answer tokens":            {"FAKE_ANSWER_TOKENS": "0"},
		"negative reasoning":          {"FAKE_REASONING_TOKENS": "-1"},
		"a fraction":                  {"FAKE_FIRST_TOKEN_MS": "1.5"},
		"not a number":                {"FAKE_TOKEN_GAP_MS": "fast"},
		"set, but empty":              {"FAKE_TOKEN_GAP_MS": ""},
		"a provider set, but empty":   {"LLM_PROVIDER": ""},
		"a number with a unit suffix": {"FAKE_FIRST_TOKEN_MS": "100ms"},
	}
	for name, values := range cases {
		t.Run(name, func(t *testing.T) {
			if _, err := settings.Load(environment(values)); !errors.Is(err, settings.ErrInvalid) {
				t.Errorf("got %v, want ErrInvalid", err)
			}
		})
	}
}
