// Command nethttp serves the contract's API with the standard library's net/http alone
// (spec/decisions/0016). Run with no argument to serve on :8000, or with "healthcheck" to ask a
// running one whether it's ready.
package main

import (
	"context"
	"os"
	"os/signal"
	"syscall"

	"github.com/fkuhne/api-langs-bench/backends/go/internal/app"
	"github.com/fkuhne/api-langs-bench/backends/go/internal/nethttp"
)

func main() {
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	code := app.Main(ctx, os.Args, nethttp.New)
	stop()
	os.Exit(code)
}
