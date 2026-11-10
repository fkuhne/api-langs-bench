package chat_test

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"os"
	"slices"
	"strings"
	"sync"
	"testing"
	"testing/iotest"
	"time"

	"github.com/fkuhne/api-langs-bench/fake-server/internal/chat"
	"github.com/fkuhne/api-langs-bench/fake-server/internal/settings"
	"github.com/fkuhne/api-langs-bench/fake-server/internal/tokens"
)

// question has seven words, so seven prompt tokens.
const question = `"messages":[{"role":"user","content":"In one sentence, what is an LLM?"}]`

var epoch = time.Unix(1_800_000_000, 0)

// manualClock is a clock the tests drive: a wait moves it on at once, and is recorded.
type manualClock struct {
	mu    sync.Mutex
	now   time.Time
	waits []time.Duration
	// onWait, if set, is called before each wait with its number, from 0.
	onWait func(number int)
}

func (c *manualClock) Now() time.Time {
	c.mu.Lock()
	defer c.mu.Unlock()
	return c.now
}

func (c *manualClock) SleepUntil(ctx context.Context, deadline time.Time) error {
	c.mu.Lock()
	number := len(c.waits)
	c.waits = append(c.waits, deadline.Sub(epoch))
	c.mu.Unlock()
	if c.onWait != nil {
		c.onWait(number)
	}
	if err := ctx.Err(); err != nil {
		return err
	}
	c.mu.Lock()
	defer c.mu.Unlock()
	if deadline.After(c.now) {
		c.now = deadline
	}
	return nil
}

func (c *manualClock) waited() []time.Duration {
	c.mu.Lock()
	defer c.mu.Unlock()
	return slices.Clone(c.waits)
}

// fixture is a fake server on a manual clock, with what it logged.
type fixture struct {
	handler http.Handler
	clock   *manualClock
	log     *bytes.Buffer
}

func serverWith(t *testing.T, s settings.Settings) fixture {
	t.Helper()
	loaded, err := tokens.Load(tokens.File)
	if err != nil {
		t.Fatal(err)
	}
	return serverOf(s, loaded)
}

func serverOf(s settings.Settings, loaded []string) fixture {
	clock := &manualClock{now: epoch}
	log := &bytes.Buffer{}
	server := chat.New(s, loaded, clock, slog.New(slog.NewJSONHandler(log, nil)))
	return fixture{handler: server.Handler(), clock: clock, log: log}
}

func paced(answer int) settings.Settings {
	return settings.Settings{AnswerTokens: answer, FirstTokenMS: 100, TokenGapMS: 20}
}

func (f fixture) post(ctx context.Context, body string) *httptest.ResponseRecorder {
	request := httptest.NewRequestWithContext(ctx, http.MethodPost, "/v1/chat/completions", strings.NewReader(body))
	recorder := httptest.NewRecorder()
	f.handler.ServeHTTP(recorder, request)
	return recorder
}

func (f fixture) ask(body string) *httptest.ResponseRecorder {
	return f.post(context.Background(), body)
}

// chunk is what a client reads of a stream's chunk.
type chunk struct {
	Choices []struct {
		FinishReason *string `json:"finish_reason"`
		Delta        struct {
			Role             *string `json:"role"`
			Content          *string `json:"content"`
			ReasoningContent *string `json:"reasoning_content"`
		} `json:"delta"`
	} `json:"choices"`
	ID    string `json:"id"`
	Model string `json:"model"`
	Usage *struct {
		CompletionTokens int `json:"completion_tokens"`
		PromptTokens     int `json:"prompt_tokens"`
		TotalTokens      int `json:"total_tokens"`
	} `json:"usage"`
	Timings *struct {
		PredictedN  int     `json:"predicted_n"`
		PredictedMS float64 `json:"predicted_ms"`
		PromptMS    float64 `json:"prompt_ms"`
	} `json:"timings"`
	Error *struct {
		Code int    `json:"code"`
		Type string `json:"type"`
	} `json:"error"`
}

