package llm_test

import (
	"encoding/json"
	"errors"
	"testing"

	"github.com/fkuhne/api-langs-bench/backends/go/internal/llm"
)

func TestParametersKeepEachNumbersText(t *testing.T) {
	var parameters llm.Parameters

	err := json.Unmarshal([]byte(`{"max_tokens": 5, "temperature": 5.0, "stop": ["\n"]}`), &parameters)
	if err != nil {
		t.Fatal(err)
	}

	if got := parameters["max_tokens"]; got != json.Number("5") {
		t.Errorf("got max_tokens %#v, want json.Number 5", got)
	}
	if got := parameters["temperature"]; got != json.Number("5.0") {
		t.Errorf("got temperature %#v, want json.Number 5.0", got)
	}
}

func TestReservedParametersAreRefused(t *testing.T) {
	var parameters llm.Parameters

	err := json.Unmarshal([]byte(`{"stream": true, "model": "x", "seed": 1}`), &parameters)

	if !errors.Is(err, llm.ErrReservedParameter) {
		t.Fatalf("got %v, want ErrReservedParameter", err)
	}
	if want := "the backend sets these parameters itself: model, stream"; err.Error() != want {
		t.Errorf("got %q, want %q", err, want)
	}
}

func TestParametersMustBeAnObject(t *testing.T) {
	for _, body := range []string{`null`, `[]`, `"max_tokens"`, `5`} {
		t.Run(body, func(t *testing.T) {
			var parameters llm.Parameters

			err := json.Unmarshal([]byte(body), &parameters)

			if !errors.Is(err, llm.ErrParametersNotObject) {
				t.Errorf("got %v, want ErrParametersNotObject", err)
			}
		})
	}
}

func TestOnlyTheContractsRolesAreValid(t *testing.T) {
	for role, want := range map[llm.Role]bool{
		"system": true, "user": true, "assistant": true, "tool": false, "User": false, "": false,
	} {
		if got := role.Valid(); got != want {
			t.Errorf("%q: got %v, want %v", role, got, want)
		}
	}
}

func TestEachPartHasItsEvent(t *testing.T) {
	parts := map[string]interface{ Event() string }{
		"reasoning": llm.ReasoningDelta{},
		"token":     llm.ContentDelta{},
		"done":      llm.StreamEnd{},
		"error":     llm.ErrorEvent{},
	}
	for want, part := range parts {
		if got := part.Event(); got != want {
			t.Errorf("%T: got %q, want %q", part, got, want)
		}
	}
}

func TestAServiceErrorBecomesItsEvent(t *testing.T) {
	err := &llm.ServiceError{Status: 503, Detail: "down"}

	if got, want := err.Event(), (llm.ErrorEvent{Status: 503, Detail: "down"}); got != want {
		t.Errorf("got %+v, want %+v", got, want)
	}
	if err.Error() != "down" {
		t.Errorf("got %q, want the detail", err.Error())
	}
}

func TestTheServiceStatusesAreTheContracts(t *testing.T) {
	for status, want := range map[int64]bool{429: true, 502: true, 503: true, 504: true, 500: false, 200: false} {
		if got := llm.IsServiceStatus(status); got != want {
			t.Errorf("%d: got %v, want %v", status, got, want)
		}
	}
}
