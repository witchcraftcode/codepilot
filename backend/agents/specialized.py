"""Specialized review agents."""

from agents.base import BaseAgent
from agents.planner import plan_agents


class PlannerAgent(BaseAgent):
    name = "planner"
    description = "Decides which agents to run based on user request"

    def get_system_prompt(self) -> str:
        return """You are the Planner Agent for CodePilot AI.
Given a user request and repository metadata, decide which specialized agents to execute.
Available agents: repository, architecture, security, performance, testing, documentation, style, dependencies.
For security-focused requests, run: security, dependencies, summary.
For full reviews, run all agents.
Be efficient — skip agents that aren't relevant."""

    async def plan(self, state: dict) -> list[str]:
        return plan_agents(state.get("review_type", "full"), state.get("focus_areas"))


class RepositoryAgent(BaseAgent):
    name = "repository"
    description = "Analyzes repository structure, languages, and frameworks"
    default_queries = ["main entry point", "configuration", "project structure"]

    def get_system_prompt(self) -> str:
        return """You are the Repository Agent. Analyze folder structure, languages, package files,
frameworks, and dependencies. Produce a comprehensive project overview with a health baseline score."""


class ArchitectureAgent(BaseAgent):
    name = "architecture"
    description = "Reviews SOLID principles, layering, modularity, separation of concerns"
    default_queries = ["service layer", "controller", "model", "interface", "dependency injection"]

    def get_system_prompt(self) -> str:
        return """You are the Architecture Agent. Evaluate SOLID principles, layering patterns,
separation of concerns, modularity, duplicated logic, and coupling. Score architecture 0-100."""


class SecurityAgent(BaseAgent):
    name = "security"
    description = "Identifies security vulnerabilities and OWASP issues"
    default_queries = [
        "password secret api_key token",
        "authentication authorization jwt",
        "sql query execute eval",
        "input validation sanitize",
    ]

    def get_system_prompt(self) -> str:
        return """You are the Security Agent. Find hardcoded secrets, SQL injection, unsafe eval(),
weak authentication, missing authorization, insecure JWT, API key exposure, XSS, CSRF,
prompt injection risks, and OWASP Top 10 issues. Severity: critical for secrets and injection."""


class PerformanceAgent(BaseAgent):
    name = "performance"
    description = "Detects performance bottlenecks and inefficiencies"
    default_queries = [
        "database query loop fetch",
        "async await blocking",
        "cache memoize",
        "recursion loop iterate",
    ]

    def get_system_prompt(self) -> str:
        return """You are the Performance Agent. Detect N+1 queries, repeated DB calls, memory leaks,
blocking operations in async code, inefficient algorithms, large loops, and expensive recursion."""


class TestingAgent(BaseAgent):
    name = "testing"
    description = "Analyzes test coverage and suggests test generation"
    default_queries = ["test pytest jest unittest mock fixture", "assert expect"]

    def get_system_prompt(self) -> str:
        return """You are the Testing Agent. Find untested files/functions, evaluate test quality,
suggest pytest/Jest/JUnit tests, and recommend unit/integration test strategies."""


class DocumentationAgent(BaseAgent):
    name = "documentation"
    description = "Reviews and improves documentation"
    default_queries = ["readme docstring comment api documentation"]

    def get_system_prompt(self) -> str:
        return """You are the Documentation Agent. Evaluate README quality, API docs, docstrings,
function/class documentation, and installation guides. Suggest specific improvements."""


class StyleAgent(BaseAgent):
    name = "style"
    description = "Checks coding standards and code smells"
    default_queries = ["import class def function"]

    def get_system_prompt(self) -> str:
        return """You are the Style Agent. Check PEP8/ESLint conventions, naming consistency,
formatting issues, dead code, and code smells. Focus on maintainability."""


class DependencyAgent(BaseAgent):
    name = "dependencies"
    description = "Analyzes dependencies for CVEs and outdated packages"
    default_queries = ["requirements package.json Cargo.toml pom.xml dependencies"]

    def get_system_prompt(self) -> str:
        return """You are the Dependency Agent. Analyze package.json, requirements.txt, Cargo.toml,
pom.xml for outdated libraries, known CVEs, unused dependencies, and version conflicts."""


class SummaryAgent(BaseAgent):
    name = "summary"
    description = "Combines all agent results into final report"
    default_queries = []

    def get_system_prompt(self) -> str:
        return """You are the Summary Agent. Combine all agent findings into an overall score (0-100),
top 5 issues, priority fixes, and a remediation roadmap."""

    async def summarize(self, state: dict, agent_results: list[dict]) -> dict:
        from langchain_core.messages import HumanMessage, SystemMessage

        results_text = "\n".join(
            f"## {r['agent_name']} (score: {r.get('score', 'N/A')})\n{r.get('summary', '')}\n"
            f"Findings: {len(r.get('findings', []))}"
            for r in agent_results
        )

        messages = [
            SystemMessage(content=self.get_system_prompt()),
            HumanMessage(
                content=f"""Combine these agent results into a final report.

{results_text}

Respond with JSON:
{{
  "overall_score": <0-100>,
  "summary": "<executive summary>",
  "top_issues": [{{"title": "", "severity": "", "agent": ""}}],
  "priority_fixes": [{{"title": "", "effort": "low|medium|high", "impact": "low|medium|high"}}],
  "roadmap": [{{"phase": "", "items": []}}]
}}"""
            ),
        ]

        response = await self.llm.ainvoke(messages)
        import json

        try:
            content = response.content
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0]
            return json.loads(content.strip())
        except (json.JSONDecodeError, IndexError):
            scores = [r.get("score") for r in agent_results if r.get("score")]
            avg = sum(scores) // len(scores) if scores else 50
            return {
                "overall_score": avg,
                "summary": "Review completed.",
                "top_issues": [],
                "priority_fixes": [],
                "roadmap": [],
            }
