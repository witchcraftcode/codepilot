"""Utilities for building LLM review input."""

from graph.state import ReviewState


def build_review_input(state: ReviewState) -> str:
    """
    Returns the correct context depending on review mode.

    Repository review:
        retrieved_context

    Pull request review:
        git diff
    """

    if state.get("pr_mode"):
        current = state.get("current_file")

        if not current:
            return ""

        return f"""Repository:
{state.get("pr_owner")}/{state.get("pr_repo")}

File:
{current["filename"]}

Git Diff:
{current["patch"]}
"""

    chunks = state.get("retrieved_context", [])

    formatted = []

    for chunk in chunks:
        formatted.append(
            f"""File: {chunk.get("file_path")}

{chunk.get("content")}
"""
        )

    return "\n\n---\n\n".join(formatted)