// events splits a stream's body into its events' data.
func events(t *testing.T, body string) []string {
	t.Helper()
	if body == "" {
		return nil
	}
	if !strings.HasSuffix(body, "\n\n") {
		t.Fatalf("the stream doesn't end with a blank line: %q", body)
	}
	var data []string
	for event := range strings.SplitSeq(strings.TrimSuffix(body, "\n\n"), "\n\n") {
		text, found := strings.CutPrefix(event, "data: ")
		if !found || strings.Contains(text, "\n") {
			t.Fatalf("not one data line: %q", event)
		}
		data = append(data, text)
	}
	return data
}

func parse(t *testing.T, data string) chunk {
	t.Helper()
	var parsed chunk
	if err := json.Unmarshal([]byte(data), &parsed); err != nil {
		t.Fatalf("%v in %q", err, data)
	}
	return parsed
}

// read returns a stream's contents and reasoning, token by token, and its finish reason.
func read(t *testing.T, data []string) (contents, reasoning []string, finish string) {
	t.Helper()
	for _, text := range data {
		if text == "[DONE]" {
			continue
		}
		parsed := parse(t, text)
		if len(parsed.Choices) == 0 {
			continue
		}
		choice := parsed.Choices[0]
		if choice.Delta.Content != nil {
			contents = append(contents, *choice.Delta.Content)
		}
		if choice.Delta.ReasoningContent != nil {
			reasoning = append(reasoning, *choice.Delta.ReasoningContent)
		}
		if choice.FinishReason != nil {
			finish = *choice.FinishReason
		}
	}
	return contents, reasoning, finish
}

func ms(values ...int) []time.Duration {
	durations := make([]time.Duration, len(values))
	for index, value := range values {
		durations[index] = time.Duration(value) * time.Millisecond
	}
	return durations
}

func TestAStreamIsARoleThenATokenAChunkThenTheEnd(t *testing.T) {
	f := serverWith(t, settings.Settings{AnswerTokens: 3})

	response := f.ask(`{` + question + `,"stream":true}`)

	if response.Code != http.StatusOK || response.Header().Get("Content-Type") != "text/event-stream" {
		t.Fatalf("got %d as %q", response.Code, response.Header().Get("Content-Type"))
	}
	data := events(t, response.Body.String())
	if len(data) != 6 || data[5] != "[DONE]" {
		t.Fatalf("got %d events, ending with %q", len(data), data[len(data)-1])
	}
	first := parse(t, data[0])
	if role := first.Choices[0].Delta.Role; role == nil || *role != "assistant" {
		t.Errorf("the first chunk's role is %v", role)
	}
	if first.Model != chat.Name || !strings.HasPrefix(first.ID, "chatcmpl-") || len(first.ID) != 41 {
		t.Errorf("got the model %q and the id %q", first.Model, first.ID)
	}
	contents, reasoning, finish := read(t, data)
	if want := []string{"A", " backend", " in"}; !slices.Equal(contents, want) {
		t.Errorf("got %q, want %q", contents, want)
	}
	if len(reasoning) != 0 || finish != "stop" {
		t.Errorf("got the reasoning %q and the finish reason %q", reasoning, finish)
	}
}

func TestTheUsageComesOnlyWhenAskedFor(t *testing.T) {
	f := serverWith(t, paced(3))

	data := events(t, f.ask(`{`+question+`,"stream":true,"stream_options":{"include_usage":true}}`).Body.String())

	if len(data) != 7 {
		t.Fatalf("got %d events, want 7", len(data))
	}
	last := parse(t, data[5])
	if len(last.Choices) != 0 || last.Usage == nil || last.Timings == nil {
		t.Fatalf("the chunk before [DONE] isn't the usage: %s", data[5])
	}
	if u := *last.Usage; u.PromptTokens != 7 || u.CompletionTokens != 3 || u.TotalTokens != 10 {
		t.Errorf("got %+v", u)
	}
	// The fake's own timetable: 100 ms to the first token, then two gaps of 20 ms.
	if timings := *last.Timings; timings.PredictedN != 3 || timings.PredictedMS != 40 || timings.PromptMS != 100 {
		t.Errorf("got %+v", timings)
	}
}

