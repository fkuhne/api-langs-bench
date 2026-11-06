package fake_test

import (
	"errors"
	"io/fs"
	"os"
	"path/filepath"
	"slices"
	"testing"

	"github.com/fkuhne/api-langs-bench/backends/go/internal/fake"
)

func TestTheContractsTokensLoadInOrder(t *testing.T) {
	tokens, err := fake.LoadTokens(fake.TokensFile)
	if err != nil {
		t.Fatal(err)
	}

	if len(tokens) != 175 {
		t.Errorf("got %d tokens, want 175", len(tokens))
	}
	if want := []string{"A", " backend", " in"}; !slices.Equal(tokens[:3], want) {
		t.Errorf("got %q first, want %q", tokens[:3], want)
	}
	// The file ends with a paragraph break, so the answer reads on when it wraps around.
	if last := tokens[len(tokens)-1]; last != "\n\n" {
		t.Errorf("got %q last, want a paragraph break", last)
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

			if _, err := fake.LoadTokens(path); !errors.Is(err, fake.ErrMalformedTokens) {
				t.Errorf("got %v, want ErrMalformedTokens", err)
			}
		})
	}
}

func TestAMissingFileIsAnError(t *testing.T) {
	_, err := fake.LoadTokens(filepath.Join(t.TempDir(), "missing.json"))

	if !errors.Is(err, fs.ErrNotExist) {
		t.Errorf("got %v, want a missing file", err)
	}
}
