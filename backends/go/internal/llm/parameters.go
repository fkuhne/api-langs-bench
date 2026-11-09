package llm

import (
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"slices"
	"strings"
)

// Parameters are generation parameters, such as max_tokens, temperature or seed, sent on as
// given. Their numbers are json.Number, which keeps the text, so 5 and 5.0 stay apart.
type Parameters map[string]any

// reserved are the parameters the backend sets itself, which a request can't send.
var reserved = []string{"messages", "model", "stream", "stream_options"}

// ErrReservedParameter means a request sent a parameter the backend sets itself.
var ErrReservedParameter = errors.New("the backend sets these parameters itself")

// ErrParametersNotObject means a request's parameters aren't a JSON object.
var ErrParametersNotObject = errors.New("parameters must be a JSON object")

// UnmarshalJSON reads a JSON object, keeping each number's text, and refuses reserved keys.
func (p *Parameters) UnmarshalJSON(data []byte) error {
	decoder := json.NewDecoder(bytes.NewReader(data))
	decoder.UseNumber()
	var values map[string]any
	if err := decoder.Decode(&values); err != nil {
		return fmt.Errorf("%w: %w", ErrParametersNotObject, err)
	}
	if values == nil {
		return ErrParametersNotObject
	}
	var found []string
	for _, key := range reserved {
		if _, sent := values[key]; sent {
			found = append(found, key)
		}
	}
	if len(found) > 0 {
		slices.Sort(found)
		return fmt.Errorf("%w: %s", ErrReservedParameter, strings.Join(found, ", "))
	}
	*p = values
	return nil
}