func TestMaxTokensCutsTheAnswerOnlyAsASmallerPositiveWholeNumber(t *testing.T) {
	cases := map[string]struct {
		maxTokens string
		tokens    int
		finish    string
	}{
		"smaller":       {"2", 2, "length"},
		"the length":    {"3", 3, "stop"},
		"larger":        {"99999999999999999999", 3, "stop"},
		"zero":          {"0", 3, "stop"},
		"negative":      {"-1", 3, "stop"},
		"very negative": {"-99999999999999999999", 3, "stop"},
		"a fraction":    {"2.0", 3, "stop"},
		"an exponent":   {"2e0", 3, "stop"},
		"a string":      {`"2"`, 3, "stop"},
		"true":          {"true", 3, "stop"},
		"null":          {"null", 3, "stop"},
	}
	for name, c := range cases {
		t.Run(name, func(t *testing.T) {
			f := serverWith(t, settings.Settings{AnswerTokens: 3})

			response := f.ask(`{` + question + `,"stream":true,"max_tokens":` + c.maxTokens + `}`)

			contents, _, finish := read(t, events(t, response.Body.String()))
			if len(contents) != c.tokens || finish != c.finish {
				t.Errorf("got %d tokens and %q, want %d and %q", len(contents), finish, c.tokens, c.finish)
			}
		})
	}
}

func TestTheReasoningComesFirstAndCountsAsCompletion(t *testing.T) {
	f := serverWith(t, settings.Settings{AnswerTokens: 2, ReasoningTokens: 2})

	data := events(t, f.ask(`{`+question+`,"stream":true,"stream_options":{"include_usage":true}}`).Body.String())

	contents, reasoning, _ := read(t, data)
	want := []string{"A", " backend"}
	if !slices.Equal(reasoning, want) || !slices.Equal(contents, want) {
		t.Errorf("got the reasoning %q and the answer %q, want %q twice", reasoning, contents, want)
	}
	// The reasoning's chunks come before the answer's.
	if second := parse(t, data[1]).Choices[0].Delta; second.ReasoningContent == nil || second.Content != nil {
		t.Errorf("the second chunk isn't reasoning: %s", data[1])
	}
	if usage := parse(t, data[len(data)-2]).Usage; usage == nil || usage.CompletionTokens != 4 {
		t.Errorf("got the usage %+v, want 4 completion tokens", usage)
	}
}

func TestEachTokenWaitsForItsOwnTime(t *testing.T) {
	f := serverWith(t, paced(3))

	f.ask(`{` + question + `,"stream":true}`)

	if want := ms(100, 120, 140); !slices.Equal(f.clock.waited(), want) {
		t.Errorf("waited until %v, want %v", f.clock.waited(), want)
	}
}

func TestTheTokensWrapAroundAndArentEscaped(t *testing.T) {
	f := serverOf(settings.Settings{AnswerTokens: 3}, []string{"<b>", ` "q" & `})

	stream := f.ask(`{"messages":[],"stream":true}`).Body.String()
	whole := f.ask(`{"messages":[]}`).Body.String()

	contents, _, _ := read(t, events(t, stream))
	if want := []string{"<b>", ` "q" & `, "<b>"}; !slices.Equal(contents, want) {
		t.Errorf("got %q, want %q", contents, want)
	}
	// As llama.cpp writes them: <, > and & as themselves.
	for _, body := range []string{stream, whole} {
		if !strings.Contains(body, `<b>`) || !strings.Contains(body, `\"q\" & `) {
			t.Errorf("the tokens are escaped in %s", body)
		}
	}
}

