// Package upstream is the upstream client: an OpenAI-compatible chat API, such as llama.cpp's
// server or the fake server, called with net/http alone (contract/README.md#the-upstream,
// spec/decisions/0024). Both Go backends share it.
package upstream

import (
	"bufio"
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"io"
	"iter"
	"net/http"
	"strings"
	"time"

	"github.com/fkuhne/api-langs-bench/backends/go/internal/llm"
	"github.com/fkuhne/api-langs-bench/backends/go/internal/settings"
)

// ReadinessTimeout is how long a readiness check waits at most, or the setting's timeout if
// that's shorter.
const ReadinessTimeout = 5 * time.Second

// done is how a stream says it has ended.
const done = "[DONE]"

// The longest line of a stream the client reads: one chunk.
const maxLine = 16 << 20

// The most the client reads of a failed answer's body, for its reason.
const maxErrorBody = 1 << 20

// errTimedOut is why a request's context ended, once nothing had arrived for the timeout.
var errTimedOut = errors.New("nothing arrived from the upstream in time")

// Client calls POST {LLM_BASE_URL}/chat/completions, whole or streamed. It sends the caller's
// parameters as given, and adds none of its own.
type Client struct {
	http    *http.Client
	url     string
	model   string
	key     string
	timeout time.Duration
}

// New returns the client the settings describe.
func New(s settings.Settings) *Client {
	// Go's own defaults, with the pool the settings give: as many connections kept idle as
	// may be open, so a steady load reuses them.
	transport := http.DefaultTransport.(*http.Transport).Clone()
	transport.MaxConnsPerHost = s.LLMMaxConnections
	transport.MaxIdleConnsPerHost = s.LLMMaxConnections
	transport.MaxIdleConns = s.LLMMaxConnections
	return &Client{
		// No Timeout here: it would bound the whole answer, and cut a long stream.
		http:    &http.Client{Transport: transport},
		url:     strings.TrimRight(s.LLMBaseURL, "/") + "/chat/completions",
		model:   s.LLMModel,
		key:     s.LLMAPIKey,
		timeout: s.LLMTimeout,
	}
}

// watch ends a request's context once nothing has arrived for the timeout: a connection, the
// answer's start, or the next piece of its body. It doesn't bound the whole answer.
type watch struct {
	context.Context
	timer   *time.Timer
	timeout time.Duration
	cancel  context.CancelCauseFunc
}

func watched(parent context.Context, timeout time.Duration) *watch {
	ctx, cancel := context.WithCancelCause(parent)
	timer := time.AfterFunc(timeout, func() { cancel(errTimedOut) })
	return &watch{Context: ctx, timer: timer, timeout: timeout, cancel: cancel}
}

// arrived starts the wait again.
func (w *watch) arrived() { w.timer.Reset(w.timeout) }

// stop ends the request, and closes its connection if its answer isn't finished.
func (w *watch) stop() {
	w.timer.Stop()
	w.cancel(nil)
}

// body reads an answer's body, and tells the watch of each piece that arrives.
type body struct {
	reader io.Reader
	watch  *watch
}

func (b body) Read(p []byte) (int, error) {
	n, err := b.reader.Read(p)
	if n > 0 {
		b.watch.arrived()
	}
	return n, err
}

// Complete returns the whole answer to messages.
func (c *Client) Complete(
	parent context.Context, messages []llm.Message, parameters llm.Parameters,
) (llm.Completion, error) {
	ctx := watched(parent, c.timeout)
	defer ctx.stop()
	response, err := c.post(ctx, c.request(messages, parameters, false))
	if err != nil {
		return llm.Completion{}, failed(parent, ctx, err)
	}
	defer func() { _ = response.Body.Close() }()
	ctx.arrived()
	data, err := io.ReadAll(body{response.Body, ctx})
	if err != nil {
		return llm.Completion{}, failed(parent, ctx, err)
	}
	if !succeeded(response) {
		return llm.Completion{}, statusError(response.StatusCode, data)
	}
	var answer struct {
		Choices []struct {
			FinishReason *string `json:"finish_reason"`
			Message      *texts  `json:"message"`
		} `json:"choices"`
		Model string `json:"model"`
		Usage *usage `json:"usage"`
	}
	if json.Unmarshal(data, &answer) != nil || len(answer.Choices) == 0 || answer.Choices[0].Message == nil {
		return llm.Completion{}, unreadable()
	}
	choice := answer.Choices[0]
	completion := llm.Completion{
		Content:      text(choice.Message.Content),
		Model:        c.model,
		FinishReason: nonEmpty(choice.FinishReason),
		Usage:        answer.Usage.counts(),
	}
	if reasoning := choice.Message.reasoning(); reasoning != "" {
		completion.Reasoning = &reasoning
	}
	if answer.Model != "" {
		completion.Model = answer.Model
	}
	return completion, nil
}

