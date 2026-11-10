"""The contract, as the evaluation tool reads it (contract/README.md)."""

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

# Where every image and every gate finds the contract (spec/decisions/0011).
CONTRACT_DIR = Path("/contract")

# The base the OpenAPI document's own references, such as `#/components/schemas/Usage`, resolve
# against.
_BASE_URI = "urn:api-langs-bench:contract"

# A fenced block of the contract's page, with its language.
_BLOCK = re.compile(r"^```(\w+)\n(.*?)^```", re.DOTALL | re.MULTILINE)


@dataclass(frozen=True)
class Examples:
    """The examples on the contract's page, in the order it gives them."""

    # The request both chat endpoints take, and its whole answer.
    request: dict[str, Any]
    completion: dict[str, Any]
    # The same request's stream, from the in-process fake, byte for byte.
    stream: bytes
    # A request whose fake fails.
    failing_request: dict[str, Any]


class Contract:
    """The OpenAPI document, the fakes' tokens and the page's examples, with a validator for any
    schema in the document."""

    def __init__(self, directory: Path = CONTRACT_DIR) -> None:
        openapi = (directory / "openapi.yaml").read_text(encoding="utf-8")
        self.document: dict[str, Any] = yaml.safe_load(openapi)
        tokens = (directory / "fake-tokens.json").read_text(encoding="utf-8")
        self.tokens: tuple[str, ...] = tuple(json.loads(tokens))
        resource: Resource[Any] = Resource.from_contents(
            self.document, default_specification=DRAFT202012
        )
        self._registry: Registry[Any] = Registry().with_resource(_BASE_URI, resource)
        self.examples = _examples((directory / "README.md").read_text(encoding="utf-8"))

    def validator(self, pointer: str) -> Draft202012Validator:
        """A validator for the schema at `pointer` in the document, such as
        `#/components/schemas/ChatRequest`, with its references resolved."""
        return Draft202012Validator({"$ref": _BASE_URI + pointer}, registry=self._registry)


def _examples(page: str) -> Examples:
    """The page's examples. Its first two JSON blocks are the request and the whole answer; the
    failing request is the first JSON block that asks for a `fake_error`; its first text block
    is the stream. The page holds other JSON blocks, such as what a backend sends its upstream."""
    blocks: dict[str, list[str]] = {}
    for language, body in _BLOCK.findall(page):
        blocks.setdefault(language, []).append(body)
    examples = [json.loads(body) for body in blocks["json"]]
    request, completion = examples[:2]
    failing_request = next(e for e in examples if "fake_error" in e.get("parameters", {}))
    return Examples(
        request=request,
        completion=completion,
        stream=blocks["text"][0].encode("utf-8"),
        failing_request=failing_request,
    )
