"""Reference integrations for popular existing storage layers.

These are NOT imported by default — you should pip-install whichever target
framework you're using and copy / inherit the relevant module. The intent
is to demonstrate idiomatic integration so library users with bespoke
storage don't have to figure it out from scratch.

Available references:
  * ``langgraph`` — wrap a LangGraph checkpointer to share its DB layer
  * ``sqlalchemy`` — wrap a SQLAlchemy async session
  * ``conversation_jsonb`` — embed registry data in an existing
    ``conversations.metadata`` JSONB column (the bridge_agent pattern)

Each module is self-contained and ~30 LOC. Use as a starting point — you'll
typically want to customize transaction boundaries, key naming, etc.
"""