func TestAWholeAnswerComesAtTheLastTokensTime(t *testing.T) {
	f := serverWith(t, settings.Settings{AnswerTokens: 3, ReasoningTokens: 1, FirstTokenMS: 100, TokenGapMS: 20})

	response := f.ask(`{` + question + `,"max_tokens":2}`)

	if response.Code != http.StatusOK || response.Header().Get("Content-Type") != "application/json; charset=utf-8" {
		t.Fatalf("got %d as %q", response.Code, response.Header().Get("Content-Type"))
	}
	var body struct {
		Choices []struct {
			FinishReason string `json:"finish_reason"`
			Message      struct {
				Role             string `json:"role"`
				Content          string `json:"content"`
				ReasoningContent string `json:"reasoning_content"`
			} `json:"message"`
		} `json:"choices"`
		Model  string `json:"model"`
		Object string `json:"object"`
		Usage  struct {
			CompletionTokens int `json:"completion_tokens"`
			PromptTokens     int `json:"prompt_tokens"`
			TotalTokens      int `json:"total_tokens"`
		} `json:"usage"`
	}
	if err := json.Unmarshal(response.Body.Bytes(), &body); err != nil {
		t.Fatal(err)
	}
	choice := body.Choices[0]
	if choice.Message.Content != "A backend" || choice.Message.ReasoningContent != "A" ||
		choice.Message.Role != "assistant" || choice.FinishReason != "length" {
		t.Errorf("got %+v", choice)
	}
	if body.Model != chat.Name || body.Object != "chat.completion" {
		t.Errorf("got the model %q and the object %q", body.Model, body.Object)
	}
	if u := body.Usage; u.PromptTokens != 7 || u.CompletionTokens != 3 || u.TotalTokens != 10 {
		t.Errorf("got %+v", u)
	}
	// One reasoning token and two answer tokens: the last is due at 100 + 2 * 20 ms.
	if want := ms(140); !slices.Equal(f.clock.waited(), want) {
		t.Errorf("waited until %v, want %v", f.clock.waited(), want)
	}
}

// shape lists a JSON value's fields in order, nested ones as paths, each scalar with its kind:
// such as "choices[].delta.content:string".
func shape(t *testing.T, data string) []string {
	t.Helper()
	decoder := json.NewDecoder(strings.NewReader(data))
	var fields []string
	var walk func(path string)
	walk = func(path string) {
		token, err := decoder.Token()
		if err != nil {
			t.Fatalf("%v in %q", err, data)
		}
		switch value := token.(type) {
		case json.Delim:
			for decoder.More() {
				inner := path + "[]"
				if value == '{' {
					key, _ := decoder.Token()
					inner = strings.TrimPrefix(path+"."+key.(string), ".")
				}
				walk(inner)
			}
			_, _ = decoder.Token()
			if value == '{' {
				fields = append(fields, path+":object")
			}
		case string:
			fields = append(fields, path+":string")
		case float64:
			fields = append(fields, path+":number")
		case bool:
			fields = append(fields, path+":bool")
		default:
			fields = append(fields, path+":null")
		}
	}
	walk("")
	return fields
}

func fixtureFile(t *testing.T, name string) string {
	t.Helper()
	data, err := os.ReadFile("testdata/" + name) //nolint:gosec // G304: a test's own file.
	if err != nil {
		t.Fatal(err)
	}
	return string(data)
}

func TestAStreamHasLlamaCppsFieldsInItsOrder(t *testing.T) {
	// llama.cpp's own stream of four tokens, with the usage (docs/fake-server.md).
	theirs := events(t, fixtureFile(t, "llama-stream.txt"))
	f := serverWith(t, paced(4))

	ours := events(t, f.ask(`{`+question+`,"stream":true,"stream_options":{"include_usage":true}}`).Body.String())

	if len(ours) != len(theirs) {
		t.Fatalf("got %d events, llama.cpp sends %d", len(ours), len(theirs))
	}
	for index := range theirs {
		if theirs[index] == "[DONE]" {
			if ours[index] != "[DONE]" {
				t.Errorf("event %d: got %s, want [DONE]", index, ours[index])
			}
			continue
		}
		if got, want := shape(t, ours[index]), shape(t, theirs[index]); !slices.Equal(got, want) {
			t.Errorf("event %d:\n got %v\nwant %v", index, got, want)
		}
	}
}

func TestAWholeAnswerHasLlamaCppsFieldsInItsOrder(t *testing.T) {
	theirs := fixtureFile(t, "llama-whole.json")
	f := serverWith(t, paced(4))

	ours := f.ask(`{` + question + `}`).Body.String()

	if got, want := shape(t, ours), shape(t, theirs); !slices.Equal(got, want) {
		t.Errorf("\n got %v\nwant %v", got, want)
	}
}

// failures is how each of fake_error's statuses shows: the HTTP status, which is the error's
// code too, and its type.
var failures = map[string]struct {
	code int
	kind string
}{
	"429": {http.StatusTooManyRequests, "rate_limit_error"},
	"502": {http.StatusBadRequest, "invalid_request_error"},
	"503": {http.StatusServiceUnavailable, "unavailable_error"},
}

