"""Contract definitions and validation for pipeline nodes."""

from typing import Any, Literal

from pydantic import BaseModel, ValidationError


class NodeContract(BaseModel):
    """Schema contract binding a node to its expected input and output types.

    Attributes:
        node_id: Unique identifier for the node this contract governs.
        input_schema: Pydantic model class that incoming state must conform to.
        output_schema: Pydantic model class that outgoing state must conform to.

    Example::

        class Query(BaseModel):
            text: str

        class Result(BaseModel):
            urls: list[str]

        contract = NodeContract(node_id="search", input_schema=Query, output_schema=Result)
    """

    node_id: str
    input_schema: type[BaseModel]
    output_schema: type[BaseModel]


class ContractViolation(Exception):
    """Raised when node input or output fails schema validation.

    Attributes:
        node_id: The node whose contract was violated.
        direction: Whether the violation occurred on ``"input"`` or ``"output"``.
        raw: The raw dict that failed validation.
        errors: List of Pydantic validation error details.
    """

    def __init__(self, node_id: str, direction: Literal["input", "output"], raw: dict[str, Any], errors: list[Any]):
        self.node_id = node_id
        self.direction = direction
        self.raw = raw
        self.errors = errors
        super().__init__(f"Contract violation for {node_id} ({direction})")


class BoundaryValidator:
    """Callable that validates a raw dict against a contract's input or output schema.

    Returns the validated Pydantic model on success, raises
    :class:`ContractViolation` on failure.
    """

    def __call__(self, contract: NodeContract, direction: Literal["input", "output"], raw: dict[str, Any]) -> BaseModel:
        """Validate *raw* against the appropriate schema of *contract*.

        Args:
            contract: The node contract containing the schema.
            direction: ``"input"`` or ``"output"`` — selects which schema to validate against.
            raw: The dict to validate.

        Returns:
            A validated Pydantic model instance.

        Raises:
            ContractViolation: If validation fails.
        """
        schema = contract.input_schema if direction == "input" else contract.output_schema
        try:
            return schema.model_validate(raw)
        except ValidationError as exc:
            raise ContractViolation(contract.node_id, direction, raw, exc.errors()) from exc


class ContractRegistry:
    """Registry mapping node IDs to their contracts with built-in validation.

    Example::

        registry = ContractRegistry()
        registry.register(NodeContract(node_id="search", input_schema=Query, output_schema=Result))

        # Validate raw data against a node's schema
        validated_input = registry.validate_input("search", {"text": "python"})
        validated_output = registry.validate_output("search", {"urls": ["https://..."]})
    """

    def __init__(self) -> None:
        self._contracts: dict[str, NodeContract] = {}
        self._validator = BoundaryValidator()

    def register(self, contract: NodeContract) -> None:
        """Register a contract for a node, replacing any existing contract for that node ID."""
        self._contracts[contract.node_id] = contract

    def get(self, node_id: str) -> NodeContract:
        """Return the contract for *node_id*.

        Raises:
            KeyError: If no contract is registered for *node_id*.
        """
        return self._contracts[node_id]

    def validate_input(self, node_id: str, raw: dict[str, Any]) -> BaseModel:
        """Validate *raw* against the input schema of the contract for *node_id*."""
        contract = self.get(node_id)
        return self._validator(contract, "input", raw)

    def validate_output(self, node_id: str, raw: dict[str, Any]) -> BaseModel:
        """Validate *raw* against the output schema of the contract for *node_id*."""
        contract = self.get(node_id)
        return self._validator(contract, "output", raw)
