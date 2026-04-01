# Runner

::: stroma.runner.NodeHooks

::: stroma.runner.RunConfig

::: stroma.runner.StromaRunner

## Node decorators

Stroma provides two ways to declare a pipeline node:

| Decorator | When to use |
|-----------|-------------|
| `@runner.node("id", input=In, output=Out)` | You already have a `StromaRunner` instance and want the contract registered automatically. |
| `@stroma_node("id", contract)` | You're building the registry manually, testing in isolation, or sharing node definitions across runners. |

Both attach the same `_stroma_node_id` and `_stroma_contract` metadata to the
function. `@runner.node` is syntactic sugar that also calls
`registry.register(...)` for you.

::: stroma.runner.stroma_node

::: stroma.runner.parallel
