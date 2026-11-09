// Package nethttp serves the contract's API with the standard library's net/http alone
// (spec/decisions/0016).
package nethttp

import (
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"log/slog"
	"net/http"

	"github.com/fkuhne/api-langs-bench/backends/go/internal/llm"
)

// New returns the contract's four endpoints, under /api, answered by client.
func New(client llm.Client) http.Handler {
	s := &server{llm: client}
	mux := http.NewServeMux()
	mux.HandleFunc("GET /api/health", s.liveness)
	mux.HandleFunc("GET /api/health/ready", s.readiness)
	mux.HandleFunc("POST /api/chat", s.chat)
	mux.HandleFunc("POST /api/chat/stream", s.chatStream)
	return mux
}

type server struct {
	llm llm.Client
}

// chatRequest is the conversation so far, and any generation parameters. Other fields are
// ignored.
type chatRequest struct {
	Messages   []llm.Message  `json:"messages"`
	Parameters llm.Parameters `json:"parameters"`
}

type detail struct {
	Detail string `json:"detail"`
}

type checks struct {
	Status string            `json:"status"`
	Checks map[string]string `json:"checks,omitempty"`
}

func (s *server) liveness(w http.ResponseWriter, _ *http.Request) {
	writeJSON(w, http.StatusOK, checks{Status: "ok"})
}

func (s *server) readiness(w http.ResponseWriter, r *http.Request) {
	check, status := "ok", http.StatusOK
	if !s.llm.Ready(r.Context()) {
		check, status = "unavailable", http.StatusServiceUnavailable
	}
	writeJSON(w, status, checks{Status: check, Checks: map[string]string{"llm": check}})
}

// chat answers with the whole answer.
func (s *server) chat(w http.ResponseWriter, r *http.Request) {
	request, err := decode(r)
	if err != nil {
		writeJSON(w, http.StatusUnprocessableEntity, detail{err.Error()})
		return
	}
	completion, err := s.llm.Complete(r.Context(), request.Messages, request.Parameters)
	if err != nil {
		writeError(w, r, err)
		return
	}
	writeJSON(w, http.StatusOK, completion)
}

// chatStream answers with server-sent events, each flushed as soon as it's made. A failure
// after the status has gone out ends the stream with an `error` event.
func (s *server) chatStream(w http.ResponseWriter, r *http.Request) {
	request, err := decode(r)
	if err != nil {
		writeJSON(w, http.StatusUnprocessableEntity, detail{err.Error()})
		return
	}
	w.Header().Set("Content-Type", "text/event-stream")
	w.Header().Set("Cache-Control", "no-cache")
	w.WriteHeader(http.StatusOK)
	flusher := http.NewResponseController(w)
	if flusher.Flush() != nil {
		return
	}
	for part, err := range s.llm.Stream(r.Context(), request.Messages, request.Parameters) {
		if err != nil {
			var service *llm.ServiceError
			if errors.As(err, &service) {
				slog.Warn("a streamed answer ended with an error", "error", err)
				_ = writeEvent(w, service.Event().Event(), service.Event())
				_ = flusher.Flush()
			}
			// Otherwise the client has left, and there's no one to tell.
			return
		}
		if writeEvent(w, part.Event(), part) != nil || flusher.Flush() != nil {
			return
		}
	}
}

// decode reads the body as a chat request, and checks what JSON's types can't.
func decode(r *http.Request) (chatRequest, error) {
	var request chatRequest
	if err := json.NewDecoder(r.Body).Decode(&request); err != nil {
		return request, err
	}
	if len(request.Messages) == 0 {
		return request, errors.New("messages: one or more are needed")
	}
	for i, message := range request.Messages {
		if !message.Role.Valid() {
			return request, fmt.Errorf("messages[%d].role: must be system, user or assistant", i)
		}
		if message.Content == "" {
			return request, fmt.Errorf("messages[%d].content: must not be empty", i)
		}
	}
	return request, nil
}

// writeEvent writes one server-sent event: its name, and its data as JSON on one line.
func writeEvent(w io.Writer, name string, data any) error {
	body, err := json.Marshal(data)
	if err != nil {
		return err
	}
	_, err = fmt.Fprintf(w, "event: %s\ndata: %s\n\n", name, body)
	return err
}

func writeJSON(w http.ResponseWriter, status int, body any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(body)
}

// writeError answers an upstream's failure with its status, and its message as the detail.
func writeError(w http.ResponseWriter, r *http.Request, err error) {
	var service *llm.ServiceError
	switch {
	case errors.As(err, &service):
		if service.Status >= http.StatusInternalServerError {
			slog.Warn("the upstream failed", "error", err)
		}
		writeJSON(w, service.Status, detail{service.Detail})
	case r.Context().Err() != nil:
		// The client has left, and there's no one to answer.
	default:
		slog.Error("an unexpected error", "error", err)
		writeJSON(w, http.StatusInternalServerError, detail{"Internal Server Error"})
	}
}
