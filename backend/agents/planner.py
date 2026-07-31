"""Planner logic for deciding which agents to execute."""

REVIEW_TYPE_AGENTS: dict[str, list[str]] = {
    "full": [
        "repository", "architecture", "security", "performance",
        "testing", "documentation", "style", "dependencies",
    ],
    "security": ["repository", "security", "dependencies"],
    "performance": ["repository", "performance", "architecture"],
    "testing": ["repository", "testing"],
    "documentation": ["repository", "documentation"],
    "architecture": ["repository", "architecture", "style"],
    "style": ["repository", "style"],
    "dependencies": ["repository", "dependencies", "security"],
}


def plan_agents(review_type: str = "full", focus_areas: list[str] | None = None) -> list[str]:
    """Determine which agents to run based on review type and focus areas."""
    agents = list(REVIEW_TYPE_AGENTS.get(review_type, REVIEW_TYPE_AGENTS["full"]))

    if focus_areas:
        agents = [a for a in agents if a in focus_areas or a == "repository"]

    if "summary" not in agents:
        agents.append("summary")

    return agents
