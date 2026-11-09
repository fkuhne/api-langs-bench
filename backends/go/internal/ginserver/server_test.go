package ginserver_test

import (
	"io"
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
