package fake_test

import (
	"context"
	"errors"
	"testing"
	"time"

	"github.com/fkuhne/api-langs-bench/backends/go/internal/fake"
)

func TestTheSystemClockWaitsUntilTheDeadline(t *testing.T) {
	clock := fake.SystemClock{}
	deadline := clock.Now().Add(5 * time.Millisecond)

	if err := clock.SleepUntil(context.Background(), deadline); err != nil {
		t.Fatal(err)
	}

	if now := clock.Now(); now.Before(deadline) {
		t.Errorf("woke %v early", deadline.Sub(now))
	}
}

func TestAPassedDeadlineGoesAtOnce(t *testing.T) {
	clock := fake.SystemClock{}
	before := time.Now()

	if err := clock.SleepUntil(context.Background(), before.Add(-time.Second)); err != nil {
		t.Fatal(err)
	}

	if waited := time.Since(before); waited > 50*time.Millisecond {
		t.Errorf("waited %v, want no wait", waited)
	}
}

func TestAnEndedContextEndsTheWait(t *testing.T) {
	clock := fake.SystemClock{}
	ctx, cancel := context.WithCancel(context.Background())
	cancel()

	for name, deadline := range map[string]time.Time{
		"in the future": clock.Now().Add(time.Hour),
		"passed":        clock.Now().Add(-time.Second),
	} {
		if err := clock.SleepUntil(ctx, deadline); !errors.Is(err, context.Canceled) {
			t.Errorf("%s: got %v, want context.Canceled", name, err)
		}
	}
}
