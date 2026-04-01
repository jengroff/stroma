from typing import Any, Literal

from pydantic import BaseModel, ValidationError


class NodeContract(BaseModel):
    """Schema contract binding a node to its expected input and output types.

    Maps a `node_id` to its `input_schema` and `output_schema` Pydantic model
    classes that state must conform to at each boundary.

    ## Example

    ```python
    class Query(BaseModel):
        text: str

    class Result(BaseModel):
        urls: list[str]

    contract = NodeContract(node_id="search", input_schema=Query, output_schema=Result)
    ```
    """

    node_id: str
    input_schema: type[BaseModel]
    output_schema: type[BaseModel]


class ContractViolation(Exception):
    """Raised when node input or output fails schema validation.

    Carries the `node_id`, `direction` (`"input"` or `"output"`), the `raw`
    dict that failed, and a list of Pydantic validation `errors`.
    """

    def __init__(self, node_id: str, direction: Literal["input", "output"], raw: dict[str, Any], errors: list[Any]):
        self.node_id = node_id
        self.direction = direction
        self.raw = raw
        self.errors = errors
        super().__init__(f"Contract violation for {node_id} ({direction})")

    def __str__(self) -> str:
        error_lines = "; ".join(f"{'.'.join(str(loc) for loc in e['loc'])}: {e['msg']}" for e in self.errors[:5])
        if len(self.errors) > 5:
            error_lines += f"; ... and {len(self.errors) - 5} more"
        return f"Contract violation for '{self.node_id}' ({self.direction})" + (
            f": {error_lines}" if error_lines else ""
        )


class BoundaryValidator:
    """Callable that validates a raw dict against a contract's input or output schema.

    Returns the validated Pydantic model on success, raises
    :class:`ContractViolation` on failure.
    """

    def __call__(self, contract: NodeContract, direction: Literal["input", "output"], raw: dict[str, Any]) -> BaseModel:
        """Validate *raw* against the appropriate schema of *contract*.

        Selects the input or output schema based on *direction* and returns
        a validated Pydantic model instance. Raises `ContractViolation` on
        validation failure.
        """
        schema = contract.input_schema if direction == "input" else contract.output_schema
        try:
            return schema.model_validate(raw)
        except ValidationError as exc:
            raise ContractViolation(contract.node_id, direction, raw, exc.errors()) from exc


class ContractRegistry:
    """Registry mapping node IDs to their contracts with built-in validation.

    ## Example

    ```python
    registry = ContractRegistry()
    registry.register(NodeContract(node_id="search", input_schema=Query, output_schema=Result))

    validated_input = registry.validate_input("search", {"text": "python"})
    validated_output = registry.validate_output("search", {"urls": ["https://..."]})
    ```
    """

    def __init__(self) -> None:
        self._contracts: dict[str, NodeContract] = {}
        self._validator = BoundaryValidator()

    def register(self, contract: NodeContract) -> None:
        """Register a contract for a node, replacing any existing contract for that node ID."""
        self._contracts[contract.node_id] = contract

    def get(self, node_id: str) -> NodeContract:
        """Return the contract for *node_id*, or raise `KeyError` if not registered."""
        return self._contracts[node_id]

    def validate_input(self, node_id: str, raw: dict[str, Any]) -> BaseModel:
        """Validate *raw* against the input schema of the contract for *node_id*."""
        contract = self.get(node_id)
        return self._validator(contract, "input", raw)

    def validate_output(self, node_id: str, raw: dict[str, Any]) -> BaseModel:
        """Validate *raw* against the output schema of the contract for *node_id*."""
        contract = self.get(node_id)
        return self._validator(contract, "output", raw)
