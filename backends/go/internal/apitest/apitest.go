// Package apitest checks that a backend's routes keep the contract (contract/README.md). Every
// Go backend's tests call Run with its routes, so all of them are held to the same checks
// (spec/decisions/0016).
package apitest

import (
	"bufio"
	"context"
	"encoding/json"
	"errors"
	"io"
	"iter"
	"net/http"
	"net/http/httptest"
	"reflect"
	"strconv"
	"strings"
	"sync/atomic"
	"testing"
	"time"

	"github.com/fkuhne/api-langs-bench/backends/go/internal/fake"
	"github.com/fkuhne/api-langs-bench/backends/go/internal/llm"
	"github.com/fkuhne/api-langs-bench/backends/go/internal/settings"
)

// Question is the contract's example request.
const Question = `{"messages": [{"role": "user", "content": "In one sentence, what is an LLM?"}], ` +
	`"parameters": {"max_tokens": 5}}`

// Completion is the contract's whole answer to Question.
const Completion = `{"content": "A backend in front of", "reasoning": null, "model": "fake", ` +
	`"finish_reason": "length", "usage": {"prompt_tokens": 7, "completion_tokens": 5, "total_tokens": 12}}`

// Done is the data of the `done` event that ends the stream answering Question.
const Done = `{"model": "fake", "finish_reason": "length", ` +
	`"usage": {"prompt_tokens": 7, "completion_tokens": 5, "total_tokens": 12}}`

// Run checks the routes newHandler makes against the contract.
func Run(t *testing.T, newHandler func(llm.Client) http.Handler) {
	t.Helper()
	checks := map[string]func(*testing.T, func(llm.Client) http.Handler){
		"liveness":                                  liveness,
		"readiness with the fake":                   readiness,
		"readiness while the upstream is down":      readinessUnavailable,
		"the whole answer":                          wholeAnswer,
		"the stream sends each token then done":     stream,
		"an invalid body answers 422":               invalidBody,
		"other fields are ignored":                  otherFields,
		"an upstream failure answers its status":    upstreamFailure,
		"a failure ends the stream with an error":   streamFailure,
		"a malformed fake_error is refused":         malformedFakeError,
		"parameters reach the model as given":       parametersAsGiven,
		"an unexpected error answers 500":           unexpectedError,
		"the stream's headers go before its tokens": headersFirst,
		"a client that leaves stops the fake":       clientLeaves,
	}
	for name, check := range checks {
		t.Run(name, func(t *testing.T) { check(t, newHandler) })
	}
}

// Event is one server-sent event, its data parsed.
type Event struct {
	Name string
	Data any
}

// Events parses a stream's body by the SSE rules: a field's value loses one leading space,
// and comments are skipped.
func Events(t *testing.T, body string) []Event {
	t.Helper()
	var events []Event
	for block := range strings.SplitSeq(body, "\n\n") {
		var event Event
		var data string
		for line := range strings.SplitSeq(block, "\n") {
			if line == "" || strings.HasPrefix(line, ":") {
				continue
			}
			field, value, _ := strings.Cut(line, ":")
			value = strings.TrimPrefix(value, " ")
			switch field {
			case "event":
				event.Name = value
			case "data":
				data = value
			default:
				t.Errorf("unexpected field %q in %q", field, block)
			}
		}
		if event.Name == "" && data == "" {
			continue
		}
		event.Data = parseJSON(t, data)
		events = append(events, event)
	}
	return events
}

func parseJSON(t *testing.T, text string) any {
	t.Helper()
	var value any
	if err := json.Unmarshal([]byte(text), &value); err != nil {
		t.Fatalf("not JSON: %q: %v", text, err)
	}
	return value
}

func assertJSON(t *testing.T, got, want string) {
	t.Helper()
	if g, w := parseJSON(t, got), parseJSON(t, want); !reflect.DeepEqual(g, w) {
		t.Errorf("got %s, want %s", got, want)
	}
}

func theFake(t *testing.T, change func(*settings.Settings)) *fake.Client {
	t.Helper()
	tokens, err := fake.LoadTokens(fake.TokensFile)
	if err != nil {
		t.Fatal(err)
	}
	s := settings.Default()
	if change != nil {
		change(&s)
	}
	return fake.New(s, tokens, nil)
}

