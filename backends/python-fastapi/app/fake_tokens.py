"""The tokens both fakes answer with, read from the contract (contract/README.md#the-fakes)."""

import json
from pathlib import Path

# Where every image and every gate finds the contract (spec/decisions/0011).
TOKENS_FILE = Path("/contract/fake-tokens.json")


def load_tokens(path: Path = TOKENS_FILE) -> tuple[str, ...]:
    """The tokens in `path`, in order. Raises ValueError unless it holds a non-empty JSON list
    of non-empty strings."""
    tokens = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(tokens, list) or not tokens:
        raise ValueError(f"{path} must hold a non-empty JSON list")
    if not all(isinstance(token, str) and token for token in tokens):
        raise ValueError(f"{path} must hold non-empty strings only")
    return tuple(tokens)
