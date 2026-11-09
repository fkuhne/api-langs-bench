package fake

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"iter"
	"net/http"
	"strconv"
	"strings"
	"time"

	"github.com/fkuhne/api-langs-bench/backends/go/internal/llm"
	"github.com/fkuhne/api-langs-bench/backends/go/internal/settings"
)

// Model is the model the fake says it is.
const Model = "fake"

// Client answers with the contract's tokens, wrapping around, each at its time.
//
// Token i, counting the reasoning and the answer together, is due at
// start + FAKE_FIRST_TOKEN_MS + i * FAKE_TOKEN_GAP_MS. The start is the call.
type Client struct {
	settings settings.Settings
	tokens   []string
	clock    Clock
}

// New returns a fake that answers with tokens, at the pace settings give, on clock. A nil
// clock is the SystemClock.
func New(s settings.Settings, tokens []string, clock Clock) *Client {
	if clock == nil {
		clock = SystemClock{}
	}
	return &Client{settings: s, tokens: tokens, clock: clock}
}

// answer is what one request gets: how many tokens, how it ends, and where it fails, if it does.
type answer struct {
	reasoningTokens int
	answerTokens    int
	finishReason    string
	usage           llm.Usage
	// The failure fake_error asks for, and the token it takes the place of.
	failure *llm.ServiceError
	failsAt int
}

// Complete returns the whole answer, at the last token's time.
func (c *Client) Complete(
	ctx context.Context, messages []llm.Message, parameters llm.Parameters,
) (llm.Completion, error) {
	start := c.clock.Now()
	a, err := c.answer(messages, parameters)
	if err != nil {
		return llm.Completion{}, err
	}
	if a.failure != nil {
		if err := c.clock.SleepUntil(ctx, c.due(start, a.failsAt)); err != nil {
			return llm.Completion{}, err
		}
		return llm.Completion{}, a.failure
	}
	if err := c.clock.SleepUntil(ctx, c.due(start, a.reasoningTokens+a.answerTokens-1)); err != nil {
		return llm.Completion{}, err
	}
	var reasoning *string
	if a.reasoningTokens > 0 {
		text := c.text(a.reasoningTokens)
		reasoning = &text
	}
	return llm.Completion{
		Content:      c.text(a.answerTokens),
		Reasoning:    reasoning,
		Model:        Model,
		FinishReason: &a.finishReason,
		Usage:        &a.usage,
	}, nil
}

// Stream yields the reasoning, then the answer, a token at a time, then the end.
func (c *Client) Stream(
	ctx context.Context, messages []llm.Message, parameters llm.Parameters,
) iter.Seq2[llm.StreamPart, error] {
	start := c.clock.Now()
	return func(yield func(llm.StreamPart, error) bool) {
		a, err := c.answer(messages, parameters)
		if err != nil {
			yield(nil, err)
			return
		}
		made := a.reasoningTokens + a.answerTokens
		if a.failure != nil {
			made = a.failsAt
		}
		for index := range made {
			if err := c.clock.SleepUntil(ctx, c.due(start, index)); err != nil {
				yield(nil, err)
				return
			}
			var part llm.StreamPart
			if index < a.reasoningTokens {
				part = llm.ReasoningDelta{Text: c.token(index)}
			} else {
				part = llm.ContentDelta{Text: c.token(index - a.reasoningTokens)}
			}
			if !yield(part, nil) {
				return
			}
		}
		if a.failure != nil {
			if err := c.clock.SleepUntil(ctx, c.due(start, a.failsAt)); err != nil {
				yield(nil, err)
				return
			}
			yield(nil, a.failure)
			return
		}
		yield(llm.StreamEnd{Model: Model, FinishReason: &a.finishReason, Usage: &a.usage}, nil)
	}
}

// Ready is always true: the fake has nothing to wait for.
func (c *Client) Ready(context.Context) bool { return true }

// Close has nothing to release.
func (c *Client) Close() error { return nil }

func (c *Client) answer(messages []llm.Message, parameters llm.Parameters) (answer, error) {
	reasoning := c.settings.FakeReasoningTokens
	length := c.settings.FakeAnswerTokens
	answerTokens, finishReason := length, "stop"
	if limit, ok := whole(parameters["max_tokens"]); ok && 1 <= limit && limit < int64(length) {
		answerTokens, finishReason = int(limit), "length"
	}
	prompt := 0
	for _, message := range messages {
		prompt += len(strings.FieldsFunc(message.Content, separatesWords))
	}
	failure, failsAt, err := failure(parameters["fake_error"], reasoning+answerTokens)
	if err != nil {
		return answer{}, err
	}
	return answer{
		reasoningTokens: reasoning,
		answerTokens:    answerTokens,
		finishReason:    finishReason,
		usage: llm.Usage{
			PromptTokens:     prompt,
			CompletionTokens: reasoning + answerTokens,
			TotalTokens:      prompt + reasoning + answerTokens,
		},
		failure: failure,
		failsAt: failsAt,
	}, nil
}

func (c *Client) due(start time.Time, index int) time.Time {
	offset := c.settings.FakeFirstTokenMS + index*c.settings.FakeTokenGapMS
	return start.Add(time.Duration(offset) * time.Millisecond)
}

func (c *Client) token(index int) string {
	return c.tokens[index%len(c.tokens)]
}

func (c *Client) text(tokens int) string {
	var text strings.Builder
	for index := range tokens {
		text.WriteString(c.token(index))
	}
	return text.String()
}

// separatesWords is true for a space, a tab, a line feed or a carriage return, for
// `prompt_tokens`. A non-breaking space belongs to its word.
func separatesWords(r rune) bool {
	return r == ' ' || r == '\t' || r == '\n' || r == '\r'
}

// whole reads a JSON whole number as a request's parameters carry it: 5, but not 5.0, "5" or
// true. One too large for int64 is clamped to it, so it still compares as Python's int does.
func whole(value any) (int64, bool) {
	number, ok := value.(json.Number)
	if !ok || strings.ContainsAny(string(number), ".eE") {
		return 0, false
	}
	parsed, err := strconv.ParseInt(string(number), 10, 64)
	return parsed, err == nil || errors.Is(err, strconv.ErrRange)
}

// failure returns the failure fake_error asks for, and the token it takes the place of. A
// malformed one fails at once, with 502, as an upstream refuses a parameter it doesn't accept.
func failure(spec any, tokens int) (*llm.ServiceError, int, error) {
	if spec == nil {
		return nil, tokens, nil
	}
	fields, ok := spec.(map[string]any)
	if !ok {
		return nil, 0, refused("it must be an object")
	}
	status, ok := whole(fields["status"])
	if !ok || !llm.IsServiceStatus(status) {
		return nil, 0, refused("status must be 429, 502, 503 or 504")
	}
	after := int64(0)
	if value, sent := fields["after_tokens"]; sent {
		if after, ok = whole(value); !ok || after < 0 {
			return nil, 0, refused("after_tokens must be 0 or more")
		}
	}
	failure := &llm.ServiceError{
		Status: int(status),
		Detail: fmt.Sprintf("The fake failed with %d, as fake_error asked", status),
	}
	return failure, int(min(after, int64(tokens))), nil
}

func refused(reason string) error {
	return &llm.ServiceError{Status: http.StatusBadGateway, Detail: "The fake refused fake_error: " + reason}
}
