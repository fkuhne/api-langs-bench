package nethttp_test

import (
	"context"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/fkuhne/api-langs-bench/backends/go/internal/apitest"
	"github.com/fkuhne/api-langs-bench/backends/go/internal/fake"
	"github.com/fkuhne/api-langs-bench/backends/go/internal/nethttp"
	"github.com/fkuhne/api-langs-bench/backends/go/internal/settings"
)

func TestTheContract(t *testing.T) {
	apitest.Run(t, nethttp.New)
}

// The stream's bytes are the contract's example, to the byte (contract/README.md#the-stream).
func TestTheStreamIsTheContractsExample(t *testing.T) {
	tokens, err := fake.LoadTokens(fake.TokensFile)
	if err != nil {
		t.Fatal(err)
	}
	handler := nethttp.New(fake.New(settings.Default(), tokens, nil))
	request := httptest.NewRequestWithContext(context.Background(), http.MethodPost, "/api/chat/stream",
		strings.NewReader(apitest.Question))
	response := httptest.NewRecorder()

	handler.ServeHTTP(response, request)

	want := "event: token\ndata: {\"text\":\"A\"}\n\n" +
		"event: token\ndata: {\"text\":\" backend\"}\n\n" +
		"event: token\ndata: {\"text\":\" in\"}\n\n" +
		"event: token\ndata: {\"text\":\" front\"}\n\n" +
		"event: token\ndata: {\"text\":\" of\"}\n\n" +
		"event: done\ndata: {\"model\":\"fake\",\"finish_reason\":\"length\"," +
		"\"usage\":{\"prompt_tokens\":7,\"completion_tokens\":5,\"total_tokens\":12}}\n\n"
	if got := response.Body.String(); got != want {
		t.Errorf("got\n%q\nwant\n%q", got, want)
	}
}
