package upstream_test

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/http/httptest"
	"reflect"
	"strings"
	"testing"
	"time"

	"github.com/fkuhne/api-langs-bench/backends/go/internal/llm"
	"github.com/fkuhne/api-langs-bench/backends/go/internal/settings"
	"github.com/fkuhne/api-langs-bench/backends/go/internal/upstream"
)

var question = []llm.Message{{Role: llm.RoleUser, Content: "Hi"}}

const usage = `{"completion_tokens":2,"prompt_tokens":1,"total_tokens":3,"prompt_tokens_details":{"cached_tokens":0}}`

// chunk is one chunk of a stream, shaped as llama.cpp's (docs/fake-server.md), as a data line.
func chunk(delta string) string {
	return `data: {"choices":[{"finish_reason":null,"index":0,"delta":` + delta + `}],"model":"fake-server"}` + "\n\n"
}

const finish = `data: {"choices":[{"finish_reason":"stop","index":0,"delta":{}}],"model":"fake-server"}` + "\n\n"

var stream = chunk(`{"role":"assistant","content":null}`) +
	chunk(`{"reasoning_content":"Hm"}`) +
	chunk(`{"content":"A"}`) +
	chunk(`{"content":" backend"}`) +
	finish +
	`data: {"choices":[],"model":"fake-server","usage":` + usage + "}\n\n" +
	"data: [DONE]\n\n"

// served is a test upstream, the client for it, and the requests it got.
type served struct {
	client *upstream.Client
	bodies []map[string]any
	header http.Header
	path   string
}

// serve starts an upstream answered by handler, and returns a client for it.
func serve(t *testing.T, handler http.HandlerFunc, change func(*settings.Settings)) *served {
	t.Helper()
	s := &served{}
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		var body map[string]any
		_ = json.NewDecoder(r.Body).Decode(&body)
		s.bodies, s.header, s.path = append(s.bodies, body), r.Header, r.URL.Path
		handler(w, r)
	}))
	t.Cleanup(server.Close)
	config := settings.Default()
	config.LLMBaseURL = server.URL + "/v1/"
	if change != nil {
		change(&config)
	}
	s.client = upstream.New(config)
	t.Cleanup(func() { _ = s.client.Close() })
	return s
}

func answers(status int, body string) http.HandlerFunc {
	return func(w http.ResponseWriter, _ *http.Request) {
		w.WriteHeader(status)
		_, _ = io.WriteString(w, body)
	}
}

func timeout(d time.Duration) func(*settings.Settings) {
	return func(s *settings.Settings) { s.LLMTimeout = d }
}

// parts reads a stream to its end, or to the error that ends it.
func parts(ctx context.Context, client *upstream.Client, parameters llm.Parameters) ([]llm.StreamPart, error) {
	var got []llm.StreamPart
	for part, err := range client.Stream(ctx, question, parameters) {
		if err != nil {
			return got, err
		}
		got = append(got, part)
	}
	return got, nil
}

func ptr[T any](value T) *T { return &value }

func status(t *testing.T, err error) int {
	t.Helper()
	var service *llm.ServiceError
	if !errors.As(err, &service) {
		t.Fatalf("got %v, want a ServiceError", err)
	}
	return service.Status
}

func TestAWholeAnswerIsAskedForAndRead(t *testing.T) {
	answer := `{"choices":[{"finish_reason":"length","index":0,"message":{"role":"assistant","content":"A backend","reasoning_content":"Hm"}}],"model":"fake-server","usage":` + usage + `}`
	s := serve(t, answers(http.StatusOK, answer), func(c *settings.Settings) { c.LLMAPIKey = "secret" })
	var parameters llm.Parameters
	if err := json.Unmarshal([]byte(`{"max_tokens":5,"seed":1.50}`), &parameters); err != nil {
		t.Fatal(err)
	}

	got, err := s.client.Complete(context.Background(), question, parameters)
	if err != nil {
		t.Fatal(err)
	}

	if s.path != "/v1/chat/completions" || s.header.Get("Authorization") != "Bearer secret" ||
		s.header.Get("Content-Type") != "application/json" {
		t.Errorf("asked %s with %v", s.path, s.header)
	}
	sent := map[string]any{
		"max_tokens": 5.0, "seed": 1.5, "model": "local",
		"messages": []any{map[string]any{"role": "user", "content": "Hi"}},
	}
	if !reflect.DeepEqual(s.bodies[0], sent) {
		t.Errorf("sent %v, want %v", s.bodies[0], sent)
	}
	want := llm.Completion{
		Content: "A backend", Reasoning: ptr("Hm"), Model: "fake-server", FinishReason: ptr("length"),
		Usage: &llm.Usage{PromptTokens: 1, CompletionTokens: 2, TotalTokens: 3},
	}
	if !reflect.DeepEqual(got, want) {
		t.Errorf("got %+v, want %+v", got, want)
	}
}

