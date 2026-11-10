package chat

import (
	"encoding/json"
	"errors"
	"fmt"
	"net/http"
	"strconv"
	"strings"
)

// request is what the fake server reads of a chat completion's body. Every other parameter
// is ignored, as llama.cpp ignores those it doesn't know.
type request struct {
	Messages []struct {
		Content *string `json:"content"`
	} `json:"messages"`
	Stream        bool `json:"stream"`
	StreamOptions struct {
		IncludeUsage bool `json:"include_usage"`
	} `json:"stream_options"`
	MaxTokens json.RawMessage `json:"max_tokens"`
	FakeError json.RawMessage `json:"fake_error"`
}

// plan is what one request gets: how many tokens, how it ends, and where it fails, if it does
// (contract/README.md#the-answer).
type plan struct {
	stream       bool
	includeUsage bool
	reasoning    int
	answer       int
	finishReason string
	prompt       int
	// The failure fake_error asks for, or nil.
	failure *failure
}

// failure is what fake_error asks for: how it shows, and the token it takes the place of.
type failure struct {
	shows shows
	at    int
}

// shows is how the fake server shows one of fake_error's statuses, as llama.cpp shows a
// failure (spec/decisions/0023).
type shows struct {
	// The HTTP status, and the code in the error's body. 0 means no answer at all.
	code int
	kind string
}

// How each status the contract allows in fake_error is shown.
var statuses = map[int64]shows{
	http.StatusTooManyRequests:    {http.StatusTooManyRequests, "rate_limit_error"},
	http.StatusBadGateway:         {http.StatusBadRequest, kindInvalidRequest},
	http.StatusServiceUnavailable: {http.StatusServiceUnavailable, "unavailable_error"},
	http.StatusGatewayTimeout:     {},
}

// kindInvalidRequest is llama.cpp's type for a request it refuses.
const kindInvalidRequest = "invalid_request_error"

// errRefused means the request can't be answered. Its text is the error's message.
var errRefused = errors.New("refused")

func refused(format string, args ...any) error {
	return fmt.Errorf("%w: %s", errRefused, fmt.Sprintf(format, args...))
}

// tokens is how many tokens the answer has, the reasoning included.
func (p plan) tokens() int { return p.reasoning + p.answer }

// plan reads a request's body, and works out its answer.
func (s *Server) plan(body []byte) (plan, error) {
	var r request
	if err := json.Unmarshal(body, &r); err != nil {
		return plan{}, refused("the body isn't a chat completion request: %v", err)
	}
	if r.Messages == nil {
		return plan{}, refused("Expected 'messages' to be an array")
	}
	p := plan{
		stream:       r.Stream,
		includeUsage: r.StreamOptions.IncludeUsage,
		reasoning:    s.settings.ReasoningTokens,
		answer:       s.settings.AnswerTokens,
		finishReason: "stop",
	}
	if limit, ok := whole(r.MaxTokens); ok && 1 <= limit && limit < int64(p.answer) {
		p.answer, p.finishReason = int(limit), "length"
	}
	for _, message := range r.Messages {
		if message.Content != nil {
			p.prompt += len(strings.FieldsFunc(*message.Content, separatesWords))
		}
	}
	var err error
	p.failure, err = failureOf(r.FakeError, p.tokens())
	return p, err
}

// separatesWords is true for a space, a tab, a line feed or a carriage return, for
// `prompt_tokens`. A non-breaking space belongs to its word.
func separatesWords(r rune) bool {
	return r == ' ' || r == '\t' || r == '\n' || r == '\r'
}

// whole reads a JSON whole number: 5, but not 5.0, "5" or true. One too large for int64 is
// clamped to it, so it still compares as the other fakes' do.
func whole(raw json.RawMessage) (int64, bool) {
	text := string(raw)
	if text == "" || strings.ContainsAny(text, ".eE") {
		return 0, false
	}
	// In a body that parsed, only a number starts with a digit or a minus sign.
	if first := text[0]; first != '-' && (first < '0' || first > '9') {
		return 0, false
	}
	parsed, err := strconv.ParseInt(text, 10, 64)
	return parsed, err == nil || errors.Is(err, strconv.ErrRange)
}

// failureOf returns the failure fake_error asks for, with the token it takes the place of. A
// malformed one is refused (contract/README.md#errors-on-request).
func failureOf(raw json.RawMessage, tokens int) (*failure, error) {
	if len(raw) == 0 || string(raw) == "null" {
		// No failure asked for.
		return nil, nil
	}
	var fields map[string]json.RawMessage
	if err := json.Unmarshal(raw, &fields); err != nil {
		return nil, refused("fake_error must be an object")
	}
	status, ok := whole(fields["status"])
	shown, known := statuses[status]
	if !ok || !known {
		return nil, refused("fake_error's status must be 429, 502, 503 or 504")
	}
	after := int64(0)
	if value, sent := fields["after_tokens"]; sent {
		if after, ok = whole(value); !ok || after < 0 {
			return nil, refused("fake_error's after_tokens must be 0 or more")
		}
	}
	return &failure{shows: shown, at: int(min(after, int64(tokens)))}, nil
}