// Stream yields one part for each piece of text the upstream sends, then the end. Stopping
// early, or ending parent, closes the upstream's connection, which stops the model.
func (c *Client) Stream(
	parent context.Context, messages []llm.Message, parameters llm.Parameters,
) iter.Seq2[llm.StreamPart, error] {
	return func(yield func(llm.StreamPart, error) bool) {
		ctx := watched(parent, c.timeout)
		// Deferred calls run last first: the request ends, then its body is closed, so the
		// connection closes at once instead of being read on for reuse.
		defer ctx.stop()
		response, err := c.post(ctx, c.request(messages, parameters, true))
		if err != nil {
			yield(nil, failed(parent, ctx, err))
			return
		}
		defer func() {
			ctx.stop()
			_ = response.Body.Close()
		}()
		ctx.arrived()
		reader := body{response.Body, ctx}
		if !succeeded(response) {
			data, err := io.ReadAll(io.LimitReader(reader, maxErrorBody))
			if err != nil {
				yield(nil, failed(parent, ctx, err))
				return
			}
			yield(nil, statusError(response.StatusCode, data))
			return
		}
		end := llm.StreamEnd{Model: c.model}
		lines := bufio.NewScanner(reader)
		lines.Buffer(make([]byte, 0, 64<<10), maxLine)
		for lines.Scan() {
			data, isData := eventData(lines.Bytes())
			if !isData {
				continue
			}
			if string(data) == done {
				break
			}
			var piece chunk
			if json.Unmarshal(data, &piece) != nil {
				yield(nil, unreadable())
				return
			}
			if len(piece.Error) > 0 {
				yield(nil, streamError(piece.Error))
				return
			}
			if piece.Model != "" {
				end.Model = piece.Model
			}
			if counts := piece.Usage.counts(); counts != nil {
				end.Usage = counts
			}
			if len(piece.Choices) == 0 {
				continue
			}
			choice := piece.Choices[0]
			if reason := nonEmpty(choice.FinishReason); reason != nil {
				end.FinishReason = reason
			}
			if choice.Delta == nil {
				continue
			}
			if reasoning := choice.Delta.reasoning(); reasoning != "" {
				if !yield(llm.ReasoningDelta{Text: reasoning}, nil) {
					return
				}
			}
			if content := text(choice.Delta.Content); content != "" {
				if !yield(llm.ContentDelta{Text: content}, nil) {
					return
				}
			}
		}
		if err := lines.Err(); err != nil {
			yield(nil, failed(parent, ctx, err))
			return
		}
		yield(end, nil)
	}
}

// Ready tries a completion of one token, as ai-bootstrap does: a server can list its model
// before it can serve it. A 400 counts as ready: the upstream answered, and refused only the
// probe's own max_tokens.
func (c *Client) Ready(parent context.Context) bool {
	ctx, cancel := context.WithTimeout(parent, min(ReadinessTimeout, c.timeout))
	defer cancel()
	probe := map[string]any{
		"model":      c.model,
		"messages":   []llm.Message{{Role: llm.RoleUser, Content: "ping"}},
		"max_tokens": 1,
	}
	response, err := c.post(ctx, probe)
	if err != nil {
		return false
	}
	defer func() { _ = response.Body.Close() }()
	// Read to the end, so the connection can be used again.
	_, _ = io.Copy(io.Discard, io.LimitReader(response.Body, maxErrorBody))
	return succeeded(response) || response.StatusCode == http.StatusBadRequest
}

