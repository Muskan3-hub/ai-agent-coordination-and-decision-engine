"""Context builder - assembles every memory source into one prompt block.

This is what makes follow-up intelligence work: the coordinator injects
the rolling conversation summary, the persisted user entities, the
recent turns and (optionally) retrieved project context into every
agent prompt, so "Optimize it", "Explain line 30" or "Give one example"
are understood against everything said before.
"""
from memory.entity_memory import EntityMemory
from memory.short_term_memory import ShortTermMemory
from memory.summary_memory import SummaryMemory

EMPTY = "No previous conversation."


class ContextBuilder:
    """Combine short-term, summary, entity and RAG context for prompts."""

    def __init__(self, short_memory=None, summary_memory=None, entity_memory=None):
        self.short_memory = short_memory or ShortTermMemory()
        self.summary_memory = summary_memory or SummaryMemory()
        self.entity_memory = entity_memory or EntityMemory()

    def build(
        self,
        recent_limit=3,
        with_rag=False,
        rag_context="",
        extra_blocks=None,
    ):
        """Return a single context string for agent prompts."""
        parts = []

        summary = self.summary_memory.get_summary()
        if summary:
            parts.append("## Conversation summary so far\n\n" + summary)

        entities = self.entity_memory.context_block()
        if entities:
            parts.append("## What I remember\n\n" + entities)

        recent = self.short_memory.get_context(limit=recent_limit)
        if recent and recent != EMPTY:
            parts.append("## Recent conversation\n\n" + recent)

        if with_rag and rag_context:
            parts.append("## Relevant project context\n\n" + rag_context)

        if extra_blocks:
            parts.extend(extra_blocks)

        return "\n\n".join(parts) if parts else EMPTY
