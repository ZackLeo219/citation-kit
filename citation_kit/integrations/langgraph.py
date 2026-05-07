"""LangGraph integration: registry as a state-channel side-car.

LangGraph's checkpointer already persists per-thread state on every
super-step. The cleanest integration is to pass the registry through state
(as a custom channel), letting LangGraph own the persistence — no
double-write, no separate table.

Pattern (most concise — recommended):

    from langgraph.graph import StateGraph
    from typing import TypedDict
    from citation_kit import CitationRegistry

    class State(TypedDict):
        # ... your other channels ...
        citation_registry_data: dict | None      # serialized registry

    async def my_node(state: State, ...):
        registry = CitationRegistry.from_serializable(
            state.get("citation_registry_data")
        )
        # ... use registry, register tool results, run renderer ...
        return {"citation_registry_data": registry.to_serializable()}

    graph = StateGraph(State)
    graph.add_node("my_node", my_node)
    # checkpointer (PostgresSaver / SqliteSaver / etc) auto-persists state

Why not implement RegistryStore against the checkpointer?
  Because checkpointers are per-thread + per-checkpoint, not per-thread
  flat KV. The state-channel path uses LangGraph's existing scoping
  primitives correctly — no impedance mismatch.

If you DO want a RegistryStore-shaped wrapper around a checkpointer (e.g.
because your code has many places that already call ``store.aload`` /
``store.asave``), copy this skeleton and fill in the (un)pickling
specifics for your Saver subclass — but the state-channel path above
is the lower-friction default.
"""
