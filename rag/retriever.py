"""LangChain retrieval chain built on top of the RAG vector index.

This is a genuine LangChain pipeline (not just imports): the query is
routed through a ``ChatPromptTemplate`` which injects the retrieved
project context + the recent conversation, and the resulting messages
are passed to the model facade (which accepts LangChain message lists).
"""
from langchain_core.prompts import ChatPromptTemplate

RETRIEVAL_PROMPT = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            "You are a precise coding assistant answering questions about a "
            "codebase. Answer using ONLY the retrieved project context below. "
            "If the context does not contain the answer, say so clearly "
            "instead of guessing.\n\n"
            "Relevant project context:\n{context}",
        ),
        (
            "system",
            "Recent conversation (use it to understand what the user means by "
            "follow-up words like 'it', 'this', 'one example'):\n{conversation}",
        ),
        ("human", "{question}"),
    ]
)


def _history_text(history):
    """Normalize a conversation history (dicts or tuples) to plain text."""
    if not history:
        return "No previous conversation."
    parts = []
    for entry in history[-4:]:
        if isinstance(entry, dict):
            role = entry.get("role", "user")
            text = entry.get("message") or entry.get("content") or ""
        elif isinstance(entry, (tuple, list)) and len(entry) >= 2:
            role, text = entry[0], entry[1]
        else:
            role, text = "user", str(entry)
        parts.append(f"{role}: {text}")
    return "\n".join(parts)


class RetrievalChain:
    """Retrieve relevant project context and (optionally) answer with the LLM.

    Usage:
        chain = RetrievalChain(index=VectorIndex(), model=llm)
        chain.answer("Where is the coordinator defined?", history=turns)
    """

    def __init__(self, index=None, model=None):
        from rag.indexer import VectorIndex  # lazy to avoid import cycles

        self.index = index if index is not None else VectorIndex()
        self.model = model
        self.prompt = RETRIEVAL_PROMPT

    def retrieve(self, question, history=None, top_k=4):
        """Retrieval-only mode: return the formatted context block."""
        return self.index.context_for(question, top_k=top_k, history=history)

    def answer(self, question, history=None, top_k=4):
        """Retrieve + generate. Returns context only when no model is set."""
        context = self.retrieve(question, history=history, top_k=top_k)
        if self.model is None:
            return context
        messages = self.prompt.format_messages(
            context=context or "No project context available.",
            conversation=_history_text(history),
            question=question,
        )
        return self.model.ask(messages)
