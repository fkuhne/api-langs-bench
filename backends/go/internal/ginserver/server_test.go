package ginserver_test

import (
	"bytes"
	"io"
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/gin-gonic/gin"

	"github.com/fkuhne/api-langs-bench/backends/go/internal/apitest"
	"github.com/fkuhne/api-langs-bench/backends/go/internal/ginserver"
)

func TestTheContract(t *testing.T) {
	gin.SetMode(gin.TestMode)
	gin.DefaultWriter = io.Discard

	apitest.Run(t, ginserver.New)
}

// No backend writes a line per request (spec/decisions/0027). Gin's logger would write one to
// gin.DefaultWriter, even in release mode.
func TestNoLineForEachRequest(t *testing.T) {
	gin.SetMode(gin.ReleaseMode)
	written := &bytes.Buffer{}
	before := gin.DefaultWriter
	gin.DefaultWriter = written
	t.Cleanup(func() { gin.DefaultWriter = before })

	handler := ginserver.New(nil)
	response := httptest.NewRecorder()
	request := httptest.NewRequestWithContext(t.Context(), http.MethodGet, "/api/health", nil)
	handler.ServeHTTP(response, request)

	if response.Code != http.StatusOK {
		t.Fatalf("liveness answered %d", response.Code)
	}
	if written.Len() != 0 {
		t.Errorf("one request wrote %q", written.String())
	}
}