func TestBeforeTheFirstTokenAFakeErrorIsAPlainHTTPError(t *testing.T) {
	for status, want := range failures {
		for _, stream := range []string{"true", "false"} {
			t.Run(status+", stream "+stream, func(t *testing.T) {
				f := serverWith(t, paced(3))

				response := f.ask(`{` + question + `,"stream":` + stream + `,"fake_error":{"status":` + status + `}}`)

				if response.Code != want.code || response.Header().Get("Content-Type") != "application/json; charset=utf-8" {
					t.Fatalf("got %d as %q", response.Code, response.Header().Get("Content-Type"))
				}
				failed := parse(t, response.Body.String()).Error
				if failed == nil || failed.Code != want.code || failed.Type != want.kind {
					t.Errorf("got %s", response.Body)
				}
				// At the first token's time.
				if want := ms(100); !slices.Equal(f.clock.waited(), want) {
					t.Errorf("waited until %v, want %v", f.clock.waited(), want)
				}
			})
		}
	}
}

func TestAfterTokensAFakeErrorIsAnErrorChunkThatEndsTheStream(t *testing.T) {
	for status, want := range failures {
		t.Run(status, func(t *testing.T) {
			f := serverWith(t, paced(3))

			response := f.ask(`{` + question + `,"stream":true,"fake_error":{"status":` + status + `,"after_tokens":2}}`)

			data := events(t, response.Body.String())
			if response.Code != http.StatusOK || len(data) != 4 {
				t.Fatalf("got %d with %d events, want 200 with 4", response.Code, len(data))
			}
			contents, _, finish := read(t, data[:3])
			if want := []string{"A", " backend"}; !slices.Equal(contents, want) || finish != "" {
				t.Errorf("got %q and the finish reason %q, want %q and none", contents, finish, want)
			}
			failed := parse(t, data[3]).Error
			if failed == nil || failed.Code != want.code || failed.Type != want.kind {
				t.Errorf("got %s", data[3])
			}
			// In place of the third token, at its time.
			if want := ms(100, 120, 140); !slices.Equal(f.clock.waited(), want) {
				t.Errorf("waited until %v, want %v", f.clock.waited(), want)
			}
		})
	}
}

func TestAFakeErrorAfterMoreTokensThanTheAnswerComesAfterTheLast(t *testing.T) {
	f := serverWith(t, paced(3))

	data := events(t, f.ask(`{`+question+`,"stream":true,"fake_error":{"status":503,"after_tokens":99}}`).Body.String())

	contents, _, finish := read(t, data)
	if len(contents) != 3 || finish != "" || parse(t, data[len(data)-1]).Error == nil {
		t.Errorf("got %d tokens, the finish reason %q, and last %s", len(contents), finish, data[len(data)-1])
	}
	if want := ms(100, 120, 140, 160); !slices.Equal(f.clock.waited(), want) {
		t.Errorf("waited until %v, want %v", f.clock.waited(), want)
	}
}

func TestInAWholeAnswerAFakeErrorComesAtItsTokensTime(t *testing.T) {
	f := serverWith(t, paced(3))

	response := f.ask(`{` + question + `,"fake_error":{"status":429,"after_tokens":2}}`)

	if response.Code != http.StatusTooManyRequests {
		t.Errorf("got %d, want 429", response.Code)
	}
	if want := ms(140); !slices.Equal(f.clock.waited(), want) {
		t.Errorf("waited until %v, want %v", f.clock.waited(), want)
	}
}

// closedEarly reads the log's lines about answers their clients left.
func closedEarly(t *testing.T, log *bytes.Buffer) []map[string]any {
	t.Helper()
	var lines []map[string]any
	for line := range strings.Lines(log.String()) {
		var fields map[string]any
		if err := json.Unmarshal([]byte(line), &fields); err != nil {
			t.Fatalf("%v in %q", err, line)
		}
		if fields["msg"] == "closed early" {
			lines = append(lines, fields)
		}
	}
	return lines
}

