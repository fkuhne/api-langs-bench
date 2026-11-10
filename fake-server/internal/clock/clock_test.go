package clock_test

import (
	"context"
	"errors"
	"testing"
	"time"

	"github.com/fkuhne/api-langs-bench/fake-server/internal/clock"
)

func TestTheSystemClockWaitsUntilTheDeadline(t *testing.T) {
	system := clock.System{}
	deadline := system.Now().Add(5 * time.Millisecond)

	if err := system.SleepUntil(context.Background(), deadline); err != nil {
		t.Fatal(err)
	}

	if now := system.Now(); now.Before(deadline) {
		t.Errorf("woke %v early", deadline.Sub(now))
	}
}

func TestAPassedDeadlineGoesAtOnce(t *testing.T) {
	system := clock.System{}
	before := time.Now()

	if err := system.SleepUntil(context.Background(), before.Add(-time.Second)); err != nil {
		t.Fatal(err)
	}

	if waited := time.Since(before); waited > 50*time.Millisecond {
		t.Errorf("waited %v, want no wait", waited)
	}
}

func TestAnEndedContextEndsTheWait(t *testing.T) {
	system := clock.System{}
	ctx, cancel := context.WithCancel(context.Background())
	cancel()

	for name, deadline := range map[string]time.Time{
		"in the future": system.Now().Add(time.Hour),
		"passed":        system.Now().Add(-time.Second),
	} {
		if err := system.SleepUntil(ctx, deadline); !errors.Is(err, context.Canceled) {
			t.Errorf("%s: got %v, want context.Canceled", name, err)
		}
	}
}