func serve(handler http.Handler, method, path, body string) *httptest.ResponseRecorder {
	request := httptest.NewRequestWithContext(context.Background(), method, path, strings.NewReader(body))
	request.Header.Set("Content-Type", "application/json")
	recorder := httptest.NewRecorder()
	handler.ServeHTTP(recorder, request)
	return recorder
}

func assertStatus(t *testing.T, response *httptest.ResponseRecorder, want int) {
	t.Helper()
	if response.Code != want {
		t.Errorf("got %d, want %d: %s", response.Code, want, response.Body)
	}
}

// asking is a one-message request with these parameters.
func asking(parameters string) string {
	return `{"messages": [{"role": "user", "content": "Hi"}], "parameters": ` + parameters + `}`
}

// stub is a client whose answers the test sets.
type stub struct {
	notReady   bool
	err        error
	parameters llm.Parameters
	// When set, the stream waits for it to close before its first part.
	release chan struct{}
}

func (s *stub) Complete(_ context.Context, _ []llm.Message, parameters llm.Parameters) (llm.Completion, error) {
	s.parameters = parameters
	return llm.Completion{Content: "A", Model: "stub"}, s.err
}

func (s *stub) Stream(ctx context.Context, _ []llm.Message, _ llm.Parameters) iter.Seq2[llm.StreamPart, error] {
	return func(yield func(llm.StreamPart, error) bool) {
		if s.release != nil {
			select {
			case <-s.release:
			case <-ctx.Done():
				return
			}
		}
		if s.err != nil {
			yield(nil, s.err)
			return
		}
		if yield(llm.ContentDelta{Text: "A"}, nil) {
			yield(llm.StreamEnd{Model: "stub"}, nil)
		}
	}
}

func (s *stub) Ready(context.Context) bool { return !s.notReady }

func (s *stub) Close() error { return nil }

func liveness(t *testing.T, newHandler func(llm.Client) http.Handler) {
	response := serve(newHandler(theFake(t, nil)), http.MethodGet, "/api/health", "")

	assertStatus(t, response, http.StatusOK)
	assertJSON(t, response.Body.String(), `{"status": "ok"}`)
}

func readiness(t *testing.T, newHandler func(llm.Client) http.Handler) {
	response := serve(newHandler(theFake(t, nil)), http.MethodGet, "/api/health/ready", "")

	assertStatus(t, response, http.StatusOK)
	assertJSON(t, response.Body.String(), `{"status": "ok", "checks": {"llm": "ok"}}`)
}

func readinessUnavailable(t *testing.T, newHandler func(llm.Client) http.Handler) {
	response := serve(newHandler(&stub{notReady: true}), http.MethodGet, "/api/health/ready", "")

	assertStatus(t, response, http.StatusServiceUnavailable)
	assertJSON(t, response.Body.String(), `{"status": "unavailable", "checks": {"llm": "unavailable"}}`)
}

func wholeAnswer(t *testing.T, newHandler func(llm.Client) http.Handler) {
	response := serve(newHandler(theFake(t, nil)), http.MethodPost, "/api/chat", Question)

	assertStatus(t, response, http.StatusOK)
	if got := response.Header().Get("Content-Type"); !strings.HasPrefix(got, "application/json") {
		t.Errorf("got Content-Type %q, want application/json", got)
	}
	assertJSON(t, response.Body.String(), Completion)
}

func stream(t *testing.T, newHandler func(llm.Client) http.Handler) {
	response := serve(newHandler(theFake(t, nil)), http.MethodPost, "/api/chat/stream", Question)

	assertStatus(t, response, http.StatusOK)
	if got := response.Header().Get("Content-Type"); !strings.HasPrefix(got, "text/event-stream") {
		t.Errorf("got Content-Type %q, want text/event-stream", got)
	}
	if got := response.Header().Get("Cache-Control"); got != "no-cache" {
		t.Errorf("got Cache-Control %q, want no-cache", got)
	}
	want := []Event{
		{"token", map[string]any{"text": "A"}},
		{"token", map[string]any{"text": " backend"}},
		{"token", map[string]any{"text": " in"}},
		{"token", map[string]any{"text": " front"}},
		{"token", map[string]any{"text": " of"}},
		{"done", parseJSON(t, Done)},
	}
	if got := Events(t, response.Body.String()); !reflect.DeepEqual(got, want) {
		t.Errorf("got %v, want %v", got, want)
	}
}

