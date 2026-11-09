package fake_test

import (
	"context"
	"encoding/json"
	"errors"
	"slices"
	"testing"
	"time"

	"github.com/fkuhne/api-langs-bench/backends/go/internal/fake"
	"github.com/fkuhne/api-langs-bench/backends/go/internal/llm"
	"github.com/fkuhne/api-langs-bench/backends/go/internal/settings"
)

var question = []llm.Message{{Role: llm.RoleUser, Content: "In one sentence, what is an LLM?"}}

// manualClock moves only when the fake waits, and records each deadline as an offset from
// its start.
type manualClock struct {
	now   time.Time
	waits []time.Duration
}

var epoch = time.Date(2026, 11, 9, 0, 0, 0, 0, time.UTC)

func (c *manualClock) Now() time.Time { return c.now }

func (c *manualClock) SleepUntil(ctx context.Context, deadline time.Time) error {
	if err := ctx.Err(); err != nil {
		return err
	}
	c.waits = append(c.waits, deadline.Sub(epoch))
	if deadline.After(c.now) {
		c.now = deadline
	}
	return nil
}

func milliseconds(values ...int) []time.Duration {
	waits := make([]time.Duration, len(values))
	for i, value := range values {
		waits[i] = time.Duration(value) * time.Millisecond
	}
	return waits
}

func tokens(t *testing.T) []string {
	t.Helper()
	loaded, err := fake.LoadTokens(fake.TokensFile)
	if err != nil {
		t.Fatal(err)
	}
	return loaded
}

func fakeWith(t *testing.T, change func(*settings.Settings)) (*fake.Client, *manualClock) {
	t.Helper()
	s := settings.Default()
	if change != nil {
		change(&s)
	}
	clock := &manualClock{now: epoch}
	return fake.New(s, tokens(t), clock), clock
}

func paced(s *settings.Settings) { s.FakeFirstTokenMS, s.FakeTokenGapMS = 100, 20 }

// parse reads parameters as a request carries them.
func parse(t *testing.T, body string) llm.Parameters {
	t.Helper()
	var parameters llm.Parameters
	if err := json.Unmarshal([]byte(body), &parameters); err != nil {
		t.Fatal(err)
	}
	return parameters
}

// collect streams the answer, and returns its parts and the error that ended it, if any.
func collect(client *fake.Client, parameters llm.Parameters) ([]llm.StreamPart, error) {
	return collectWith(context.Background(), client, parameters)
}

func collectWith(ctx context.Context, client *fake.Client, parameters llm.Parameters) ([]llm.StreamPart, error) {
	var parts []llm.StreamPart
	for part, err := range client.Stream(ctx, question, parameters) {
		if err != nil {
			return parts, err
		}
		parts = append(parts, part)
	}
	return parts, nil
}

func texts(parts []llm.StreamPart) []string {
	var got []string
	for _, part := range parts {
		switch part := part.(type) {
		case llm.ReasoningDelta:
			got = append(got, part.Text)
		case llm.ContentDelta:
			got = append(got, part.Text)
		}
	}
	return got
}

func serviceStatus(t *testing.T, err error) int {
	t.Helper()
	var service *llm.ServiceError
	if !errors.As(err, &service) {
		t.Fatalf("got %v, want a *llm.ServiceError", err)
	}
	return service.Status
}

func TestMaxTokensCutsTheAnswer(t *testing.T) {
	client, _ := fakeWith(t, nil)

	parts, err := collect(client, parse(t, `{"max_tokens": 5}`))
	if err != nil {
		t.Fatal(err)
	}

	if got, want := texts(parts), tokens(t)[:5]; !slices.Equal(got, want) {
		t.Errorf("got %q, want %q", got, want)
	}
	for _, part := range parts[:5] {
		if _, ok := part.(llm.ContentDelta); !ok {
			t.Errorf("got %T, want only ContentDelta before the end", part)
		}
	}
	end, ok := parts[len(parts)-1].(llm.StreamEnd)
	if !ok {
		t.Fatalf("got %T last, want StreamEnd", parts[len(parts)-1])
	}
	if end.Model != "fake" || *end.FinishReason != "length" {
		t.Errorf("got model %q and finish %q, want fake and length", end.Model, *end.FinishReason)
	}
	if want := (llm.Usage{PromptTokens: 7, CompletionTokens: 5, TotalTokens: 12}); *end.Usage != want {
		t.Errorf("got %+v, want %+v", *end.Usage, want)
	}
}

