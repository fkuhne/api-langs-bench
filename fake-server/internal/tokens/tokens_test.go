package tokens_test

import (
	"errors"
	"io/fs"
	"os"
	"path/filepath"
	"slices"
	"testing"

	"github.com/fkuhne/api-langs-bench/fake-server/internal/tokens"
)

func TestTheContractsTokensLoadInOrder(t *testing.T) {
	loaded, err := tokens.Load(tokens.File)
	if err != nil {
		t.Fatal(err)
	}

	if len(loaded) != 175 {
		t.Errorf("got %d tokens, want 175", len(loaded))
	}
	if want := []string{"A", " backend", " in"}; !slices.Equal(loaded[:3], want) {
		t.Errorf("got %q first, want %q", loaded[:3], want)
	}
}

func TestAMalformedFileIsRefused(t *testing.T) {
	cases := map[string]string{
		"not a list":      `{"list": ["A"]}`,
		"empty":           `[]`,
		"an empty string": `["A", ""]`,
		"a number":        `["A", 1]`,
	}
	for name, content := range cases {
		t.Run(name, func(t *testing.T) {
			path := filepath.Join(t.TempDir(), "tokens.json")
			if err := os.WriteFile(path, []byte(content), 0o600); err != nil {
				t.Fatal(err)
			}

			if _, err := tokens.Load(path); !errors.Is(err, tokens.ErrMalformed) {
				t.Errorf("got %v, want ErrMalformed", err)
			}
		})
	}
}

func TestAMissingFileIsAnError(t *testing.T) {
	_, err := tokens.Load(filepath.Join(t.TempDir(), "missing.json"))

	if !errors.Is(err, fs.ErrNotExist) {
		t.Errorf("got %v, want a missing file", err)
	}
}