func invalidBody(t *testing.T, newHandler func(llm.Client) http.Handler) {
	bodies := map[string]string{
		"not JSON":           `{"messages": [`,
		"no body":            ``,
		"no messages":        `{}`,
		"empty messages":     `{"messages": []}`,
		"null messages":      `{"messages": null}`,
		"an unknown role":    `{"messages": [{"role": "tool", "content": "x"}]}`,
		"no role":            `{"messages": [{"content": "x"}]}`,
		"empty content":      `{"messages": [{"role": "user", "content": ""}]}`,
		"no content":         `{"messages": [{"role": "user"}]}`,
		"a number content":   `{"messages": [{"role": "user", "content": 1}]}`,
		"content parts":      `{"messages": [{"role": "user", "content": [{"type": "text", "text": "x"}]}]}`,
		"a reserved key":     asking(`{"stream": true}`),
		"parameters as list": asking(`[1]`),
		"null parameters":    asking(`null`),
	}
	handler := newHandler(theFake(t, nil))
	for name, body := range bodies {
		for _, path := range []string{"/api/chat", "/api/chat/stream"} {
			t.Run(name+" to "+path, func(t *testing.T) {
				response := serve(handler, http.MethodPost, path, body)

				assertStatus(t, response, http.StatusUnprocessableEntity)
				if _, ok := parseJSON(t, response.Body.String()).(map[string]any)["detail"]; !ok {
					t.Errorf("got %s, want a detail", response.Body)
				}
			})
		}
	}
}

func otherFields(t *testing.T, newHandler func(llm.Client) http.Handler) {
	body := `{"messages": [{"role": "user", "content": "Hi", "name": "x"}], "other": 1}`

	response := serve(newHandler(theFake(t, nil)), http.MethodPost, "/api/chat", body)

	assertStatus(t, response, http.StatusOK)
}

func upstreamFailure(t *testing.T, newHandler func(llm.Client) http.Handler) {
	handler := newHandler(theFake(t, nil))
	for _, status := range llm.ServiceStatuses {
		t.Run(strconv.Itoa(status), func(t *testing.T) {
			body := asking(`{"fake_error": {"status": ` + strconv.Itoa(status) + `}}`)

			response := serve(handler, http.MethodPost, "/api/chat", body)

			assertStatus(t, response, status)
			if _, ok := parseJSON(t, response.Body.String()).(map[string]any)["detail"].(string); !ok {
				t.Errorf("got %s, want a detail string", response.Body)
			}
		})
	}
}

func streamFailure(t *testing.T, newHandler func(llm.Client) http.Handler) {
	body := asking(`{"fake_error": {"status": 504, "after_tokens": 2}}`)

	response := serve(newHandler(theFake(t, nil)), http.MethodPost, "/api/chat/stream", body)

	assertStatus(t, response, http.StatusOK)
	events := Events(t, response.Body.String())
	var names []string
	for _, event := range events {
		names = append(names, event.Name)
	}
	if want := []string{"token", "token", "error"}; !reflect.DeepEqual(names, want) {
		t.Fatalf("got %v, want %v", names, want)
	}
	if got := events[2].Data.(map[string]any)["status"]; got != 504.0 {
		t.Errorf("got status %v, want 504", got)
	}
}

func malformedFakeError(t *testing.T, newHandler func(llm.Client) http.Handler) {
	handler := newHandler(theFake(t, nil))
	body := asking(`{"fake_error": "soon"}`)

	whole := serve(handler, http.MethodPost, "/api/chat", body)
	streamed := serve(handler, http.MethodPost, "/api/chat/stream", body)

	assertStatus(t, whole, http.StatusBadGateway)
	detail := parseJSON(t, whole.Body.String()).(map[string]any)["detail"]
	want := []Event{{"error", map[string]any{"status": 502.0, "detail": detail}}}
	if got := Events(t, streamed.Body.String()); !reflect.DeepEqual(got, want) {
		t.Errorf("got %v, want %v", got, want)
	}
}