func TestTheAnswerIsFakeAnswerTokensLongOtherwise(t *testing.T) {
	cases := map[string]string{
		"absent":           `{}`,
		"null":             `{"max_tokens": null}`,
		"the same length":  `{"max_tokens": 3}`,
		"longer":           `{"max_tokens": 4}`,
		"zero":             `{"max_tokens": 0}`,
		"negative":         `{"max_tokens": -1}`,
		"a string":         `{"max_tokens": "2"}`,
		"a fraction":       `{"max_tokens": 2.5}`,
		"written as float": `{"max_tokens": 2.0}`,
		"an exponent":      `{"max_tokens": 2e0}`,
		"a bool":           `{"max_tokens": true}`,
		"beyond int64":     `{"max_tokens": 99999999999999999999}`,
	}
	for name, body := range cases {
		t.Run(name, func(t *testing.T) {
			client, _ := fakeWith(t, func(s *settings.Settings) { s.FakeAnswerTokens = 3 })

			parts, err := collect(client, parse(t, body))
			if err != nil {
				t.Fatal(err)
			}

			if len(parts) != 4 {
				t.Errorf("got %d parts, want 3 tokens and the end", len(parts))
			}
			if end := parts[len(parts)-1].(llm.StreamEnd); *end.FinishReason != "stop" {
				t.Errorf("got finish %q, want stop", *end.FinishReason)
			}
		})
	}
}

func TestTheTokensWrapAround(t *testing.T) {
	all := tokens(t)
	client, _ := fakeWith(t, func(s *settings.Settings) { s.FakeAnswerTokens = len(all) + 2 })

	parts, err := collect(client, nil)
	if err != nil {
		t.Fatal(err)
	}

	got := texts(parts)
	if last := got[len(got)-2:]; !slices.Equal(last, all[:2]) {
		t.Errorf("got %q last, want %q", last, all[:2])
	}
}

func TestReasoningComesFirstAndCountsAsCompletion(t *testing.T) {
	all := tokens(t)
	client, _ := fakeWith(t, func(s *settings.Settings) { s.FakeReasoningTokens, s.FakeAnswerTokens = 2, 3 })
	parameters := parse(t, `{"max_tokens": 1}`)

	parts, err := collect(client, parameters)
	if err != nil {
		t.Fatal(err)
	}
	whole, err := client.Complete(context.Background(), question, parameters)
	if err != nil {
		t.Fatal(err)
	}

	_, first := parts[0].(llm.ReasoningDelta)
	_, second := parts[1].(llm.ReasoningDelta)
	_, third := parts[2].(llm.ContentDelta)
	if !first || !second || !third {
		t.Errorf("got %T, %T, %T, want reasoning, reasoning, token", parts[0], parts[1], parts[2])
	}
	if got, want := texts(parts), []string{all[0], all[1], all[0]}; !slices.Equal(got, want) {
		t.Errorf("got %q, want %q", got, want)
	}
	if end := parts[3].(llm.StreamEnd); end.Usage.CompletionTokens != 3 {
		t.Errorf("got %d completion tokens, want 3", end.Usage.CompletionTokens)
	}
	if *whole.Reasoning != all[0]+all[1] || whole.Content != all[0] {
		t.Errorf("got reasoning %q and content %q", *whole.Reasoning, whole.Content)
	}
}

