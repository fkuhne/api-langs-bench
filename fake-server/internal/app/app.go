// Package app starts the fake server: it reads the settings and the tokens, and serves until
// it's told to stop (spec/decisions/0023).
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

	"github.com/fkuhne/api-langs-bench/fake-server/internal/chat"
	"github.com/fkuhne/api-langs-bench/fake-server/internal/clock"
	"github.com/fkuhne/api-langs-bench/fake-server/internal/settings"
	"github.com/fkuhne/api-langs-bench/fake-server/internal/tokens"
)

// Address is where the fake server listens in its container: llama.cpp's port.
const Address = ":8080"

// HealthURL is what the healthcheck command asks for.
const HealthURL = "http://127.0.0.1:8080/health"

// ShutdownGrace is how long the server gets to close its connections once it's told to stop.
const ShutdownGrace = 10 * time.Second

// Config is what Run needs: where the settings and the tokens come from, and where it logs.
type Config struct {
	LookupEnv  func(string) (string, bool)
	TokensFile string
	Log        *slog.Logger
}

// Main runs the fake server's command, and returns its exit code. With the argument
// "healthcheck", it asks a running server for its health, for Compose; otherwise it serves on
// Address until ctx ends.
func Main(ctx context.Context, args []string, log *slog.Logger) int {
	if len(args) > 1 && args[1] == "healthcheck" {
		if err := Probe(ctx, HealthURL); err != nil {
			log.Error("not healthy", "error", err)
			return 1
		}
		return 0
	}
	// In its container, the server takes connections from Compose's network. Compose publishes
	// it on 127.0.0.1 only (spec/decisions/0008).
	listener, err := (&net.ListenConfig{}).Listen(ctx, "tcp", Address) //nolint:gosec // G102, as above.
	if err != nil {
		log.Error("can't listen", "address", Address, "error", err)
		return 1
	}
	log.Info("listening", "address", Address)
	if err := Run(ctx, listener, Config{LookupEnv: os.LookupEnv, TokensFile: tokens.File, Log: log}); err != nil {
		log.Error("stopped", "error", err)
		return 1
	}
	return 0
}

// Run reads the settings and the tokens, and serves on listener until ctx ends. Then every
// open answer ends at once, as its client had left. An invalid setting stops it before it
// serves.
func Run(ctx context.Context, listener net.Listener, config Config) error {
	defer func() { _ = listener.Close() }()
	s, err := settings.Load(config.LookupEnv)
	if err != nil {
		return err
	}
	loaded, err := tokens.Load(config.TokensFile)
	if err != nil {
		return err
	}
	server := &http.Server{
		Handler: chat.New(s, loaded, clock.System{}, config.Log).Handler(),
		// A slow client can't hold a connection open by sending its headers slowly. There's
		// no write timeout, which would cut a long stream.
		ReadHeaderTimeout: 10 * time.Second,
		// Every request's context ends with ctx, so a stop doesn't wait for open streams.
		BaseContext: func(net.Listener) context.Context { return ctx },
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

// Probe asks url for health, and fails unless it answers 200 within 4 seconds.
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