func parametersAsGiven(t *testing.T, newHandler func(llm.Client) http.Handler) {
	client := &stub{}
	body := asking(`{"max_tokens": 1, "temperature": 0.7, "nested": {"a": [1, null]}}`)

	response := serve(newHandler(client), http.MethodPost, "/api/chat", body)

	assertStatus(t, response, http.StatusOK)
	want := llm.Parameters{
		"max_tokens":  json.Number("1"),
		"temperature": json.Number("0.7"),
		"nested":      map[string]any{"a": []any{json.Number("1"), nil}},
	}
	if !reflect.DeepEqual(client.parameters, want) {
		t.Errorf("got %#v, want %#v", client.parameters, want)
	}
}

func unexpectedError(t *testing.T, newHandler func(llm.Client) http.Handler) {
	handler := newHandler(&stub{err: errors.New("a bug")})

	whole := serve(handler, http.MethodPost, "/api/chat", asking(`{}`))
	streamed := serve(handler, http.MethodPost, "/api/chat/stream", asking(`{}`))

	assertStatus(t, whole, http.StatusInternalServerError)
	if events := Events(t, streamed.Body.String()); len(events) != 0 {
		t.Errorf("got %v, want the stream to end with no event", events)
	}
}

func headersFirst(t *testing.T, newHandler func(llm.Client) http.Handler) {
	client := &stub{release: make(chan struct{})}
	server := httptest.NewServer(newHandler(client))
	defer server.Close()

	response := post(t, http.DefaultClient, server.URL+"/api/chat/stream", asking(`{}`))
	defer func() { _ = response.Body.Close() }()
	close(client.release)

	if response.StatusCode != http.StatusOK {
		t.Errorf("got %d, want 200 before the first token", response.StatusCode)
	}
	body, err := io.ReadAll(response.Body)
	if err != nil {
		t.Fatal(err)
	}
	if events := Events(t, string(body)); len(events) != 2 {
		t.Errorf("got %v, want a token and done once released", events)
	}
}

func post(t *testing.T, client *http.Client, url, body string) *http.Response {
	t.Helper()
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	t.Cleanup(cancel)
	request, err := http.NewRequestWithContext(ctx, http.MethodPost, url, strings.NewReader(body))
	if err != nil {
		t.Fatal(err)
	}
	request.Header.Set("Content-Type", "application/json")
	response, err := client.Do(request)
	if err != nil {
		t.Fatal(err)
	}
	return response
}

// watched is the fake, counting the tokens it makes, and noting when its stream ends.
type watched struct {
	*fake.Client
	made  atomic.Int64
	ended chan struct{}
}

func (w *watched) Stream(
	ctx context.Context, messages []llm.Message, parameters llm.Parameters,
) iter.Seq2[llm.StreamPart, error] {
	parts := w.Client.Stream(ctx, messages, parameters)
	return func(yield func(llm.StreamPart, error) bool) {
		defer close(w.ended)
		for part, err := range parts {
			if err == nil {
				w.made.Add(1)
			}
			if !yield(part, err) {
				return
			}
		}
	}
}

// clientLeaves runs over a real socket: the stream stops soon after the client leaves.
func clientLeaves(t *testing.T, newHandler func(llm.Client) http.Handler) {
	client := &watched{
		Client: theFake(t, func(s *settings.Settings) { s.FakeTokenGapMS, s.FakeAnswerTokens = 20, 1000 }),
		ended:  make(chan struct{}),
	}
	server := httptest.NewServer(newHandler(client))
	defer server.Close()
	// A client that closes its connection when it leaves, as the contract's is. Go's own client
	// otherwise reads a body closed early for up to 50 ms more, to reuse its connection
	// (net/http's maxPostCloseReadTime, in transport.go).
	leaving := &http.Client{Transport: &http.Transport{DisableKeepAlives: true}}

	response := post(t, leaving, server.URL+"/api/chat/stream", asking(`{}`))
	lines := bufio.NewScanner(response.Body)
	for lines.Scan() && !strings.HasSuffix(lines.Text(), `{"text":" backend"}`) {
		continue
	}
	_ = response.Body.Close()
	leftAt := client.made.Load()

	select {
	case <-client.ended:
	case <-time.After(time.Second):
		t.Fatal("the fake still streams a second after the client left")
	}
	if more := client.made.Load() - leftAt; more > 1 {
		t.Errorf("the fake made %d more tokens after the client left, want at most 1", more)
	}
}
