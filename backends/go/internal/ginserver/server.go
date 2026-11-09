// Package ginserver serves the contract's API with Gin (spec/decisions/0016).
package ginserver

import (
	"errors"
	"log/slog"
	"net/http"

	"github.com/gin-gonic/gin"

	"github.com/fkuhne/api-langs-bench/backends/go/internal/llm"
)

// New returns the contract's four endpoints, under /api, answered by client. The router is
// gin.Default(), with Gin's logger and recovery, and trusts no proxy, as Gin's warning asks:
// none stands in front of it.
func New(client llm.Client) http.Handler {
	router := gin.Default()
	if err := router.SetTrustedProxies(nil); err != nil {
		panic(err) // Unreachable: nil is always a valid list.
	}
	s := &server{llm: client}
	api := router.Group("/api")
	api.GET("/health", s.liveness)
	api.GET("/health/ready", s.readiness)
	api.POST("/chat", s.chat)
	api.POST("/chat/stream", s.chatStream)
	return router
}

type server struct {
	llm llm.Client
}

// message is one message of the conversation, checked by Gin's binding.
type message struct {
	Role    llm.Role `json:"role"    binding:"required,oneof=system user assistant"`
	Content string   `json:"content" binding:"required"`
}

// chatRequest is the conversation so far, and any generation parameters. Other fields are
// ignored.
type chatRequest struct {
	Messages   []message      `json:"messages"   binding:"required,min=1,dive"`
	Parameters llm.Parameters `json:"parameters"`
}

func (r *chatRequest) messages() []llm.Message {
	messages := make([]llm.Message, len(r.Messages))
	for i, m := range r.Messages {
		messages[i] = llm.Message{Role: m.Role, Content: m.Content}
	}
	return messages
}

func (s *server) liveness(c *gin.Context) {
	c.JSON(http.StatusOK, gin.H{"status": "ok"})
}

func (s *server) readiness(c *gin.Context) {
	check, status := "ok", http.StatusOK
	if !s.llm.Ready(c.Request.Context()) {
		check, status = "unavailable", http.StatusServiceUnavailable
	}
	c.JSON(status, gin.H{"status": check, "checks": gin.H{"llm": check}})
}

// chat answers with the whole answer.
func (s *server) chat(c *gin.Context) {
	var request chatRequest
	if err := c.ShouldBindJSON(&request); err != nil {
		c.JSON(http.StatusUnprocessableEntity, gin.H{"detail": err.Error()})
		return
	}
	completion, err := s.llm.Complete(c.Request.Context(), request.messages(), request.Parameters)
	if err != nil {
		fail(c, err)
		return
	}
	c.JSON(http.StatusOK, completion)
}

// chatStream answers with server-sent events, each flushed as soon as it's made. A failure
// after the status has gone out ends the stream with an `error` event.
func (s *server) chatStream(c *gin.Context) {
	var request chatRequest
	if err := c.ShouldBindJSON(&request); err != nil {
		c.JSON(http.StatusUnprocessableEntity, gin.H{"detail": err.Error()})
		return
	}
	c.Header("Content-Type", "text/event-stream")
	c.Header("Cache-Control", "no-cache")
	c.Status(http.StatusOK)
	c.Writer.Flush()
	for part, err := range s.llm.Stream(c.Request.Context(), request.messages(), request.Parameters) {
		if err != nil {
			var service *llm.ServiceError
			if errors.As(err, &service) {
				slog.Warn("a streamed answer ended with an error", "error", err)
				c.SSEvent(service.Event().Event(), service.Event())
				c.Writer.Flush()
			}
			// Otherwise the client has left, and there's no one to tell.
			return
		}
		c.SSEvent(part.Event(), part)
		c.Writer.Flush()
	}
}

// fail answers an upstream's failure with its status, and its message as the detail.
func fail(c *gin.Context, err error) {
	var service *llm.ServiceError
	switch {
	case errors.As(err, &service):
		if service.Status >= http.StatusInternalServerError {
			slog.Warn("the upstream failed", "error", err)
		}
		c.JSON(service.Status, gin.H{"detail": service.Detail})
	case c.Request.Context().Err() != nil:
		// The client has left, and there's no one to answer.
	default:
		slog.Error("an unexpected error", "error", err)
		c.JSON(http.StatusInternalServerError, gin.H{"detail": "Internal Server Error"})
	}
}