func TestWithoutReasoningTheWholeAnswerHasNone(t *testing.T) {
	client, _ := fakeWith(t, nil)

	whole, err := client.Complete(context.Background(), question, parse(t, `{"max_tokens": 5}`))
	if err != nil {
		t.Fatal(err)
	}

	if whole.Reasoning != nil {
		t.Errorf("got reasoning %q, want none", *whole.Reasoning)
	}
	if whole.Content != "A backend in front of" || whole.Model != "fake" || *whole.FinishReason != "length" {
		t.Errorf("got %+v", whole)
	}
}

func TestPromptTokensCountWordsSplitOnlyOnASCIISpace(t *testing.T) {
	client, _ := fakeWith(t, nil)
	messages := []llm.Message{
		{Role: llm.RoleSystem, Content: "  one\ttwo\r\nthree  "},
		{Role: llm.RoleUser, Content: "four\u00a0still-four five"},
	}

	whole, err := client.Complete(context.Background(), messages, nil)
	if err != nil {
		t.Fatal(err)
	}

	if whole.Usage.PromptTokens != 5 {
		t.Errorf("got %d prompt tokens, want 5", whole.Usage.PromptTokens)
	}
}

func TestEachTokenWaitsForItsOwnTime(t *testing.T) {
	client, clock := fakeWith(t, paced)

	if _, err := collect(client, parse(t, `{"max_tokens": 4}`)); err != nil {
		t.Fatal(err)
	}

	if want := milliseconds(100, 120, 140, 160); !slices.Equal(clock.waits, want) {
		t.Errorf("got waits %v, want %v", clock.waits, want)
	}
}

func TestTheWholeAnswerWaitsOnceForTheLastToken(t *testing.T) {
	client, clock := fakeWith(t, paced)

	if _, err := client.Complete(context.Background(), question, parse(t, `{"max_tokens": 4}`)); err != nil {
		t.Fatal(err)
	}

	if want := milliseconds(160); !slices.Equal(clock.waits, want) {
		t.Errorf("got waits %v, want %v", clock.waits, want)
	}
}

func TestFakeErrorFailsInPlaceOfTheNextToken(t *testing.T) {
	client, clock := fakeWith(t, paced)

	parts, err := collect(client, parse(t, `{"fake_error": {"status": 503, "after_tokens": 2}}`))

	if got := serviceStatus(t, err); got != 503 {
		t.Errorf("got %d, want 503", got)
	}
	if got, want := texts(parts), tokens(t)[:2]; !slices.Equal(got, want) {
		t.Errorf("got %q before the failure, want %q", got, want)
	}
	if want := milliseconds(100, 120, 140); !slices.Equal(clock.waits, want) {
		t.Errorf("got waits %v, want %v", clock.waits, want)
	}
}

func TestFakeErrorFailsTheWholeAnswerAtTheSameTime(t *testing.T) {
	client, clock := fakeWith(t, paced)

	_, err := client.Complete(context.Background(), question,
		parse(t, `{"fake_error": {"status": 503, "after_tokens": 2}}`))

	if got := serviceStatus(t, err); got != 503 {
		t.Errorf("got %d, want 503", got)
	}
	if err.Error() != "The fake failed with 503, as fake_error asked" {
		t.Errorf("got detail %q", err)
	}
	if want := milliseconds(140); !slices.Equal(clock.waits, want) {
		t.Errorf("got waits %v, want %v", clock.waits, want)
	}
}

func TestFakeErrorAfterTheLastTokenStillFails(t *testing.T) {
	client, _ := fakeWith(t, func(s *settings.Settings) { s.FakeAnswerTokens = 2 })

	parts, err := collect(client, parse(t, `{"fake_error": {"status": 429, "after_tokens": 9}}`))

	if len(parts) != 2 {
		t.Errorf("got %d parts, want the 2 tokens", len(parts))
	}
	if got := serviceStatus(t, err); got != 429 {
		t.Errorf("got %d, want 429", got)
	}
}