func TestAWholeAnswerWithLittleInIt(t *testing.T) {
	answer := `{"choices":[{"finish_reason":"","message":{"role":"assistant","content":null}}],"usage":{"prompt_tokens":1}}`
	s := serve(t, answers(http.StatusOK, answer), func(c *settings.Settings) { c.LLMModel = "mine" })

	got, err := s.client.Complete(context.Background(), question, nil)
	if err != nil {
		t.Fatal(err)
	}

	if want := (llm.Completion{Model: "mine"}); !reflect.DeepEqual(got, want) {
		t.Errorf("got %+v, want %+v", got, want)
	}
}

func TestAStreamIsOnePartForEachPieceThenTheEnd(t *testing.T) {
	s := serve(t, answers(http.StatusOK, stream), nil)

	got, err := parts(context.Background(), s.client, llm.Parameters{"max_tokens": json.Number("2")})
	if err != nil {
		t.Fatal(err)
	}

	sent := s.bodies[0]
	if sent["stream"] != true || sent["max_tokens"] != 2.0 || sent["model"] != "local" ||
		!reflect.DeepEqual(sent["stream_options"], map[string]any{"include_usage": true}) {
		t.Errorf("sent %v", sent)
	}
	want := []llm.StreamPart{
		llm.ReasoningDelta{Text: "Hm"},
		llm.ContentDelta{Text: "A"},
		llm.ContentDelta{Text: " backend"},
		llm.StreamEnd{
			Model: "fake-server", FinishReason: ptr("stop"),
			Usage: &llm.Usage{PromptTokens: 1, CompletionTokens: 2, TotalTokens: 3},
		},
	}
	if !reflect.DeepEqual(got, want) {
		t.Errorf("got %+v, want %+v", got, want)
	}
}

func TestAStreamIsReadAsOtherServersWriteIt(t *testing.T) {
	// Ollama's name for the reasoning; a comment; no space after the colon; lines that end
	// with a carriage return; a chunk with both texts; an empty text; no delta; another
	// field; a usage short of a count; and no [DONE] before the end.
	body := ": ping\r\n\r\n" +
		`data:{"choices":[{"delta":{"reasoning":"Hm","content":"A"}}]}` + "\r\n\r\n" +
		chunk(`{"content":""}`) +
		chunk(`null`) +
		"event: other\n\n" +
		`data: {"choices":[],"usage":{"prompt_tokens":1,"total_tokens":3}}` + "\n\n"
	s := serve(t, answers(http.StatusOK, body), func(c *settings.Settings) { c.LLMModel = "mine" })

	got, err := parts(context.Background(), s.client, nil)
	if err != nil {
		t.Fatal(err)
	}

	want := []llm.StreamPart{
		llm.ReasoningDelta{Text: "Hm"},
		llm.ContentDelta{Text: "A"},
		llm.StreamEnd{Model: "fake-server"},
	}
	if !reflect.DeepEqual(got, want) {
		t.Errorf("got %+v, want %+v", got, want)
	}
}

func TestWhatFollowsDoneIsntRead(t *testing.T) {
	s := serve(t, answers(http.StatusOK, stream+chunk(`{"content":"late"}`)), nil)

	got, err := parts(context.Background(), s.client, nil)

	if err != nil || len(got) != 4 {
		t.Errorf("got %d parts and %v, want 4 and no error", len(got), err)
	}
}

