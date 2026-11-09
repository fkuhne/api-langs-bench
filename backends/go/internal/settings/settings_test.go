package settings_test

import (
	"errors"
	"testing"

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

	want := settings.Settings{LLMProvider: "fake", FakeAnswerTokens: 256}
	if got != want {
		t.Errorf("got %+v, want %+v", got, want)
	}
}

func TestEachVariableSetsItsSetting(t *testing.T) {
	got, err := settings.Load(environment(map[string]string{
		"LLM_PROVIDER":          "fake",
		"FAKE_ANSWER_TOKENS":    "5",
		"FAKE_REASONING_TOKENS": "2",
		"FAKE_FIRST_TOKEN_MS":   "100",
		"FAKE_TOKEN_GAP_MS":     "20",
	}))
	if err != nil {
		t.Fatal(err)
	}

	want := settings.Settings{
		LLMProvider: "fake", FakeAnswerTokens: 5, FakeReasoningTokens: 2,
		FakeFirstTokenMS: 100, FakeTokenGapMS: 20,
	}
	if got != want {
		t.Errorf("got %+v, want %+v", got, want)
	}
}

func TestAnInvalidValueIsRefused(t *testing.T) {
	cases := map[string]map[string]string{
		"an unknown provider":         {"LLM_PROVIDER": "openai-compatible"},
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
