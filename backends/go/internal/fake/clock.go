package fake

import (
	"context"
	"time"
)

// Clock is the fake's clock: monotonic time, and a wait until a given time
// (contract/README.md#the-pace).
type Clock interface {
	Now() time.Time
	// SleepUntil waits until deadline, or until ctx ends, and then returns ctx's error.
	SleepUntil(ctx context.Context, deadline time.Time) error
}

// SystemClock is Go's own: time.Now's monotonic reading, and a timer.
type SystemClock struct{}

// Now is time.Now.
func (SystemClock) Now() time.Time { return time.Now() }

// SleepUntil waits until deadline; at once if it has passed, so delays don't add up.
func (SystemClock) SleepUntil(ctx context.Context, deadline time.Time) error {
	delay := time.Until(deadline)
	if delay <= 0 {
		return ctx.Err()
	}
	timer := time.NewTimer(delay)
	defer timer.Stop()
	select {
	case <-ctx.Done():
		return ctx.Err()
	case <-timer.C:
		return nil
	}
}
