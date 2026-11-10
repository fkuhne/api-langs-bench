// Command fake-server is the fake upstream server: llama.cpp's chat completions, answered
// with the contract's tokens at the contract's pace (spec/decisions/0023). Run with no
// argument to serve on :8080, or with "healthcheck" to ask a running one for its health.
package main

import (
	"context"
	"log/slog"
	"os"
	"os/signal"
	"syscall"

	"github.com/fkuhne/api-langs-bench/fake-server/internal/app"
)

func main() {
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	// One JSON object on each line, so the evaluation tool can read the answers closed early.
	code := app.Main(ctx, os.Args, slog.New(slog.NewJSONHandler(os.Stdout, nil)))
	stop()
	os.Exit(code)
}
