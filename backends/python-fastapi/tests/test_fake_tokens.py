from pathlib import Path

import pytest

from app.fake.tokens import load_tokens


def test_the_contracts_tokens_load_in_order() -> None:
    tokens = load_tokens()

    assert len(tokens) == 175
    assert tokens[:3] == ("A", " backend", " in")
    # The file ends with a paragraph break, so the answer reads on when it wraps around.
    assert tokens[-1] == "\n\n"


@pytest.mark.parametrize(
    "content",
    [
        pytest.param('{"tokens": ["A"]}', id="not a list"),
        pytest.param("[]", id="empty"),
        pytest.param('["A", ""]', id="an empty token"),
        pytest.param('["A", 1]', id="a number"),
    ],
)
def test_a_malformed_file_is_refused(tmp_path: Path, content: str) -> None:
    path = tmp_path / "tokens.json"
    path.write_text(content, encoding="utf-8")

    with pytest.raises(ValueError, match="must hold"):
        load_tokens(path)
