// Package app starts a backend: it reads the settings, makes the LLM client, and serves the
// contract's API until it's told to stop. Both Go backends start the same way
// (spec/decisions/0016).
package app

import (
	"context"
	"errors"
	"fmt"
	"log/slog"
	"net"
	"net/http"
	"os"
	"time"

	"github.com/fkuhne/api-langs-bench/backends/go/internal/fake"
	"github.com/fkuhne/api-langs-bench/backends/go/internal/llm"
	"github.com/fkuhne/api-langs-bench/backends/go/internal/settings"
	"github.com/fkuhne/api-langs-bench/backends/go/internal/upstream"
)

// Address is where every backend listens in its container (spec/decisions/0011).
const Address = ":8000"

// ReadyURL is the readiness the healthcheck command asks for.
const ReadyURL = "http://127.0.0.1:8000/api/health/ready"

// ShutdownGrace is how long open requests get to finish once the backend is told to stop.
const ShutdownGrace = 10 * time.Second

// NewHandler makes a backend's routes, answered by an LLM client.
type NewHandler func(llm.Client) http.Handler

// Config is what Run needs: where the settings and the tokens come from, and the routes.
type Config struct {
	LookupEnv  func(string) (string, bool)
	TokensFile string
	Handler    NewHandler
}

// Main runs a backend's command, and returns its exit code. With the argument
// "healthcheck", it asks a running backend whether it's ready, for Compose; otherwise it serves
// on Address until ctx ends.
func Main(ctx context.Context, args []string, handler NewHandler) int {
	if len(args) > 1 && args[1] == "healthcheck" {
		if err := Probe(ctx, ReadyURL); err != nil {
			slog.Error("not ready", "error", err)
			return 1
		}
		return 0
	}
	// In its container, the backend takes connections from Compose's network, as uvicorn's
	// --host 0.0.0.0 does. Compose publishes it on 127.0.0.1 only (spec/decisions/0008).
	listener, err := (&net.ListenConfig{}).Listen(ctx, "tcp", Address) //nolint:gosec // G102, as above.
	if err != nil {
		slog.Error("can't listen", "address", Address, "error", err)
		return 1
	}
	slog.Info("listening", "address", Address)
	config := Config{LookupEnv: os.LookupEnv, TokensFile: fake.TokensFile, Handler: handler}
	if err := Run(ctx, listener, config); err != nil {
		slog.Error("stopped", "error", err)
		return 1
	}
	return 0
}

// Run reads the settings, makes the LLM client, and serves on listener until ctx ends. Then
// it stops taking requests, and gives open ones ShutdownGrace to finish. An invalid setting
// stops it before it serves.
func Run(ctx context.Context, listener net.Listener, config Config) error {
	defer func() { _ = listener.Close() }()
	s, err := settings.Load(config.LookupEnv)
	if err != nil {
		return err
	}
	client, err := newLLMClient(s, config.TokensFile)
	if err != nil {
		return err
	}
	defer func() { _ = client.Close() }()
	server := &http.Server{
		Handler: config.Handler(client),
		// A slow client can't hold a connection open by sending its headers slowly. There's
		// no write timeout, which would cut a long stream.
		ReadHeaderTimeout: 10 * time.Second,
	}
	served := make(chan error, 1)
	go func() { served <- server.Serve(listener) }()
	select {
	case err := <-served:
		return err
	case <-ctx.Done():
	}
	shutdown, cancel := context.WithTimeout(context.WithoutCancel(ctx), ShutdownGrace)
	defer cancel()
	if err := server.Shutdown(shutdown); err != nil {
		return fmt.Errorf("stopping: %w", err)
	}
	if err := <-served; !errors.Is(err, http.ErrServerClosed) {
		return err
	}
	return nil
}

// newLLMClient makes the client LLM_PROVIDER names: the upstream client, or the in-process
// fake.
func newLLMClient(s settings.Settings, tokensFile string) (llm.Client, error) {
	if s.LLMProvider == settings.ProviderOpenAICompatible {
		return upstream.New(s), nil
	}
	tokens, err := fake.LoadTokens(tokensFile)
	if err != nil {
		return nil, err
	}
	return fake.New(s, tokens, nil), nil
}

// Probe asks url for readiness, and fails unless it answers 200 within 4 seconds.
func Probe(ctx context.Context, url string) error {
	ctx, cancel := context.WithTimeout(ctx, 4*time.Second)
	defer cancel()
	request, err := http.NewRequestWithContext(ctx, http.MethodGet, url, http.NoBody)
	if err != nil {
		return err
	}
	response, err := http.DefaultClient.Do(request)
	if err != nil {
		return err
	}
	defer func() { _ = response.Body.Close() }()
	if response.StatusCode != http.StatusOK {
		return fmt.Errorf("%s answered %s", url, response.Status)
	}
	return nil
}
