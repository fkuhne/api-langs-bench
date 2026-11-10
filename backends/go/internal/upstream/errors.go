package upstream

import (
	"bytes"
	"encoding/json"
	"fmt"
	"net/http"
	"strconv"
	"strings"

	"github.com/fkuhne/api-langs-bench/backends/go/internal/llm"
)

// An upstream's failures as the contract's errors (contract/README.md#the-upstream). The
// mapping is ai-bootstrap's, in its app/core/services.py and app/llm/openai_errors.py.

// service is how the upstream is named in an error's detail.
const service = "The LLM endpoint"

// reasonCharacters is how much of the upstream's own reason an error's detail carries.
const reasonCharacters = 200

// down are the statuses that mean the upstream is down, not that it refused this request.
var down = map[int]bool{
	http.StatusBadGateway:         true,
	http.StatusServiceUnavailable: true,
	http.StatusGatewayTimeout:     true,
	529:                           true,
}

// statusError is the error a failed answer is: rate-limited for a 429; unavailable while the
// upstream is down; any other status a refusal, with its reason.
func statusError(status int, body []byte) *llm.ServiceError {
	switch {
	case status == http.StatusTooManyRequests:
		return &llm.ServiceError{Status: status, Detail: service + " is rate-limiting requests."}
	case down[status]:
		return &llm.ServiceError{
			Status: http.StatusServiceUnavailable,
			Detail: fmt.Sprintf("%s failed with status %d%s", service, status, reason(body)),
		}
	default:
		return &llm.ServiceError{
			Status: http.StatusBadGateway,
			Detail: fmt.Sprintf("%s refused the request with status %d%s", service, status, reason(body)),
		}
	}
}

// streamError is the error an `error` object inside a stream is, by its code. Without a whole
// number as its code, it's a refusal.
func streamError(object json.RawMessage) *llm.ServiceError {
	body := append(append([]byte(`{"error":`), object...), '}')
	var fields struct {
		Code json.RawMessage `json:"code"`
	}
	if json.Unmarshal(object, &fields) == nil {
		if code, err := strconv.Atoi(string(fields.Code)); err == nil {
			return statusError(code, body)
		}
	}
	return &llm.ServiceError{
		Status: http.StatusBadGateway,
		Detail: service + " failed inside its stream" + reason(body),
	}
}

// unreadable means the upstream answered something that isn't the API's answer.
func unreadable() *llm.ServiceError {
	return &llm.ServiceError{
		Status: http.StatusBadGateway,
		Detail: service + " sent an answer the backend can't read.",
	}
}

// reason is the upstream's own reason in an error's body: ": <reason>", or "." when it gives
// none. It reads OpenAI's {"error": {"message": …}}, a plain {"error": …} and {"detail": …}.
func reason(body []byte) string {
	var fields map[string]json.RawMessage
	if json.Unmarshal(body, &fields) != nil {
		return "."
	}
	found, sent := fields["error"]
	if !sent {
		found = fields["detail"]
	}
	var nested struct {
		Message json.RawMessage `json:"message"`
	}
	if bytes.HasPrefix(bytes.TrimSpace(found), []byte("{")) && json.Unmarshal(found, &nested) == nil {
		found = nested.Message
	}
	var message string
	if json.Unmarshal(found, &message) != nil || strings.TrimSpace(message) == "" {
		return "."
	}
	characters := []rune(strings.TrimSpace(message))
	if len(characters) > reasonCharacters {
		characters = characters[:reasonCharacters]
	}
	return ": " + string(characters)
}
