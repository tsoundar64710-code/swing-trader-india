"""Optional local assistant (Phase 8).

Disabled by default. Uses only rule-based lookups against the local SQLite
database — no external LLM calls, no network requests, no secrets.
"""

from swingtrader.ai.assistant import Assistant, AssistantReply

__all__ = ["Assistant", "AssistantReply"]