func TestAFailedAnswerBecomesTheContractsError(t *testing.T) {
	cases := []struct {
		status, answered int
		detail           string
	}{
		{429, 429, "The LLM endpoint is rate-limiting requests."},
		{400, 502, "The LLM endpoint refused the request with status 400: no"},
		{404, 502, "The LLM endpoint refused the request with status 404: no"},
		{500, 502, "The LLM endpoint refused the request with status 500: no"},
		{502, 503, "The LLM endpoint failed with status 502: no"},
		{503, 503, "The LLM endpoint failed with status 503: no"},
		{504, 503, "The LLM endpoint failed with status 504: no"},
		{529, 503, "The LLM endpoint failed with status 529: no"},
	}
	for _, c := range cases {
		for _, streamed := range []bool{false, true} {
			t.Run(fmt.Sprintf("%d, streamed %t", c.status, streamed), func(t *testing.T) {
				body := fmt.Sprintf(`{"error":{"code":%d,"message":" no ","type":"some_error"}}`, c.status)
				s := serve(t, answers(c.status, body), nil)

				var err error
				if streamed {
					_, err = parts(context.Background(), s.client, nil)
				} else {
					_, err = s.client.Complete(context.Background(), question, nil)
				}

				if status(t, err) != c.answered || err.Error() != c.detail {
					t.Errorf("got %d: %v, want %d: %s", status(t, err), err, c.answered, c.detail)
				}
			})
		}
	}
}

// silent holds a request without answering, until its client leaves.
func silent(_ http.ResponseWriter, r *http.Request) { <-r.Context().Done() }

// tokenThen sends a stream's first token, then does what follows.
func tokenThen(follows http.HandlerFunc) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		_, _ = io.WriteString(w, chunk(`{"content":"A"}`))
		_ = http.NewResponseController(w).Flush()
		follows(w, r)
	}
}

// hangUp closes the connection in the middle of an answer.
func hangUp(w http.ResponseWriter, _ *http.Request) {
	connection, _, err := http.NewResponseController(w).Hijack()
	if err == nil {
		_ = connection.Close()
	}
}

func TestNoAnswerInTimeIsATimeout(t *testing.T) {
	for _, streamed := range []bool{false, true} {
		t.Run(fmt.Sprintf("streamed %t", streamed), func(t *testing.T) {
			s := serve(t, silent, timeout(50*time.Millisecond))

			var err error
			if streamed {
				_, err = parts(context.Background(), s.client, nil)
			} else {
				_, err = s.client.Complete(context.Background(), question, nil)
			}

			if status(t, err) != http.StatusGatewayTimeout {
				t.Errorf("got %v, want a 504", err)
			}
		})
	}
}

func TestAnAnswerThatStopsHalfwayFails(t *testing.T) {
	cases := map[string]struct {
		follows  http.HandlerFunc
		answered int
	}{
		"silence":  {silent, http.StatusGatewayTimeout},
		"a hangup": {hangUp, http.StatusServiceUnavailable},
	}
	for name, c := range cases {
		t.Run(name+", streamed", func(t *testing.T) {
			s := serve(t, tokenThen(c.follows), timeout(50*time.Millisecond))

			got, err := parts(context.Background(), s.client, nil)

			if len(got) != 1 || status(t, err) != c.answered {
				t.Errorf("got %d parts and %v, want 1 and a %d", len(got), err, c.answered)
			}
		})
		t.Run(name+", whole", func(t *testing.T) {
			s := serve(t, tokenThen(c.follows), timeout(50*time.Millisecond))

			_, err := s.client.Complete(context.Background(), question, nil)

			if status(t, err) != c.answered {
				t.Errorf("got %v, want a %d", err, c.answered)
			}
		})
	}
}

