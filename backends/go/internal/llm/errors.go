package llm

import (
	"net/http"
	"slices"
)

// ServiceError is an upstream's failure, with the status the API answers it with
// (contract/README.md#errors). It's ai-bootstrap's ServiceError and its subclasses, as one type.
type ServiceError struct {
	// Status is 429 (rate-limited), 502 (refused), 503 (unavailable) or 504 (timed out).
	Status int
	Detail string
}

func (e *ServiceError) Error() string { return e.Detail }

// ServiceStatuses are the statuses an upstream's failure answers with.
var ServiceStatuses = []int{
	http.StatusTooManyRequests,
	http.StatusBadGateway,
	http.StatusServiceUnavailable,
	http.StatusGatewayTimeout,
}

// IsServiceStatus tells whether status is one of ServiceStatuses.
func IsServiceStatus(status int64) bool {
	return slices.Contains(ServiceStatuses, int(status))
}

// ErrorEvent is the data of an `error` event: the upstream failed after the stream had started.
type ErrorEvent struct {
	Status int    `json:"status"`
	Detail string `json:"detail"`
}

// Event is "error".
func (ErrorEvent) Event() string { return "error" }

// Event is the `error` event that ends a stream this error stopped, with the status the same
// request answers unstreamed.
func (e *ServiceError) Event() ErrorEvent {
	return ErrorEvent{Status: e.Status, Detail: e.Detail}
}
