from typing import Any

from stroma.adapters.base import FrameworkAdapter, LoopAdapter, StepInterceptor, TurnAdapter
from stroma.contracts import NodeContract


def test_framework_adapter_is_runtime_checkable():
    class FakeGraphAdapter:
        def wrap(self, graph: Any) -> Any:
            return graph

        def node_decorator(self, node_id: str, contract: NodeContract) -> Any:
            return lambda fn: fn

    assert isinstance(FakeGraphAdapter(), FrameworkAdapter)


def test_step_interceptor_is_runtime_checkable():
    class FakeStepWrapper:
        def wrap_step(self, step_id: str, func: Any, contract: Any = None) -> Any:
            return func

    assert isinstance(FakeStepWrapper(), StepInterceptor)


def test_loop_adapter_is_runtime_checkable():
    class FakeLoopHook:
        def on_tool_call(self, tool_name: str, args: dict, ctx: Any) -> dict:
            return args

        def on_tool_result(self, tool_name: str, result: Any, ctx: Any) -> Any:
            return result

    assert isinstance(FakeLoopHook(), LoopAdapter)


def test_turn_adapter_is_runtime_checkable():
    class FakeTurnHook:
        def on_turn_start(self, turn_id: str, message: Any, ctx: Any) -> Any:
            return message

        def on_turn_end(self, turn_id: str, result: Any, ctx: Any) -> Any:
            return result

    assert isinstance(FakeTurnHook(), TurnAdapter)


def test_plain_object_is_not_step_interceptor():
    assert not isinstance(object(), StepInterceptor)


def test_plain_object_is_not_loop_adapter():
    assert not isinstance(object(), LoopAdapter)