func TestA504IsNoAnswerUntilTheClientLeaves(t *testing.T) {
	cases := map[string]struct {
		body   string
		events int
	}{
		"a stream":                {`,"stream":true,"fake_error":{"status":504}}`, 0},
		"a stream, after a token": {`,"stream":true,"fake_error":{"status":504,"after_tokens":1}}`, 2},
		"a whole answer":          {`,"fake_error":{"status":504}}`, 0},
	}
	for name, c := range cases {
		t.Run(name, func(t *testing.T) {
			f := serverWith(t, paced(3))
			ctx, leave := context.WithCancel(context.Background())
			answered := make(chan *httptest.ResponseRecorder)
			go func() { answered <- f.post(ctx, `{`+question+c.body) }()

			select {
			case <-answered:
				t.Fatal("it answered")
			case <-time.After(50 * time.Millisecond):
			}
			leave()

			response := <-answered
			if got := len(events(t, response.Body.String())); got != c.events {
				t.Errorf("got %d events, want %d: %s", got, c.events, response.Body)
			}
			if lines := closedEarly(t, f.log); len(lines) != 1 {
				t.Errorf("logged %d answers closed early, want 1", len(lines))
			}
		})
	}
}

func TestAMalformedFakeErrorIsRefusedAtOnce(t *testing.T) {
	cases := map[string]string{ //nolint:gosec // G101: test cases, not credentials.
		"not an object":            `"503"`,
		"a list":                   `[503]`,
		"no status":                `{}`,
		"an unknown status":        `{"status":500}`,
		"a status as a string":     `{"status":"503"}`,
		"a negative after_tokens":  `{"status":503,"after_tokens":-1}`,
		"a fraction of a token":    `{"status":503,"after_tokens":1.5}`,
		"after_tokens as a string": `{"status":503,"after_tokens":"1"}`,
	}
	for name, fakeError := range cases {
		for _, stream := range []string{"true", "false"} {
			t.Run(name+", stream "+stream, func(t *testing.T) {
				f := serverWith(t, paced(3))

				response := f.ask(`{` + question + `,"stream":` + stream + `,"fake_error":` + fakeError + `}`)

				failed := parse(t, response.Body.String()).Error
				if response.Code != http.StatusBadRequest || failed == nil || failed.Type != "invalid_request_error" {
					t.Errorf("got %d: %s", response.Code, response.Body)
				}
				if waits := f.clock.waited(); len(waits) != 0 {
					t.Errorf("waited until %v, want no wait", waits)
				}
			})
		}
	}
}

func TestANullFakeErrorAsksForNoFailure(t *testing.T) {
	f := serverWith(t, settings.Settings{AnswerTokens: 3})

	response := f.ask(`{` + question + `,"fake_error":null}`)

	if response.Code != http.StatusOK {
		t.Errorf("got %d, want 200", response.Code)
	}
}

func TestARequestItCantReadIsRefusedAsLlamaCppDoes(t *testing.T) {
	cases := map[string]string{
		"not JSON":              `{"messages":`,
		"no messages":           `{"stream":true}`,
		"messages as null":      `{"messages":null}`,
		"messages as a string":  `{"messages":"no"}`,
		"a message as a list":   `{"messages":[[]]}`,
		"content as a number":   `{"messages":[{"role":"user","content":5}]}`,
		"stream as a string":    `{` + question + `,"stream":"yes"}`,
		"stream_options a list": `{` + question + `,"stream_options":[]}`,
	}
	for name, body := range cases {
		t.Run(name, func(t *testing.T) {
			f := serverWith(t, settings.Settings{AnswerTokens: 3})

			response := f.ask(body)

			failed := parse(t, response.Body.String()).Error
			if response.Code != http.StatusBadRequest || failed == nil ||
				failed.Code != http.StatusBadRequest || failed.Type != "invalid_request_error" {
				t.Errorf("got %d: %s", response.Code, response.Body)
			}
		})
	}
}

func TestABodyThatCantBeReadIsRefused(t *testing.T) {
	f := serverWith(t, settings.Settings{AnswerTokens: 3})
	request := httptest.NewRequestWithContext(context.Background(), http.MethodPost, "/v1/chat/completions",
		iotest.ErrReader(errors.New("the connection broke")))
	recorder := httptest.NewRecorder()

	f.handler.ServeHTTP(recorder, request)

	if recorder.Code != http.StatusBadRequest {
		t.Errorf("got %d, want 400", recorder.Code)
	}
}

