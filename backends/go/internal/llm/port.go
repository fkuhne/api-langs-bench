// Package llm is the LLM port: what the backend needs from a chat model. It's ai-bootstrap's
// app/llm/llm_client.py, cut to text (contract/README.md#the-request).
package llm

import (
	"context"
	"iter"
)

// Role is who wrote a message.
type Role string

// The roles a message can have.
const (
	RoleSystem    Role = "system"
	RoleUser      Role = "user"
	RoleAssistant Role = "assistant"
)

// Valid tells whether r is one of the contract's roles.
func (r Role) Valid() bool {
	return r == RoleSystem || r == RoleUser || r == RoleAssistant
}

// Message is one message of the conversation sent to the model.
type Message struct {
	Role    Role   `json:"role"`
	Content string `json:"content"`
}

// Usage is the tokens one answer used, as the upstream counts them.
type Usage struct {
	PromptTokens     int `json:"prompt_tokens"`
	CompletionTokens int `json:"completion_tokens"`
	TotalTokens      int `json:"total_tokens"`
}

// Completion is a whole answer, with the model's reasoning when it shows it.
type Completion struct {
	Content      string  `json:"content"`
	Reasoning    *string `json:"reasoning"`
	Model        string  `json:"model"`
	FinishReason *string `json:"finish_reason"`
	Usage        *Usage  `json:"usage"`
}

// StreamPart is one part of a streamed answer: a ReasoningDelta, a ContentDelta or a StreamEnd.
type StreamPart interface {
	// Event is the name the contract's stream sends the part as.
	Event() string
}

// ReasoningDelta is the next piece of the model's reasoning, which comes before the answer.
type ReasoningDelta struct {
	Text string `json:"text"`
}

// ContentDelta is the next piece of the answer.
type ContentDelta struct {
	Text string `json:"text"`
}

// StreamEnd is the last part of a stream that ended normally.
type StreamEnd struct {
	Model        string  `json:"model"`
	FinishReason *string `json:"finish_reason"`
	Usage        *Usage  `json:"usage"`
}

// Event is "reasoning".
func (ReasoningDelta) Event() string { return "reasoning" }

// Event is "token".
func (ContentDelta) Event() string { return "token" }

// Event is "done".
func (StreamEnd) Event() string { return "done" }

// Client is a chat model the backend can call. Its failures are *ServiceError, or the
// context's error once ctx ends.
type Client interface {
	// Complete returns the whole answer to messages.
	Complete(ctx context.Context, messages []Message, parameters Parameters) (Completion, error)
	// Stream yields the reasoning and the answer piece by piece, then a StreamEnd, or an error
	// that ends it. Stopping early, or ending ctx, stops the model.
	Stream(ctx context.Context, messages []Message, parameters Parameters) iter.Seq2[StreamPart, error]
	// Ready tells whether the model can take requests right now.
	Ready(ctx context.Context) bool
	// Close releases connections and other resources.
	Close() error
}
