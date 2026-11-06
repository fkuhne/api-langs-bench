"""The contract, as the evaluation tool reads it (contract/README.md)."""

import json
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


class Contract:
    """The OpenAPI document and the fakes' tokens, with a validator for any schema in it."""

    def __init__(self, directory: Path = CONTRACT_DIR) -> None:
        openapi = (directory / "openapi.yaml").read_text(encoding="utf-8")
        self.document: dict[str, Any] = yaml.safe_load(openapi)
        tokens = (directory / "fake-tokens.json").read_text(encoding="utf-8")
        self.tokens: tuple[str, ...] = tuple(json.loads(tokens))
        resource: Resource[Any] = Resource.from_contents(
            self.document, default_specification=DRAFT202012
        )
        self._registry: Registry[Any] = Registry().with_resource(_BASE_URI, resource)

    def validator(self, pointer: str) -> Draft202012Validator:
        """A validator for the schema at `pointer` in the document, such as
        `#/components/schemas/ChatRequest`, with its references resolved."""
        return Draft202012Validator({"$ref": _BASE_URI + pointer}, registry=self._registry)
