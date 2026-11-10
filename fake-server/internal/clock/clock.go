// Package clock is the fake's clock: monotonic time, and a wait until a given time
// (contract/README.md#the-pace).
package clock

import (
	"context"
	"time"
)

// Clock tells the time, and waits until one.
type Clock interface {
	Now() time.Time
	// SleepUntil waits until deadline, or until ctx ends, and then returns ctx's error.
	SleepUntil(ctx context.Context, deadline time.Time) error
}

// System is Go's own clock: time.Now's monotonic reading, and a timer.
type System struct{}

// Now is time.Now.
func (System) Now() time.Time { return time.Now() }

// SleepUntil waits until deadline; at once if it has passed, so delays don't add up.
func (System) SleepUntil(ctx context.Context, deadline time.Time) error {
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
