// Package chat answers llama.cpp's chat completions with the contract's fake: its tokens, at
// its pace, in llama.cpp's chunks (contract/README.md#the-fake-server, spec/decisions/0023).
package chat

import (
	"context"
	"fmt"
	"io"
	"log/slog"
	"net/http"
	"strings"
	"sync/atomic"
	"time"

	"github.com/fkuhne/api-langs-bench/fake-server/internal/clock"
	"github.com/fkuhne/api-langs-bench/fake-server/internal/settings"
)

// MaxBody is the largest request body read, in bytes.
const MaxBody = 16 << 20

// Server is the fake upstream server's routes.
//
// Token i, counting the reasoning and the answer together, is due at
// start + FAKE_FIRST_TOKEN_MS + i * FAKE_TOKEN_GAP_MS. The start is when the request's body
// has been read.
type Server struct {
	settings settings.Settings
	tokens   []string
	// Each token as JSON, made once.
	quoted [][]byte
	clock  clock.Clock
	log    *slog.Logger
	// How many answers have started, for their ids.
	answers atomic.Uint64
}

// New returns a server that answers with tokens, at the pace s gives, on c. It logs each
// answer a client leaves early to log.
func New(s settings.Settings, tokens []string, c clock.Clock, log *slog.Logger) *Server {
	quoted := make([][]byte, len(tokens))
	for index, token := range tokens {
		quoted[index] = encode(token)
	}
	return &Server{settings: s, tokens: tokens, quoted: quoted, clock: c, log: log}
}

// Handler returns the routes: llama.cpp's chat completions, and its health.
func (s *Server) Handler() http.Handler {
	mux := http.NewServeMux()
	mux.HandleFunc("POST /v1/chat/completions", s.complete)
	mux.HandleFunc("GET /health", health)
	return mux
}

func health(w http.ResponseWriter, _ *http.Request) {
	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	_, _ = io.WriteString(w, `{"status":"ok"}`)
}

// answer is one request being answered.
type answer struct {
	plan
	id      string
	start   time.Time
	created int64
}

func (s *Server) complete(w http.ResponseWriter, r *http.Request) {
	body, err := io.ReadAll(http.MaxBytesReader(w, r.Body, MaxBody))
	if err != nil {
		refuse(w, refused("the body can't be read: %v", err))
		return
	}
	start := s.clock.Now()
	p, err := s.plan(body)
	if err != nil {
		refuse(w, err)
		return
	}
	a := answer{
		plan:    p,
		id:      fmt.Sprintf("chatcmpl-%032x", s.answers.Add(1)),
		start:   start,
		created: start.Unix(),
	}
	if p.stream {
		s.stream(r.Context(), w, a)
	} else {
		s.whole(r.Context(), w, a)
	}
}

// refuse answers 400, as llama.cpp refuses a request.
func refuse(w http.ResponseWriter, err error) {
	text := strings.TrimPrefix(err.Error(), errRefused.Error()+": ")
	fail(w, http.StatusBadRequest, kindInvalidRequest, text)
}

func fail(w http.ResponseWriter, code int, kind, text string) {
	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	w.WriteHeader(code)
	_, _ = w.Write(failedWith(code, kind, text))
}

// failureText is the message of a failure fake_error asked for.
const failureText = "The fake server failed, as fake_error asked"

// stream sends the answer a token at a time. The headers and the role leave with the first
// token, and the finish reason, the usage and [DONE] with the last, as llama.cpp's do.
func (s *Server) stream(ctx context.Context, w http.ResponseWriter, a answer) {
	made := a.tokens()
	if a.failure != nil {
		made = a.failure.at
	}
	out := newChunks(a.id, a.created)
	flusher := http.NewResponseController(w)
	buffer := make([]byte, 0, 1024)
	for index := range made {
		if err := s.clock.SleepUntil(ctx, s.due(a, index)); err != nil {
			s.left(a, index)
			return
		}
		buffer = buffer[:0]
		if index == 0 {
			w.Header().Set("Content-Type", "text/event-stream")
			w.Header().Set("Server", Name)
			w.Header().Set("X-Accel-Buffering", "no")
			buffer = out.role(buffer)
		}
		if index < a.reasoning {
			buffer = out.token(buffer, reasoningKey, s.quote(index))
		} else {
			buffer = out.token(buffer, contentKey, s.quote(index-a.reasoning))
		}
		if index == a.tokens()-1 && a.failure == nil {
			buffer = out.finish(buffer, a.finishReason)
			if a.includeUsage {
				buffer = append(buffer, sseData...)
				buffer = append(buffer, encode(s.usageChunk(a))...)
				buffer = append(buffer, sseEnd...)
			}
			buffer = append(buffer, done...)
		}
		if err := send(w, flusher, buffer); err != nil {
			s.left(a, index)
			return
		}
	}
	if a.failure == nil {
		return
	}
	if err := s.clock.SleepUntil(ctx, s.due(a, made)); err != nil {
		s.left(a, made)
		return
	}
	shown := a.failure.shows
	switch {
	case shown.code == 0:
		// No answer: the upstream that doesn't answer in time. The client leaves first.
		<-ctx.Done()
		s.left(a, made)
	case made == 0:
		// Before the first token, a failure is a plain HTTP error.
		fail(w, shown.code, shown.kind, failureText)
	default:
		buffer = append(buffer[:0], sseData...)
		buffer = append(buffer, failedWith(shown.code, shown.kind, failureText)...)
		buffer = append(buffer, sseEnd...)
		if err := send(w, flusher, buffer); err != nil {
			s.left(a, made)
		}
	}
}