func TestAMessageWithoutContentCountsNoWords(t *testing.T) {
	f := serverWith(t, settings.Settings{AnswerTokens: 1})

	body := `{"messages":[{"role":"assistant","content":null},{"role":"user","content":"two\u00a0joined  words\t\n"}],` +
		`"stream":true,"stream_options":{"include_usage":true}}`
	data := events(t, f.ask(body).Body.String())

	// A non-breaking space belongs to its word.
	if usage := parse(t, data[len(data)-2]).Usage; usage == nil || usage.PromptTokens != 2 {
		t.Errorf("got the usage %+v, want 2 prompt tokens", usage)
	}
}

func TestAClientThatLeavesStopsItsStream(t *testing.T) {
	f := serverWith(t, paced(5))
	ctx, leave := context.WithCancel(context.Background())
	f.clock.onWait = func(number int) {
		if number == 2 {
			leave()
		}
	}

	response := f.post(ctx, `{`+question+`,"stream":true}`)

	contents, _, _ := read(t, events(t, response.Body.String()))
	if len(contents) != 2 {
		t.Errorf("sent %d tokens, want 2", len(contents))
	}
	lines := closedEarly(t, f.log)
	if len(lines) != 1 || lines[0]["tokens_sent"] != 2.0 || lines[0]["stream"] != true || lines[0]["after_ms"] != 120.0 {
		t.Errorf("logged %v", lines)
	}
}

func TestAClientThatLeavesBeforeItsAnswerIsLogged(t *testing.T) {
	cases := map[string]string{ //nolint:gosec // G101: test cases, not credentials.
		"a whole answer":                      `}`,
		"a stream that fails after its token": `,"stream":true,"fake_error":{"status":503,"after_tokens":1}}`,
	}
	for name, body := range cases {
		t.Run(name, func(t *testing.T) {
			f := serverWith(t, paced(1))
			ctx, leave := context.WithCancel(context.Background())
			last := strings.Count(body, "after_tokens")
			f.clock.onWait = func(number int) {
				if number == last {
					leave()
				}
			}

			f.post(ctx, `{`+question+body)

			if lines := closedEarly(t, f.log); len(lines) != 1 {
				t.Errorf("logged %d answers closed early, want 1", len(lines))
			}
		})
	}
}

// brokenWriter is a connection that fails after a number of writes, and can't flush.
type brokenWriter struct {
	header http.Header
	writes int
}

func (w *brokenWriter) Header() http.Header { return w.header }
func (w *brokenWriter) WriteHeader(int)     {}
func (w *brokenWriter) Write(data []byte) (int, error) {
	if w.writes == 0 {
		return 0, errors.New("the connection broke")
	}
	w.writes--
	return len(data), nil
}

// FlushError makes the writer one that http.ResponseController can flush.
func (w *brokenWriter) FlushError() error { return nil }

func TestAConnectionThatBreaksStopsTheStream(t *testing.T) {
	cases := map[string]struct {
		body   string
		writes int
	}{
		"on a token":        {`,"stream":true}`, 1},
		"on an error chunk": {`,"stream":true,"fake_error":{"status":503,"after_tokens":1}}`, 1},
	}
	for name, c := range cases {
		t.Run(name, func(t *testing.T) {
			f := serverWith(t, paced(3))
			request := httptest.NewRequestWithContext(context.Background(), http.MethodPost,
				"/v1/chat/completions", strings.NewReader(`{`+question+c.body))

			f.handler.ServeHTTP(&brokenWriter{header: http.Header{}, writes: c.writes}, request)

			if lines := closedEarly(t, f.log); len(lines) != 1 || lines[0]["tokens_sent"] != 1.0 {
				t.Errorf("logged %v, want one answer closed after 1 token", lines)
			}
		})
	}
}

func TestHealthAnswersAsLlamaCpps(t *testing.T) {
	f := serverWith(t, settings.Default())
	request := httptest.NewRequestWithContext(context.Background(), http.MethodGet, "/health", http.NoBody)
	recorder := httptest.NewRecorder()

	f.handler.ServeHTTP(recorder, request)

	if recorder.Code != http.StatusOK || recorder.Body.String() != `{"status":"ok"}` {
		t.Errorf("got %d: %s", recorder.Code, recorder.Body)
	}
}
