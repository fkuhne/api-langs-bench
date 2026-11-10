package chat

import (
	"bytes"
	"encoding/json"
	"strconv"
)

// The answers' shapes are llama.cpp's, field for field and in its order, as its server sent
// them on 2026-11-10 (docs/fake-server.md#what-llamacpp-sends). The tests compare them with
// that capture.

// Name is what the fake server calls its model and its build.
const Name = "fake-server"

const (
	sseData      = "data: "
	sseEnd       = "\n\n"
	done         = "data: [DONE]\n\n"
	choiceOpen   = `{"choices":[{"finish_reason":null,"index":0,"delta":{`
	roleDelta    = `"role":"assistant","content":null`
	contentKey   = `"content":`
	reasoningKey = `"reasoning_content":`
	choiceClose  = `}}]`
	finishOpen   = `{"choices":[{"finish_reason":"`
	finishClose  = `","index":0,"delta":{}}]`
)

// encode writes value as JSON the way llama.cpp does: no escaping of <, > and &.
func encode(value any) []byte {
	var buffer bytes.Buffer
	encoder := json.NewEncoder(&buffer)
	encoder.SetEscapeHTML(false)
	// The values encoded here are strings, whole numbers and finite fractions, which can't fail.
	_ = encoder.Encode(value)
	return bytes.TrimSuffix(buffer.Bytes(), []byte("\n"))
}

// chunks writes one answer's chunks. Every chunk ends with the same fields, made once.
type chunks struct {
	tail []byte
}

func newChunks(id string, created int64) chunks {
	tail := []byte(`,"created":`)
	tail = strconv.AppendInt(tail, created, 10)
	tail = append(tail, `,"id":"`+id+`","model":"`+Name+`","system_fingerprint":"`+Name+
		`","object":"chat.completion.chunk"}`+sseEnd...)
	return chunks{tail: tail}
}

// role appends the first chunk: the role, and no content yet.
func (c chunks) role(to []byte) []byte {
	to = append(to, sseData+choiceOpen+roleDelta+choiceClose...)
	return append(to, c.tail...)
}

// token appends one token's chunk. key is contentKey or reasoningKey, and text the token as
// JSON.
func (c chunks) token(to []byte, key string, text []byte) []byte {
	to = append(to, sseData+choiceOpen...)
	to = append(to, key...)
	to = append(to, text...)
	to = append(to, choiceClose...)
	return append(to, c.tail...)
}

// finish appends the chunk that says why the answer ended.
func (c chunks) finish(to []byte, reason string) []byte {
	to = append(to, sseData+finishOpen...)
	to = append(to, reason...)
	to = append(to, finishClose...)
	return append(to, c.tail...)
}

// usage is the tokens an answer counts.
type usage struct {
	CompletionTokens    int `json:"completion_tokens"`
	PromptTokens        int `json:"prompt_tokens"`
	TotalTokens         int `json:"total_tokens"`
	PromptTokensDetails struct {
		CachedTokens int `json:"cached_tokens"`
	} `json:"prompt_tokens_details"`
}

// timings is llama.cpp's account of an answer's speed. The fake server works it out from its
// own timetable.
type timings struct {
	CacheN              int     `json:"cache_n"`
	PromptN             int     `json:"prompt_n"`
	PromptMS            float64 `json:"prompt_ms"`
	PromptPerTokenMS    float64 `json:"prompt_per_token_ms"`
	PromptPerSecond     float64 `json:"prompt_per_second"`
	PredictedN          int     `json:"predicted_n"`
	PredictedMS         float64 `json:"predicted_ms"`
	PredictedPerTokenMS float64 `json:"predicted_per_token_ms"`
	PredictedPerSecond  float64 `json:"predicted_per_second"`
}

// usageChunk is a stream's last chunk, when the request asks for the usage.
type usageChunk struct {
	Choices           []struct{} `json:"choices"`
	Created           int64      `json:"created"`
	ID                string     `json:"id"`
	Model             string     `json:"model"`
	SystemFingerprint string     `json:"system_fingerprint"`
	Object            string     `json:"object"`
	Usage             usage      `json:"usage"`
	Timings           timings    `json:"timings"`
}

// message is a whole answer's message.
type message struct {
	Role             string `json:"role"`
	Content          string `json:"content"`
	ReasoningContent string `json:"reasoning_content,omitempty"`
}

// completion is a whole answer.
type completion struct {
	Choices []struct {
		FinishReason string  `json:"finish_reason"`
		Index        int     `json:"index"`
		Message      message `json:"message"`
	} `json:"choices"`
	Created           int64   `json:"created"`
	Model             string  `json:"model"`
	SystemFingerprint string  `json:"system_fingerprint"`
	Object            string  `json:"object"`
	Usage             usage   `json:"usage"`
	ID                string  `json:"id"`
	Timings           timings `json:"timings"`
}

// failed is llama.cpp's error body.
type failed struct {
	Error struct {
		Code    int    `json:"code"`
		Message string `json:"message"`
		Type    string `json:"type"`
	} `json:"error"`
}

func failedWith(code int, kind, text string) []byte {
	var body failed
	body.Error.Code, body.Error.Message, body.Error.Type = code, text, kind
	return encode(body)
}

// per is a divided by b, or 0 when b is 0.
func per(a, b float64) float64 {
	if b == 0 {
		return 0
	}
	return a / b
}