func TestAnUpstreamThatCantBeReachedIsUnavailable(t *testing.T) {
	config := settings.Default()
	config.LLMBaseURL = "http://127.0.0.1:1/v1"
	client := upstream.New(config)

	_, whole := client.Complete(context.Background(), question, nil)
	_, streamed := parts(context.Background(), client, nil)

	if status(t, whole) != http.StatusServiceUnavailable || status(t, streamed) != http.StatusServiceUnavailable {
		t.Errorf("got %v and %v, want two 503s", whole, streamed)
	}
	if client.Ready(context.Background()) {
		t.Error("got ready")
	}
}

func TestAStreamLongerThanTheTimeoutIsntCut(t *testing.T) {
	// Ten tokens, 20 ms apart: 200 ms in all, against a timeout of 100 ms for each wait.
	slow := func(w http.ResponseWriter, _ *http.Request) {
		flusher := http.NewResponseController(w)
		for range 10 {
			time.Sleep(20 * time.Millisecond)
			_, _ = io.WriteString(w, chunk(`{"content":"A"}`))
			_ = flusher.Flush()
		}
	}
	s := serve(t, slow, timeout(100*time.Millisecond))

	got, err := parts(context.Background(), s.client, nil)

	if err != nil || len(got) != 11 {
		t.Errorf("got %d parts and %v, want 10 tokens, the end, and no error", len(got), err)
	}
}

func TestAnErrorInsideAStreamIsMappedByItsCode(t *testing.T) {
	cases := map[string]struct {
		object   string
		answered int
		detail   string
	}{
		"rate-limited":       {`{"code":429,"message":"slow down"}`, 429, "The LLM endpoint is rate-limiting requests."},
		"down":               {`{"code":503,"message":"loading"}`, 503, "The LLM endpoint failed with status 503: loading"},
		"refused":            {`{"code":400,"message":"no"}`, 502, "The LLM endpoint refused the request with status 400: no"},
		"a code as a string": {`{"code":"503","message":"no"}`, 502, "The LLM endpoint failed inside its stream: no"},
		"a code as a truth":  {`{"code":true,"message":"no"}`, 502, "The LLM endpoint failed inside its stream: no"},
		"a fraction":         {`{"code":503.0,"message":"no"}`, 502, "The LLM endpoint failed inside its stream: no"},
		"no code":            {`{"message":"no"}`, 502, "The LLM endpoint failed inside its stream: no"},
		"just a text":        {`"no"`, 502, "The LLM endpoint failed inside its stream: no"},
		"nothing":            {`null`, 502, "The LLM endpoint failed inside its stream."},
	}
	for name, c := range cases {
		t.Run(name, func(t *testing.T) {
			body := chunk(`{"content":"A"}`) + `data: {"error":` + c.object + "}\n\n"
			s := serve(t, answers(http.StatusOK, body), nil)

			got, err := parts(context.Background(), s.client, nil)

			if len(got) != 1 || status(t, err) != c.answered || err.Error() != c.detail {
				t.Errorf("got %d parts and %d: %v, want 1 and %d: %s", len(got), status(t, err), err, c.answered, c.detail)
			}
		})
	}
}

func TestAnAnswerThatCantBeReadIsARefusal(t *testing.T) {
	wholes := []string{"not JSON", "[]", `{"choices":[]}`, `{"choices":[{"message":"text"}]}`, `{"choices":[{}]}`}
	for _, body := range wholes {
		t.Run("whole: "+body, func(t *testing.T) {
			s := serve(t, answers(http.StatusOK, body), nil)

			if _, err := s.client.Complete(context.Background(), question, nil); status(t, err) != http.StatusBadGateway {
				t.Errorf("got %v, want a 502", err)
			}
		})
	}
	chunks := []string{"not JSON", "[]", `"text"`, strings.Repeat("x", 17<<20)}
	for _, data := range chunks {
		t.Run(fmt.Sprintf("a chunk of %d bytes", len(data)), func(t *testing.T) {
			s := serve(t, answers(http.StatusOK, "data: "+data+"\n\n"), nil)

			if _, err := parts(context.Background(), s.client, nil); status(t, err) != http.StatusBadGateway {
				t.Errorf("got %v, want a 502", err)
			}
		})
	}
}

