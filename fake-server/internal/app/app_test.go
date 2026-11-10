package app_test

import (
	"bufio"
	"context"
	"errors"
	"io/fs"
	"log/slog"
	"net"
	"net/http"
	"net/http/httptest"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"github.com/fkuhne/api-langs-bench/fake-server/internal/app"
	"github.com/fkuhne/api-langs-bench/fake-server/internal/settings"
	"github.com/fkuhne/api-langs-bench/fake-server/internal/tokens"
)

var quiet = slog.New(slog.DiscardHandler)

func environment(values map[string]string) func(string) (string, bool) {
	return func(name string) (string, bool) {
		value, set := values[name]
		return value, set
	}
}

func listen(t *testing.T) net.Listener {
	t.Helper()
	listener, err := (&net.ListenConfig{}).Listen(context.Background(), "tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	return listener
}

func config(env map[string]string) app.Config {
	return app.Config{LookupEnv: environment(env), TokensFile: tokens.File, Log: quiet}
}

// eventually retries check every 10 ms until it passes, or fails the test after 5 seconds.
func eventually(t *testing.T, check func() error) {
	t.Helper()
	deadline := time.Now().Add(5 * time.Second)
	for {
		err := check()
		if err == nil {
			return
		}
		if time.Now().After(deadline) {
			t.Fatal(err)
		}
		time.Sleep(10 * time.Millisecond)
	}
}

func TestRunServesUntilItsContextEnds(t *testing.T) {
	listener := listen(t)
	ctx, cancel := context.WithCancel(context.Background())
	stopped := make(chan error)
	go func() { stopped <- app.Run(ctx, listener, config(nil)) }()

	eventually(t, func() error { return app.Probe(context.Background(), "http://"+listener.Addr().String()+"/health") })
	cancel()

	if err := <-stopped; err != nil {
		t.Errorf("got %v, want a clean stop", err)
	}
}

func TestAStopEndsAnOpenStreamAtOnce(t *testing.T) {
	listener := listen(t)
	ctx, cancel := context.WithCancel(context.Background())
	stopped := make(chan error)
	// A token a minute: the stream would outlast the test.
	go func() { stopped <- app.Run(ctx, listener, config(map[string]string{"FAKE_TOKEN_GAP_MS": "60000"})) }()
	url := "http://" + listener.Addr().String() + "/v1/chat/completions"
	request, err := http.NewRequestWithContext(context.Background(), http.MethodPost, url,
		strings.NewReader(`{"messages":[],"stream":true}`))
	if err != nil {
		t.Fatal(err)
	}
	response, err := http.DefaultClient.Do(request)
	if err != nil {
		t.Fatal(err)
	}
	defer func() { _ = response.Body.Close() }()
	if _, err := bufio.NewReader(response.Body).ReadString('\n'); err != nil {
		t.Fatalf("no first chunk: %v", err)
	}

	cancel()

	select {
	case err := <-stopped:
		if err != nil {
			t.Errorf("got %v, want a clean stop", err)
		}
	case <-time.After(5 * time.Second):
		t.Error("the stop waited for the open stream")
	}
}

func TestAnInvalidSettingStopsTheStartUp(t *testing.T) {
	err := app.Run(context.Background(), listen(t), config(map[string]string{"FAKE_ANSWER_TOKENS": "0"}))

	if !errors.Is(err, settings.ErrInvalid) {
		t.Errorf("got %v, want ErrInvalid", err)
	}
}

func TestAMissingTokensFileStopsTheStartUp(t *testing.T) {
	c := config(nil)
	c.TokensFile = filepath.Join(t.TempDir(), "missing.json")

	if err := app.Run(context.Background(), listen(t), c); !errors.Is(err, fs.ErrNotExist) {
		t.Errorf("got %v, want a missing file", err)
	}
}

func TestAFailedListenerStopsRun(t *testing.T) {
	listener := listen(t)
	_ = listener.Close()

	if err := app.Run(context.Background(), listener, config(nil)); !errors.Is(err, net.ErrClosed) {
		t.Errorf("got %v, want the listener's error", err)
	}
}

func TestProbeFailsUnlessHealthy(t *testing.T) {
	down := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		w.WriteHeader(http.StatusServiceUnavailable)
	}))
	defer down.Close()

	for name, url := range map[string]string{
		"503":           down.URL,
		"nothing there": "http://127.0.0.1:1",
		"a bad URL":     "http://bad host",
	} {
		if err := app.Probe(context.Background(), url); err == nil {
			t.Errorf("%s: got healthy", name)
		}
	}
}

// Main listens on :8080, which is free in the checks' container.
func TestMainServesAndItsHealthcheckSeesIt(t *testing.T) {
	healthcheck := []string{"server", "healthcheck"}
	if code := app.Main(context.Background(), healthcheck, quiet); code != 1 {
		t.Fatalf("got %d before the start, want 1", code)
	}
	ctx, cancel := context.WithCancel(context.Background())
	exited := make(chan int)
	go func() { exited <- app.Main(ctx, []string{"server"}, quiet) }()

	eventually(t, func() error {
		if app.Main(context.Background(), healthcheck, quiet) != 0 {
			return errors.New("not healthy after 5 seconds")
		}
		return nil
	})
	if code := app.Main(context.Background(), []string{"server"}, quiet); code != 1 {
		t.Errorf("a second server on the same port got %d, want 1", code)
	}
	cancel()

	if code := <-exited; code != 0 {
		t.Errorf("got %d, want 0", code)
	}
}

func TestMainFailsOnAnInvalidSetting(t *testing.T) {
	t.Setenv("FAKE_TOKEN_GAP_MS", "-1")

	if code := app.Main(context.Background(), []string{"server"}, quiet); code != 1 {
		t.Errorf("got %d, want 1", code)
	}
}