// Close closes the connections kept idle.
func (c *Client) Close() error {
	c.http.CloseIdleConnections()
	return nil
}

// request is the body sent to the upstream. A chat request can't carry model or messages
// among its parameters: they're reserved.
func (c *Client) request(messages []llm.Message, parameters llm.Parameters, stream bool) map[string]any {
	request := make(map[string]any, len(parameters)+4)
	for name, value := range parameters {
		request[name] = value
	}
	request["model"] = c.model
	request["messages"] = messages
	if stream {
		request["stream"] = true
		// The usage comes in a last chunk without choices.
		request["stream_options"] = map[string]bool{"include_usage": true}
	}
	return request
}

func (c *Client) post(ctx context.Context, request map[string]any) (*http.Response, error) {
	var encoded bytes.Buffer
	// What a request can carry, parsed from JSON, always encodes.
	_ = json.NewEncoder(&encoded).Encode(request)
	call, err := http.NewRequestWithContext(ctx, http.MethodPost, c.url, &encoded)
	if err != nil {
		return nil, err
	}
	call.Header.Set("Content-Type", "application/json")
	call.Header.Set("Authorization", "Bearer "+c.key)
	return c.http.Do(call)
}

func succeeded(response *http.Response) bool {
	return response.StatusCode >= 200 && response.StatusCode < 300
}

// failed is the error a request that got no answer is: the caller's own, once its context has
// ended; else a timeout, or an upstream that can't be reached.
func failed(parent context.Context, ctx context.Context, err error) error {
	if parent.Err() != nil {
		return parent.Err()
	}
	if errors.Is(context.Cause(ctx), errTimedOut) {
		return &llm.ServiceError{Status: http.StatusGatewayTimeout, Detail: service + " didn't answer in time."}
	}
	if errors.Is(err, bufio.ErrTooLong) {
		return unreadable()
	}
	return &llm.ServiceError{Status: http.StatusServiceUnavailable, Detail: service + " can't be reached."}
}

// eventData returns a server-sent event's data, from its line. It isn't data for a blank
// line, a comment or another field.
func eventData(line []byte) ([]byte, bool) {
	data, found := bytes.CutPrefix(line, []byte("data:"))
	if !found {
		return nil, false
	}
	return bytes.TrimPrefix(data, []byte(" ")), true
}

// texts is what a message or a delta carries. Servers put the model's reasoning under two
// names: llama.cpp and DeepSeek use the first, Ollama and OpenRouter the second.
type texts struct {
	Content          *string `json:"content"`
	ReasoningContent *string `json:"reasoning_content"`
	Reasoning        *string `json:"reasoning"`
}

func (t *texts) reasoning() string {
	if found := text(t.ReasoningContent); found != "" {
		return found
	}
	return text(t.Reasoning)
}

// chunk is one piece of a stream.
type chunk struct {
	// Error is set when the upstream fails inside its stream.
	Error   json.RawMessage `json:"error"`
	Model   string          `json:"model"`
	Usage   *usage          `json:"usage"`
	Choices []struct {
		FinishReason *string `json:"finish_reason"`
		Delta        *texts  `json:"delta"`
	} `json:"choices"`
}

// usage is the tokens an answer used. llama.cpp adds details the contract doesn't carry.
type usage struct {
	PromptTokens     *int `json:"prompt_tokens"`
	CompletionTokens *int `json:"completion_tokens"`
	TotalTokens      *int `json:"total_tokens"`
}

// counts is the three counts, when the upstream gives all three.
func (u *usage) counts() *llm.Usage {
	if u == nil || u.PromptTokens == nil || u.CompletionTokens == nil || u.TotalTokens == nil {
		return nil
	}
	return &llm.Usage{
		PromptTokens:     *u.PromptTokens,
		CompletionTokens: *u.CompletionTokens,
		TotalTokens:      *u.TotalTokens,
	}
}

func text(value *string) string {
	if value == nil {
		return ""
	}
	return *value
}

// nonEmpty is value, or nil when it's empty or missing.
func nonEmpty(value *string) *string {
	if value == nil || *value == "" {
		return nil
	}
	return value
}