func TestAnErrorsReasonIsTheUpstreamsOwn(t *testing.T) {
	cases := map[string]string{
		`{"error":{"message":"the reason"}}`:                       ": the reason",
		`{"error":"the reason"}`:                                   ": the reason",
		`{"detail":"the reason"}`:                                  ": the reason",
		`{"error":{"message":"` + strings.Repeat("é", 300) + `"}}`: ": " + strings.Repeat("é", 200),
		`{"error":{"message":"  "}}`:                               ".",
		`{"error":{"code":500}}`:                                   ".",
		`{"error":null,"detail":"hidden"}`:                         ".",
		`["a list"]`:                                               ".",
		`not JSON`:                                                 ".",
		``:                                                         ".",
	}
	for body, reason := range cases {
		s := serve(t, answers(http.StatusNotFound, body), nil)

		_, err := s.client.Complete(context.Background(), question, nil)

		if want := "The LLM endpoint refused the request with status 404" + reason; err.Error() != want {
			t.Errorf("%s: got %q, want %q", body, err, want)
		}
	}
}

func TestReadinessIsACompletionOfOneToken(t *testing.T) {
	for code, ready := range map[int]bool{200: true, 400: true, 429: false, 503: false} {
		s := serve(t, answers(code, `{}`), nil)

		if got := s.client.Ready(context.Background()); got != ready {
			t.Errorf("%d: got ready %t, want %t", code, got, ready)
		}
		if sent := s.bodies[0]; sent["max_tokens"] != 1.0 || sent["model"] != "local" {
			t.Errorf("%d: sent %v", code, sent)
		}
	}
}

func TestReadinessWaitsNoLongerThanTheTimeout(t *testing.T) {
	s := serve(t, silent, timeout(50*time.Millisecond))
	start := time.Now()

	if s.client.Ready(context.Background()) {
		t.Error("got ready")
	}
	if waited := time.Since(start); waited > 2*time.Second {
		t.Errorf("waited %v, want about 50 ms", waited)
	}
}

func TestACallerThatLeavesGetsItsOwnErrorAndTheUpstreamSeesIt(t *testing.T) {
	left := make(chan struct{})
	s := serve(t, tokenThen(func(_ http.ResponseWriter, r *http.Request) {
		<-r.Context().Done()
		close(left)
	}), nil)
	ctx, leave := context.WithCancel(context.Background())
	defer leave()
	var got []llm.StreamPart
	var failure error

	for part, err := range s.client.Stream(ctx, question, nil) {
		if err != nil {
			failure = err
			break
		}
		got = append(got, part)
		leave()
	}

	if len(got) != 1 || !errors.Is(failure, context.Canceled) {
		t.Errorf("got %d parts and %v, want 1 and context.Canceled", len(got), failure)
	}
	select {
	case <-left:
	case <-time.After(5 * time.Second):
		t.Error("the upstream's connection stayed open")
	}
}

func TestStoppingAStreamEarlyClosesTheUpstreamsConnectionAtOnce(t *testing.T) {
	left := make(chan time.Time, 1)
	s := serve(t, tokenThen(func(_ http.ResponseWriter, r *http.Request) {
		<-r.Context().Done()
		left <- time.Now()
	}), nil)

	var stopped time.Time
	for _, err := range s.client.Stream(context.Background(), question, nil) {
		if err != nil {
			t.Fatal(err)
		}
		stopped = time.Now()
		break
	}

	select {
	case at := <-left:
		// Without ending the request first, Go's client reads on for up to 50 ms.
		if late := at.Sub(stopped); late > 40*time.Millisecond {
			t.Errorf("the upstream saw it %v later", late)
		}
	case <-time.After(5 * time.Second):
		t.Error("the upstream's connection stayed open")
	}
}

func TestACallerThatHasLeftGetsItsOwnErrorFromAWholeAnswer(t *testing.T) {
	s := serve(t, silent, nil)
	ctx, leave := context.WithCancel(context.Background())
	leave()

	if _, err := s.client.Complete(ctx, question, nil); !errors.Is(err, context.Canceled) {
		t.Errorf("got %v, want context.Canceled", err)
	}
}