func TestFakeErrorWithoutAfterTokensFailsBeforeTheFirst(t *testing.T) {
	client, clock := fakeWith(t, paced)

	parts, err := collect(client, parse(t, `{"fake_error": {"status": 504}}`))

	if len(parts) != 0 || serviceStatus(t, err) != 504 {
		t.Errorf("got %d parts and %v, want none and 504", len(parts), err)
	}
	if want := milliseconds(100); !slices.Equal(clock.waits, want) {
		t.Errorf("got waits %v, want %v", clock.waits, want)
	}
}

func TestANullFakeErrorIsIgnored(t *testing.T) {
	client, _ := fakeWith(t, func(s *settings.Settings) { s.FakeAnswerTokens = 1 })

	if _, err := collect(client, parse(t, `{"fake_error": null}`)); err != nil {
		t.Errorf("got %v, want no failure", err)
	}
}

func TestAMalformedFakeErrorFailsAtOnceWith502(t *testing.T) {
	cases := map[string]string{
		"not an object":       `"503"`,
		"no status":           `{}`,
		"an unknown status":   `{"status": 500}`,
		"a bool status":       `{"status": true}`,
		"a fractional status": `{"status": 503.0}`,
		"a negative count":    `{"status": 503, "after_tokens": -1}`,
		"a fractional count":  `{"status": 503, "after_tokens": 1.5}`,
		"a null count":        `{"status": 503, "after_tokens": null}`,
		"a count as a string": `{"status": 503, "after_tokens": "1"}`,
	}
	for name, spec := range cases {
		t.Run(name, func(t *testing.T) {
			client, clock := fakeWith(t, paced)
			parameters := parse(t, `{"fake_error": `+spec+`}`)

			_, streamed := collect(client, parameters)
			_, whole := client.Complete(context.Background(), question, parameters)

			for _, err := range []error{streamed, whole} {
				if got := serviceStatus(t, err); got != 502 {
					t.Errorf("got %d, want 502", got)
				}
			}
			if len(clock.waits) != 0 {
				t.Errorf("got waits %v, want none", clock.waits)
			}
		})
	}
}

func TestStoppingTheLoopStopsTheFake(t *testing.T) {
	client, clock := fakeWith(t, paced)

	for _, err := range client.Stream(context.Background(), question, nil) {
		if err != nil {
			t.Fatal(err)
		}
		break
	}

	if len(clock.waits) != 1 {
		t.Errorf("got %d waits, want the fake to stop after its first token", len(clock.waits))
	}
}

func TestAnEndedContextStopsTheFake(t *testing.T) {
	ctx, cancel := context.WithCancel(context.Background())
	cancel()

	for _, run := range map[string]func(*fake.Client) error{
		"streamed": func(client *fake.Client) error {
			_, err := collectWith(ctx, client, nil)
			return err
		},
		"whole": func(client *fake.Client) error {
			_, err := client.Complete(ctx, question, nil)
			return err
		},
		"streamed, failing": func(client *fake.Client) error {
			_, err := collectWith(ctx, client, parse(t, `{"fake_error": {"status": 503}}`))
			return err
		},
		"whole, failing": func(client *fake.Client) error {
			_, err := client.Complete(ctx, question, parse(t, `{"fake_error": {"status": 503}}`))
			return err
		},
	} {
		client, _ := fakeWith(t, nil)
		if err := run(client); !errors.Is(err, context.Canceled) {
			t.Errorf("got %v, want context.Canceled", err)
		}
	}
}

func TestAnEndedContextStopsTheFakeBeforeItsFailure(t *testing.T) {
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	client, _ := fakeWith(t, nil)

	var err error
	for _, err = range client.Stream(ctx, question, parse(t, `{"fake_error": {"status": 503, "after_tokens": 1}}`)) {
		cancel()
	}

	if !errors.Is(err, context.Canceled) {
		t.Errorf("got %v, want context.Canceled", err)
	}
}

func TestTheFakeIsAlwaysReady(t *testing.T) {
	client, _ := fakeWith(t, nil)

	if !client.Ready(context.Background()) {
		t.Error("got not ready")
	}
	if err := client.Close(); err != nil {
		t.Error(err)
	}
}