// send writes one or more chunks, and flushes them.
func send(w io.Writer, flusher *http.ResponseController, data []byte) error {
	if _, err := w.Write(data); err != nil {
		return err
	}
	return flusher.Flush()
}

// whole sends the whole answer, at the last token's time.
func (s *Server) whole(ctx context.Context, w http.ResponseWriter, a answer) {
	last := a.tokens() - 1
	if a.failure != nil {
		last = a.failure.at
	}
	if err := s.clock.SleepUntil(ctx, s.due(a, last)); err != nil {
		s.left(a, 0)
		return
	}
	if a.failure != nil {
		shown := a.failure.shows
		if shown.code == 0 {
			<-ctx.Done()
			s.left(a, 0)
			return
		}
		fail(w, shown.code, shown.kind, failureText)
		return
	}
	body := completion{
		Created:           a.created,
		Model:             Name,
		SystemFingerprint: Name,
		Object:            "chat.completion",
		Usage:             a.usage(),
		ID:                a.id,
		Timings:           s.timings(a),
	}
	body.Choices = make([]struct {
		FinishReason string  `json:"finish_reason"`
		Index        int     `json:"index"`
		Message      message `json:"message"`
	}, 1)
	body.Choices[0].FinishReason = a.finishReason
	body.Choices[0].Message = message{
		Role:             "assistant",
		Content:          s.text(a.answer),
		ReasoningContent: s.text(a.reasoning),
	}
	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	w.Header().Set("Server", Name)
	_, _ = w.Write(encode(body))
}

// left logs an answer its client left early: a stream closed before its end, or a request
// that got no answer (R9).
func (s *Server) left(a answer, sent int) {
	s.log.Info("closed early",
		"id", a.id,
		"stream", a.stream,
		"tokens_sent", sent,
		"after_ms", float64(s.clock.Now().Sub(a.start).Microseconds())/1000,
	)
}

func (s *Server) due(a answer, index int) time.Time {
	offset := s.settings.FirstTokenMS + index*s.settings.TokenGapMS
	return a.start.Add(time.Duration(offset) * time.Millisecond)
}

func (s *Server) quote(index int) []byte {
	return s.quoted[index%len(s.quoted)]
}

func (s *Server) text(tokens int) string {
	var text strings.Builder
	for index := range tokens {
		text.WriteString(s.tokens[index%len(s.tokens)])
	}
	return text.String()
}

func (p plan) usage() usage {
	return usage{
		CompletionTokens: p.tokens(),
		PromptTokens:     p.prompt,
		TotalTokens:      p.prompt + p.tokens(),
	}
}

// timings is the answer's speed by the fake's own timetable: the prompt takes the time to
// the first token, and the tokens the gaps between them.
func (s *Server) timings(a answer) timings {
	promptMS := float64(s.settings.FirstTokenMS)
	predictedMS := float64((a.tokens() - 1) * s.settings.TokenGapMS)
	prompt, predicted := float64(a.prompt), float64(a.tokens())
	return timings{
		PromptN:             a.prompt,
		PromptMS:            promptMS,
		PromptPerTokenMS:    per(promptMS, prompt),
		PromptPerSecond:     per(prompt*1000, promptMS),
		PredictedN:          a.tokens(),
		PredictedMS:         predictedMS,
		PredictedPerTokenMS: per(predictedMS, predicted),
		PredictedPerSecond:  per(predicted*1000, predictedMS),
	}
}

func (s *Server) usageChunk(a answer) usageChunk {
	return usageChunk{
		Choices:           []struct{}{},
		Created:           a.created,
		ID:                a.id,
		Model:             Name,
		SystemFingerprint: Name,
		Object:            "chat.completion.chunk",
		Usage:             a.usage(),
		Timings:           s.timings(a),
	}
}
