"""Specialized review agents."""

from agents.base import BaseAgent
from agents.planner import plan_agents
from app.services.observability import measured_llm_ainvoke


import json
import logging
import re
import time
from pathlib import Path
from typing import Any

try:
    from opentelemetry import trace
except Exception:
    # Fallback tracer
    class DummySpan:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    class DummyTracer:
        def start_as_current_span(self, name):
            return DummySpan()

    trace = DummyTracer()

logger = logging.getLogger(__name__)


class PlannerAgent(BaseAgent):
    name = "planner"
    description = "Decides which agents to run based on user request"

    def get_system_prompt(self) -> str:
        return (
            "You are the Planner Agent for CodePilot AI.\n"
            "Given the user's request and repository metadata, produce a structured plan that lists which specialized agents to run, their priority, brief reason, and any agent-specific parameters.\n"
            "Available agents: repository, architecture, security, performance, testing, documentation, style, dependencies, summary.\n"
            "Return JSON only in the following format:\n"
            "{\n"
            "  \"agents\": [\n"
            "    {\"name\": \"security\", \"priority\": 10, \"reason\": \"user asked about vulnerabilities\", \"params\": {} }\n"
            "  ],\n"
            "  \"summary\": \"Brief plan summary\"\n"
            "}"
        )

    async def plan(self, state: dict) -> dict | list[str]:
        """Create a structured execution plan using the LLM. Returns either a dict (preferred)
        with fields: agents (list of {name, priority, reason, params}), summary; or a fallback list of agent names."""
        tracer = trace.get_tracer(__name__)
        start = time.time()
        with tracer.start_as_current_span("planner.plan"):
            # Build prompt with repository metadata and user request
            metadata = state.get("repo_metadata", {})
            user_request = state.get("user_request") or state.get("review_type", "full")

            prompt = (
                self.get_system_prompt()
                + "\n\nRepository metadata:\n"
                + json.dumps(metadata or {}, indent=2)
                + "\n\nUser request:\n"
                + str(user_request)
                + "\n\nRespond with JSON as specified."
            )

            try:
                from langchain_core.messages import HumanMessage, SystemMessage
            except Exception:
                class HumanMessage:
                    def __init__(self, content: str):
                        self.content = content

                class SystemMessage:
                    def __init__(self, content: str):
                        self.content = content

            # Use deterministic LLM for planning
            try:
                from app.services.llm_factory import get_llm

                llm = get_llm(temperature=0.0, max_tokens=256)
            except Exception:
                class Dummy:
                    async def ainvoke(self, messages):
                        class R:
                            def __init__(self):
                                self.content = json.dumps({
                                    "agents": [
                                        {"name": "repository", "priority": 100, "reason": "always run", "params": {}},
                                        {"name": "summary", "priority": 10, "reason": "summarize results", "params": {}},
                                    ],
                                    "summary": "Fallback plan",
                                })
                        return R()

                llm = Dummy()

            messages = [SystemMessage(content=self.get_system_prompt()), HumanMessage(content=prompt)]

            try:
                resp, _, _, _ = await measured_llm_ainvoke(llm, messages, operation="agent.planner")
                text = getattr(resp, "content", str(resp))
                # attempt to extract JSON block
                if "```json" in text:
                    text = text.split("```json")[1].split("```")[0]
                elif "```" in text and text.strip().startswith("{"):
                    # in case of fenced json
                    text = text.split("```")[1].split("```")[0]
                plan = json.loads(text)
            except Exception as exc:  # pragma: no cover - LLM failures
                logger.exception("Planner LLM failed to produce structured plan: %s", exc)
                # fallback to rule-based planner
                agents = plan_agents(state.get("review_type", "full"), state.get("focus_areas"))
                plan = {"agents": [{"name": a, "priority": 5, "reason": "fallback"} for a in agents], "summary": "fallback"}

            # Validate and normalize plan
            allowed = set(plan_agents().copy()) | {"summary"}
            cleaned_agents = []
            for a in plan.get("agents", []):
                name = a.get("name")
                if not name or name not in allowed:
                    continue
                cleaned_agents.append({
                    "name": name,
                    "priority": int(a.get("priority", 5)),
                    "reason": a.get("reason", ""),
                    "params": a.get("params", {}),
                })

            # Sort by priority
            cleaned_agents.sort(key=lambda x: -x["priority"])
            agent_names = [c["name"] for c in cleaned_agents]

            duration_ms = int((time.time() - start) * 1000)
            logger.info("planner: planned agents=%s duration_ms=%d", agent_names, duration_ms)

            return {"agents": cleaned_agents, "summary": plan.get("summary", ""), "duration_ms": duration_ms}


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

    async def run(self, state: dict) -> dict:
        start = time.time()
        chunks = await self.retrieve_context(state)
        findings = []

        # Aggregate per-file metrics
        file_metrics = {}
        for chunk in chunks:
            path = chunk.get("file_path")
            content = chunk.get("content") or ""
            lang = chunk.get("language") or ""
            metrics = self._analyze_chunk(content, path, lang)
            file_metrics[path] = metrics
            findings.extend(metrics.get("findings", []))

        # Cross-file analyses
        cycles = self._detect_cyclic_dependencies(chunks)
        if cycles:
            findings.append({
                "severity": "critical",
                "title": "Cyclic dependencies detected",
                "description": f"Cyclic import graph among files: {', '.join(sorted(cycles))}",
                "suggestion": "Refactor modules to break cycles, introduce interfaces/abstractions or inversion of control.",
            })

        duplicates = self._detect_code_duplication(chunks)
        for dup in duplicates:
            findings.append({
                "severity": "high",
                "title": "Code duplication",
                "description": f"Similar code found in {dup['a']} and {dup['b']} (similarity={dup['ratio']:.2f})",
                "suggestion": "Extract common code into shared utility or library and reduce duplication.",
            })

        strengths, weaknesses, roadmap = self._synthesize_recommendations(file_metrics, findings)

        duration_ms = int((time.time() - start) * 1000)
        score = self._compute_architecture_score(file_metrics, findings)

        return {
            "agent_name": self.name,
            "architecture_score": score,
            "strengths": strengths,
            "weaknesses": weaknesses,
            "improvement_roadmap": roadmap,
            "findings": findings,
            "duration_ms": duration_ms,
            "tokens_used": 0,
        }

    def _analyze_chunk(self, content: str, file_path: str, language: str) -> dict:
        lines = content.splitlines()
        findings = []
        metrics = {
            "file_path": file_path,
            "language": language,
            "num_lines": len(lines),
            "num_functions": 0,
            "num_classes": 0,
            "avg_function_length": 0,
            "findings": findings,
        }

        # Heuristics per language
        # Count classes and functions and large function/class heuristics
        func_lengths = []
        class_methods_counts = []
        current_class_methods = 0
        in_class = False

        for i, line in enumerate(lines):
            stripped = line.rstrip('\n')
            # detect class/interface headers (python/java/cpp/js)
            if re.search(r"\bclass\b", stripped) or re.search(r"\binterface\b", stripped):
                # close previous class count
                if in_class:
                    class_methods_counts.append(current_class_methods)
                in_class = True
                current_class_methods = 0
                metrics["num_classes"] += 1
            # method inside a class: indentation + def (python) or method signature (js/java/cpp)
            if in_class and re.match(r"^\s+def\s+\w+\(|^\s+\w+\s+\w+\s*\(|^\s*\w+\s*:\s*function\(|^\s+async\s+def\s+", line):
                current_class_methods += 1
            # top-level function (python) or function keyword (js)
            if re.match(r"^def\s+\w+\(|^function\s+\w+\(|^\w+\s+\w+\s*\(.*\)\s*\{", stripped):
                # compute function length by scanning until blank line or next def/class
                metrics["num_functions"] += 1
                length = 0
                for j in range(i + 1, len(lines)):
                    if re.match(r"^\s*$", lines[j]) or re.match(r"^\s*(def |class |function |interface|\w+\s+\w+\s*\(|#)", lines[j]):
                        break
                    length += 1
                func_lengths.append(length)

        # close last class
        if in_class:
            class_methods_counts.append(current_class_methods)

        if func_lengths:
            metrics["avg_function_length"] = sum(func_lengths) / len(func_lengths)
        else:
            metrics["avg_function_length"] = 0
        if class_methods_counts:
            metrics["avg_methods_per_class"] = sum(class_methods_counts) / len(class_methods_counts)
        else:
            metrics["avg_methods_per_class"] = 0

        # Heuristics: large classes/functions
        if metrics["num_classes"] > 0 and metrics["avg_methods_per_class"] > 12:
            findings.append({
                "severity": "high",
                "title": "Large classes / potential Single Responsibility violation",
                "description": f"{metrics['file_path']} has average methods per class = {metrics['avg_methods_per_class']:.1f}",
                "suggestion": "Split large classes into smaller, focused classes following SRP.",
            })

        if metrics["avg_function_length"] and metrics["avg_function_length"] > 120:
            findings.append({
                "severity": "high",
                "title": "Large functions detected",
                "description": f"{metrics['file_path']} has large average function length = {metrics['avg_function_length']:.1f} lines",
                "suggestion": "Refactor long functions into smaller units with clear responsibilities.",
            })

        # Open-closed heuristic: many explicit type checks
        type_checks = sum(1 for l in lines if re.search(r"\b(isinstance|type\(|switch|case)\b", l))
        if type_checks > 4:
            findings.append({
                "severity": "medium",
                "title": "Potential Open/Closed violations",
                "description": "Multiple type-checking or switch/case constructs detected. Consider polymorphism or strategy patterns.",
                "suggestion": "Introduce abstractions or strategy patterns to avoid sprawling conditional logic.",
            })

        # Coupling heuristic: many imports/requires
        imports = [l for l in lines if re.search(r"^\s*(import |from |require\(|#include |using )", l)]
        metrics["num_imports"] = len(imports)
        if metrics["num_imports"] > 15:
            findings.append({
                "severity": "medium",
                "title": "High coupling via imports",
                "description": f"{metrics['file_path']} imports {metrics['num_imports']} modules, which may indicate tight coupling.",
                "suggestion": "Review module boundaries and reduce direct imports by introducing interfaces or facades.",
            })

        return metrics

    def _detect_cyclic_dependencies(self, chunks: list[dict]) -> set:
        # Build simple import graph based on file basenames
        imports_map = {c.get("file_path"): set() for c in chunks}
        for c in chunks:
            fp = c.get("file_path")
            content = c.get("content") or ""
            # python: from X import or import X
            for m in re.findall(r"from\s+([\w\.\-/]+)\s+import", content):
                imports_map[fp].add(m)
            for m in re.findall(r"import\s+([\w\.\-/]+)", content):
                imports_map[fp].add(m)
            # js/ts imports
            for m in re.findall(r"import\s+.*from\s+[\'\"]([\./\w\-]+)[\'\"]", content):
                imports_map[fp].add(m)
            for m in re.findall(r"require\([\'\"]([\./\w\-]+)[\'\"]\)", content):
                imports_map[fp].add(m)

        # Normalize names to basenames present in chunks
        name_map = {p: p for p in imports_map.keys()}
        basename_map = {p.split('/')[-1].split('.')[0]: p for p in imports_map.keys()}

        graph = {p: set() for p in imports_map}
        for p, deps in imports_map.items():
            for d in deps:
                b = d.split('/')[-1].split('.')[0]
                if b in basename_map:
                    graph[p].add(basename_map[b])

        # detect cycles via DFS
        visited = {}
        cycles = set()

        def dfs(node, stack):
            visited[node] = 1
            stack.append(node)
            for nei in graph.get(node, []):
                if visited.get(nei, 0) == 0:
                    dfs(nei, stack)
                elif visited.get(nei) == 1:
                    # found cycle
                    cycles.update(stack[stack.index(nei):])
            stack.pop()
            visited[node] = 2

        for n in graph:
            if visited.get(n, 0) == 0:
                dfs(n, [])

        return cycles

    def _detect_code_duplication(self, chunks: list[dict]) -> list:
        # pairwise similarity using SequenceMatcher
        from difflib import SequenceMatcher

        results = []
        for i in range(len(chunks)):
            for j in range(i + 1, len(chunks)):
                a = chunks[i]
                b = chunks[j]
                ratio = SequenceMatcher(None, a.get("content") or "", b.get("content") or "").ratio()
                if ratio > 0.75:
                    results.append({"a": a.get("file_path"), "b": b.get("file_path"), "ratio": ratio})
        return results

    def _synthesize_recommendations(self, file_metrics: dict, findings: list) -> tuple:
        strengths = []
        weaknesses = []
        roadmap = []

        # strengths: files with small functions and few imports
        for p, m in file_metrics.items():
            if m.get("avg_function_length", 0) < 30 and m.get("num_imports", 0) < 5:
                strengths.append({"file": p, "reason": "Small functions and low coupling"})

        for f in findings:
            weaknesses.append({"title": f.get("title"), "description": f.get("description")})

        # build roadmap: prioritized fixes
        if any(f.get("title") == "Cyclic dependencies detected" for f in findings):
            roadmap.append({"priority": "P0", "action": "Break cyclic dependencies by introducing interfaces or inversion of control."})
        if any(f.get("title") == "Code duplication" for f in findings) or any(f.get("title") == "Code duplication" for f in findings):
            roadmap.append({"priority": "P1", "action": "Extract duplicated code into shared libraries and centralize utilities."})
        if any(f.get("title") == "Large classes / potential Single Responsibility violation" for f in findings):
            roadmap.append({"priority": "P1", "action": "Split large classes into smaller, cohesive classes per SRP."})
        if any(f.get("title") == "Large functions detected" for f in findings):
            roadmap.append({"priority": "P2", "action": "Refactor long functions into smaller units with single responsibility."})

        # generic maintainability improvements
        roadmap.append({"priority": "P3", "action": "Add module-level documentation, define clear layer boundaries, and add integration tests to validate module contracts."})

        return strengths, weaknesses, roadmap

    def _compute_architecture_score(self, file_metrics: dict, findings: list) -> int:
        score = 100
        for f in findings:
            sev = f.get("severity", "medium")
            if sev == "critical":
                score -= 30
            elif sev == "high":
                score -= 20
            elif sev == "medium":
                score -= 10
            elif sev == "low":
                score -= 5
        # penalize many imports and large files
        for p, m in file_metrics.items():
            if m.get("num_imports", 0) > 20:
                score -= 5
            if m.get("num_lines", 0) > 2000:
                score -= 10
        return max(0, score)


class SecurityAgent(BaseAgent):
    name = "security"
    description = "Identifies security vulnerabilities and OWASP issues"
    default_queries = [
        "password secret api_key token",
        "authentication authorization jwt",
        "sql query execute eval",
        "input validation sanitize",
        "subprocess os.system eval exec",
        "csrf xss script innerHTML",
        "prompt injection openai prompt user_input",
    ]

    def get_system_prompt(self) -> str:
        return """You are the Security Agent. Find hardcoded secrets, SQL injection, command injection, unsafe eval(), weak authentication, missing authorization, insecure JWT, API exposure, XSS, CSRF, prompt injection, and OWASP Top 10 issues. Use retrieved repository context only."""

    async def run(self, state: dict) -> dict:
        chunks = await self.retrieve_context(state)
        findings = []

        for chunk in chunks:
            file_path = chunk.get("file_path")
            language = chunk.get("language")
            content = chunk.get("content") or ""
            base_line = int(chunk.get("start_line") or 1)
            findings.extend(self._analyze_chunk(content, file_path, base_line, language))

        score = self._compute_score(findings)
        summary = self._build_summary(findings)

        return {
            "agent_name": self.name,
            "score": score,
            "findings": findings,
            "summary": summary,
            "tokens_used": 0,
            "duration_ms": 0,
        }

    def _analyze_chunk(self, content: str, file_path: str, base_line: int, language: str | None) -> list[dict]:
        lines = content.splitlines()
        findings = []
        for check in [
            self._find_hardcoded_secret,
            self._find_sql_injection,
            self._find_command_injection,
            self._find_unsafe_eval,
            self._find_jwt_issue,
            self._find_missing_authentication,
            self._find_missing_authorization,
            self._find_xss,
            self._find_csrf,
            self._find_prompt_injection,
        ]:
            findings.extend(check(lines, file_path, base_line, language))
        return findings

    def _make_finding(self, severity: str, file_path: str, line: int, title: str, description: str, fix: str, confidence: float) -> dict:
        return {
            "severity": severity,
            "file_path": file_path,
            "line_number": line,
            "title": title,
            "description": description,
            "suggestion": fix,
            "confidence": round(confidence, 2),
        }

    def _find_hardcoded_secret(self, lines, file_path, base_line, language):
        findings = []
        secret_names = ["password", "pass", "secret", "api_key", "token", "access_key", "private_key"]
        for idx, line in enumerate(lines, start=1):
            stripped = line.strip()
            if any(name in stripped.lower() for name in secret_names) and ("=" in stripped or ":" in stripped):
                if re.search(r"['\"]{3}.*['\"]{3}", stripped):
                    continue
                if re.search(r"[\"\'`].+?[\"\'`]|\\btrue\\b|\\bfalse\\b", stripped, re.IGNORECASE):
                    findings.append(self._make_finding(
                        "critical",
                        file_path,
                        base_line + idx - 1,
                        "Hardcoded secret detected",
                        f"The code contains a secret-like identifier and a literal value: {stripped}",
                        "Move secrets to environment variables or a secrets manager and do not store them in source code.",
                        0.95,
                    ))
        return findings

    def _find_sql_injection(self, lines, file_path, base_line, language):
        findings = []
        for idx, line in enumerate(lines, start=1):
            if re.search(r"\b(execute|executemany|query|prepare)\s*\(", line) and re.search(r"\+|%\s*[\w(]|format\(|f\"|f'", line):
                findings.append(self._make_finding(
                    "critical",
                    file_path,
                    base_line + idx - 1,
                    "Potential SQL injection",
                    "A database query is constructed with string interpolation or concatenation, which can allow attacker-controlled input to alter SQL semantics.",
                    "Use parameterized queries or ORM query builders instead of string formatting when constructing SQL.",
                    0.9,
                ))
            elif re.search(r"\bselect\b.*\bfrom\b", line, re.IGNORECASE) and re.search(r"\{.*\}|\+|format\(|f\"|f'", line):
                findings.append(self._make_finding(
                    "high",
                    file_path,
                    base_line + idx - 1,
                    "SQL injection risk in query string",
                    "SQL query contains interpolated or concatenated values that may include user input.",
                    "Use parameter binding instead of building SQL with string interpolation.",
                    0.85,
                ))
        return findings

    def _find_command_injection(self, lines, file_path, base_line, language):
        findings = []
        for idx, line in enumerate(lines, start=1):
            if re.search(r"\b(subprocess\.Popen|subprocess\.run|os\.system|popen|shell=\s*True)\b", line):
                if re.search(r"\+|%\(|format\(|f\"|f'", line):
                    findings.append(self._make_finding(
                        "critical",
                        file_path,
                        base_line + idx - 1,
                        "Potential command injection",
                        "A shell command is executed with interpolated or concatenated input, which can allow arbitrary command execution.",
                        "Avoid using shell commands with untrusted input and use safe APIs instead.",
                        0.9,
                    ))
        return findings

    def _find_unsafe_eval(self, lines, file_path, base_line, language):
        findings = []
        for idx, line in enumerate(lines, start=1):
            if re.search(r"\b(eval|exec|compile)\s*\(", line):
                findings.append(self._make_finding(
                    "high",
                    file_path,
                    base_line + idx - 1,
                    "Unsafe dynamic code execution",
                    "This code uses eval/exec/compile, which may execute attacker-controlled expressions.",
                    "Avoid dynamic evaluation of code; use explicit logic or safer parsing libraries.",
                    0.85,
                ))
        return findings

    def _find_jwt_issue(self, lines, file_path, base_line, language):
        findings = []
        for idx, line in enumerate(lines, start=1):
            if "jwt.decode" in line:
                if "verify=False" in line:
                    findings.append(self._make_finding(
                        "critical",
                        file_path,
                        base_line + idx - 1,
                        "Insecure JWT validation",
                        "JWT validation is disabled by passing verify=False.",
                        "Enable JWT signature verification and specify allowed algorithms.",
                        0.95,
                    ))
                elif "algorithms" not in line:
                    findings.append(self._make_finding(
                        "high",
                        file_path,
                        base_line + idx - 1,
                        "Missing JWT algorithm validation",
                        "JWT decode is called without explicitly specifying allowed algorithms.",
                        "Pass the algorithms parameter to jwt.decode to enforce expected signing methods.",
                        0.8,
                    ))
        return findings

    def _find_missing_authentication(self, lines, file_path, base_line, language):
        findings = []
        auth_decorators = ["login_required", "authenticate", "auth_required", "Depends(get_current_user)", "@jwt_required"]
        route_patterns = [r"@app\.route", r"@router\.", r"def .*\(.*request", r"def .*\(.*self.*\)"]
        for idx, line in enumerate(lines, start=1):
            if any(re.search(pat, line) for pat in route_patterns):
                block = "\n".join(lines[max(0, idx - 3): idx + 3])
                if not any(token in block for token in auth_decorators):
                    findings.append(self._make_finding(
                        "high",
                        file_path,
                        base_line + idx - 1,
                        "Missing authentication guard",
                        "A route or handler appears without an authentication check.",
                        "Require authentication for this endpoint by using decorators, middleware, or explicit validation.",
                        0.8,
                    ))
        return findings

    def _find_missing_authorization(self, lines, file_path, base_line, language):
        findings = []
        auth_patterns = [r"if .*\.role", r"if .*\.is_admin", r"has_role", r"is_admin"]
        auth_tokens = ["authorize", "permission", "role", "is_admin", "has_role"]
        for idx, line in enumerate(lines, start=1):
            if any(re.search(pat, line) for pat in auth_patterns):
                block = "\n".join(lines[max(0, idx - 3): idx + 3])
                if not any(token in block for token in auth_tokens):
                    findings.append(self._make_finding(
                        "medium",
                        file_path,
                        base_line + idx - 1,
                        "Missing authorization checks",
                        "The endpoint may accept authenticated users without verifying authorization levels.",
                        "Add explicit role or permission checks to protect this resource.",
                        0.7,
                    ))
        return findings

    def _find_xss(self, lines, file_path, base_line, language):
        findings = []
        xss_patterns = [r"\.innerHTML", r"dangerouslySetInnerHTML", r"document\.write", r"response\.write\(", r"innerText"]
        for idx, line in enumerate(lines, start=1):
            if any(re.search(pat, line) for pat in xss_patterns):
                findings.append(self._make_finding(
                    "high",
                    file_path,
                    base_line + idx - 1,
                    "Potential cross-site scripting (XSS)",
                    "Code is injecting HTML or script into a page or DOM element, which may allow unsanitized input to execute.",
                    "Sanitize user-controlled content before rendering it in HTML or use safe templating.",
                    0.85,
                ))
        return findings

    def _find_csrf(self, lines, file_path, base_line, language):
        findings = []
        for idx, line in enumerate(lines, start=1):
            if "csrf_exempt" in line or ("CSRF" in line and "disabled" in line):
                findings.append(self._make_finding(
                    "high",
                    file_path,
                    base_line + idx - 1,
                    "CSRF protection disabled or missing",
                    "CSRF protection appears disabled or not enforced for this handler.",
                    "Enable CSRF protection and require anti-forgery tokens for state-changing requests.",
                    0.85,
                ))
        return findings

    def _find_prompt_injection(self, lines, file_path, base_line, language):
        findings = []
        for idx, line in enumerate(lines, start=1):
            if re.search(r"prompt\s*=|messages\s*=|system_prompt\s*=", line) and re.search(r"\+|format\(|f\"|f'", line):
                findings.append(self._make_finding(
                    "high",
                    file_path,
                    base_line + idx - 1,
                    "Potential prompt injection",
                    "A prompt or message payload is built using string interpolation, which can allow untrusted input to alter LLM behavior.",
                    "Use structured prompt construction and avoid directly embedding raw user input into prompts.",
                    0.8,
                ))
        return findings

    def _compute_score(self, findings):
        if not findings:
            return 95
        score = 100
        for f in findings:
            severity = f.get("severity", "medium")
            weight = {"critical": 30, "high": 20, "medium": 10, "low": 5, "info": 2}.get(severity, 10)
            score -= weight
        return max(0, score)

    def _build_summary(self, findings):
        if not findings:
            return "No security issues were detected in the retrieved repository context."
        counts = {}
        for f in findings:
            counts[f["severity"]] = counts.get(f["severity"], 0) + 1
        parts = [f"{cnt} {sev}" for sev, cnt in counts.items()]
        return "Detected " + ", ".join(parts) + " security-related findings in retrieved context."


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

    async def run(self, state: dict) -> dict:
        start = time.time()
        chunks = await self.retrieve_context(state)
        findings = []
        metrics = {
            "files_analyzed": 0,
            "n_plus_one": 0,
            "blocking_io": 0,
            "large_loops": 0,
            "inefficient_algorithms": 0,
            "memory_leaks": 0,
            "redundant_allocations": 0,
            "recursive_bottlenecks": 0,
        }

        for chunk in chunks:
            fp = chunk.get("file_path")
            lang = chunk.get("language")
            content = chunk.get("content") or ""
            metrics["files_analyzed"] += 1
            fnds = self._analyze_performance_chunk(content, fp, lang)
            for f in fnds:
                t = f.get("type")
                if t and t in metrics:
                    metrics[t] += 1
            findings.extend(fnds)

        duration_ms = int((time.time() - start) * 1000)

        # Build a human-friendly summary
        summary = {
            "total_findings": len(findings),
            "by_type": {k: metrics[k] for k in metrics if k != "files_analyzed"},
            "files_analyzed": metrics["files_analyzed"],
        }

        return {
            "agent_name": self.name,
            "performance_score": max(0, 100 - (metrics["n_plus_one"] * 10 + metrics["inefficient_algorithms"] * 8 + metrics["blocking_io"] * 5)),
            "findings": findings,
            "performance_metrics": summary,
            "duration_ms": duration_ms,
            "tokens_used": 0,
        }

    def _analyze_performance_chunk(self, content: str, file_path: str, language: str) -> list:
        lines = content.splitlines()
        findings = []

        # Detect N+1: loop followed by DB call inside
        loop_indices = [i for i, l in enumerate(lines) if re.match(r"^\s*(for |while )", l)]
        for idx in loop_indices:
            # look ahead a few lines for DB calls
            window = lines[idx: idx + 8]
            for j, l in enumerate(window, start=idx + 1):
                if re.search(r"\b(execute|executemany|query|fetchall|fetchone|session\.query|db\.query|cursor\.execute)\b", l):
                    findings.append(self._make_performance_finding(
                        "high",
                        file_path,
                        idx + 1,
                        "Possible N+1 database queries",
                        "Database calls detected inside a loop which may indicate N+1 queries.",
                        "Batch database access or use joins/preloads to avoid per-item queries.",
                        "high",
                        "O(n*m) - depends on loop and query",
                        "n_plus_one",
                    ))
                    break

        # Detect blocking I/O in async contexts or use of known blocking calls
        if re.search(r"async\s+def|async\s+function", content):
            for i, l in enumerate(lines, start=1):
                if re.search(r"\b(time\.sleep|requests\.|urllib\.|socket\.|open\(|subprocess\.)\b", l) and "await" not in l:
                    findings.append(self._make_performance_finding(
                        "medium",
                        file_path,
                        i,
                        "Blocking I/O in async context",
                        "Blocking I/O call found inside an async function without awaiting an async equivalent.",
                        "Use asynchronous libraries (httpx, aiofiles) or run blocking calls in threadpool executors.",
                        "medium",
                        "O(k)",
                        "blocking_io",
                    ))

        # Detect large loops: long body or nested loops
        for idx in loop_indices:
            # estimate loop body size
            body_len = 0
            for l in lines[idx + 1: idx + 1 + 200]:
                if re.match(r"^\s*(for |while |def |class )", l):
                    break
                body_len += 1
            if body_len > 100:
                findings.append(self._make_performance_finding(
                    "medium",
                    file_path,
                    idx + 1,
                    "Large loop body",
                    f"Loop starting at line {idx+1} has a large body ({body_len} lines) which may be slow.",
                    "Refactor loop body, extract helper functions, and consider streaming or vectorized operations.",
                    "medium",
                    "O(n)",
                    "large_loops",
                ))

        # Detect nested loops (heuristic for O(n^2))
        nested = 0
        for i, l in enumerate(lines):
            if re.match(r"^\s*(for |while )", l):
                # look ahead for inner loop within next 20 lines
                for inner in lines[i + 1: i + 20]:
                    if re.match(r"^\s*(for |while )", inner):
                        nested += 1
                        findings.append(self._make_performance_finding(
                            "high",
                            file_path,
                            i + 1,
                            "Nested loops (potential O(n^2))",
                            "Nested loop detected which may lead to quadratic time complexity.",
                            "Consider using hashing, sets, or algorithms that avoid nested iteration.",
                            "high",
                            "O(n^2)",
                            "inefficient_algorithms",
                        ))
                        break

        # Detect redundant allocations inside loops
        for i, l in enumerate(lines, start=1):
            if re.search(r"(list\(|\[\]|dict\(|set\(|new\s+Array\(|Array\()", l) and re.search(r"for |while", '\n'.join(lines[max(0, i-3): i+3])):
                findings.append(self._make_performance_finding(
                    "low",
                    file_path,
                    i,
                    "Redundant allocations in loop",
                    "A new collection appears to be allocated inside a loop which can be moved outside the loop.",
                    "Allocate reusable structures outside the loop or reuse buffers.",
                    "low",
                    "O(n)",
                    "redundant_allocations",
                ))

        # Detect potential memory leaks: growing global or persistent collections
        for i, l in enumerate(lines, start=1):
            if re.search(r"\bappend\(|\.push\(|setdefault\(|dict\[|\]\s*=\s*\{|\badd\(", l):
                # heuristic: appends at module level or long-lived list usage
                context = '\n'.join(lines[max(0, i-5): i+5])
                if not re.search(r"def |class |function", context):
                    findings.append(self._make_performance_finding(
                        "medium",
                        file_path,
                        i,
                        "Possible memory accumulation",
                        "A collection is being appended or mutated at module scope which may grow unbounded over time.",
                        "Ensure bounded caches, use LRU caches, or persist to disk for large datasets.",
                        "medium",
                        "O(n)",
                        "memory_leaks",
                    ))

        # Detect recursive bottlenecks: direct recursion with no memoization
        for m in re.finditer(r"def\s+(\w+)\s*\(|function\s+(\w+)\s*\(|(\w+)\s*:\s*function", content):
            name = m.group(1) or m.group(2) or m.group(3)
            if name:
                # find function block text
                func_pattern = re.compile(rf"def\s+{name}.*:|function\s+{name}.*\(")
                if re.search(func_pattern, content):
                    # if function calls itself and no memo/cache obvious
                    if re.search(rf"\b{name}\s*\(", content) and not re.search(r"lru_cache|memoize|cache", content):
                        findings.append(self._make_performance_finding(
                            "high",
                            file_path,
                            1,
                            "Recursive function without memoization",
                            f"Function {name} appears recursive and may cause exponential time without memoization.",
                            "Add memoization or convert to iterative DP to avoid exponential recursion.",
                            "high",
                            "O(2^n) possibly",
                            "recursive_bottlenecks",
                        ))

        return findings

    def _make_performance_finding(self, severity, file_path, line, title, description, suggestion, estimated_impact, time_complexity, ftype):
        return {
            "severity": severity,
            "file_path": file_path,
            "line_number": line,
            "title": title,
            "description": description,
            "suggested_optimization": suggestion,
            "estimated_impact": estimated_impact,
            "time_complexity": time_complexity,
            "type": ftype,
        }


class TestingAgent(BaseAgent):
    name = "testing"
    description = "Analyzes test coverage and suggests test generation"
    default_queries = ["test pytest jest unittest mock fixture", "assert expect"]

    def get_system_prompt(self) -> str:
        return """You are the Testing Agent. Find untested files/functions, evaluate test quality,
suggest pytest/Jest/JUnit tests, and recommend unit/integration test strategies."""

    async def run(self, state: dict) -> dict:
        start = time.time()
        chunks = await self.retrieve_context(state)
        findings = []
        artifacts = []
        coverage_recommendations = []
        files = {c.get("file_path") for c in chunks if c.get("file_path")}
        test_files = [f for f in files if "/tests/" in f or f.startswith("test_") or f.endswith("_test.py") or "spec" in f.lower()]

        functions = [c for c in chunks if c.get("chunk_type") in ("function", "method")]
        endpoints = [c for c in chunks if self._is_api_endpoint(c)]

        if not test_files:
            coverage_recommendations.append({
                "title": "No test suite detected",
                "description": "There are no existing test files in the retrieved repository context.",
                "suggestion": "Add a dedicated tests/ folder and start with unit tests for core logic.",
                "impact": "high",
            })
            artifacts.append({
                "type": "test_plan",
                "path": "tests/README.md",
                "content": self._build_test_plan(state),
                "description": "Starter test plan and recommended test file structure.",
            })

        for func in functions:
            if self._needs_unit_test(func, test_files):
                artifact = self._build_unit_test_stub(func)
                artifacts.append(artifact)
                findings.append({
                    "severity": "medium",
                    "category": "testing",
                    "title": "Unit test suggested",
                    "description": f"Add a unit test for {func.get('symbol_name')} in {func.get('file_path')}",
                    "file_path": func.get("file_path"),
                    "line_number": func.get("start_line"),
                    "suggestion": "Create a focused unit test covering happy and edge cases.",
                })

        for endpoint in endpoints:
            artifact = self._build_integration_test_stub(endpoint)
            artifacts.append(artifact)
            findings.append({
                "severity": "high",
                "category": "testing",
                "title": "Integration test suggested",
                "description": f"Add an integration test for endpoint in {endpoint.get('file_path')}",
                "file_path": endpoint.get("file_path"),
                "line_number": endpoint.get("start_line"),
                "suggestion": "Test the request/response flow and critical business paths.",
            })
            coverage_recommendations.append({
                "title": "Endpoint coverage",
                "description": "Some API endpoints are not backed by integration tests.",
                "suggestion": "Add integration tests for these endpoints to validate end-to-end behavior.",
                "impact": "high",
            })

        if not functions and not endpoints:
            findings.append({
                "severity": "low",
                "category": "testing",
                "title": "Limited code coverage signals",
                "description": "No testable functions or endpoints were found in the retrieved context.",
                "file_path": None,
                "line_number": None,
                "suggestion": "Review more repository files or expand retrieval to cover library code.",
            })

        if not coverage_recommendations:
            coverage_recommendations.append({
                "title": "Review coverage targets",
                "description": "Ensure you cover both unit and integration tests for critical paths.",
                "suggestion": "Aim for 70-80% coverage on core modules and provide regression tests for API flows.",
                "impact": "medium",
            })

        duration_ms = int((time.time() - start) * 1000)
        score = max(0, 100 - len(findings) * 8)
        summary = f"Suggested {len(findings)} test improvements with {len(artifacts)} generated test artifacts."

        return {
            "agent_name": self.name,
            "score": score,
            "findings": findings,
            "summary": summary,
            "generated_artifacts": artifacts,
            "export_package": artifacts,
            "coverage_recommendations": coverage_recommendations,
            "duration_ms": duration_ms,
            "tokens_used": 0,
        }

    def _needs_unit_test(self, func: dict, test_files: list[str]) -> bool:
        name = func.get("symbol_name") or ""
        if not name:
            return False
        if func.get("file_path") and ("test_" in func.get("file_path") or "spec" in func.get("file_path", "")):
            return False
        # skip trivial accessors
        if re.match(r"^(get|set|is|has)_", name):
            return False
        return True

    def _build_unit_test_stub(self, func: dict) -> dict:
        file_path = func.get("file_path", "unknown")
        name = func.get("symbol_name") or "function"
        test_path = f"tests/test_{Path(file_path).stem}.py"
        content = f"""import pytest

from {Path(file_path).stem} import {name}


def test_{name}_behavior():
    # TODO: replace with concrete inputs and expected outputs
    result = {name}(None)
    assert result is not None
"""
        return {
            "type": "unit_test",
            "path": test_path,
            "content": content,
            "description": f"Generated unit test skeleton for {name}.",
        }

    def _build_integration_test_stub(self, endpoint: dict) -> dict:
        file_path = endpoint.get("file_path", "unknown")
        test_path = f"tests/test_{Path(file_path).stem}_integration.py"
        content = f"""import pytest

# TODO: implement integration test for endpoint defined in {file_path}

def test_endpoint_flow():
    # setup mock request and expected response
    assert True
"""
        return {
            "type": "integration_test",
            "path": test_path,
            "content": content,
            "description": f"Generated integration test scaffold for endpoint in {file_path}.",
        }

    def _build_test_plan(self, state: dict) -> str:
        langs = state.get("repo_metadata", {}).get("languages", {})
        frameworks = state.get("repo_metadata", {}).get("frameworks", [])
        lines = ["# Test Plan\n"]
        lines.append("## Goal\nEnsure core logic and API flows are covered by unit and integration tests.\n")
        if frameworks:
            lines.append(f"## Frameworks\nDetected frameworks: {', '.join(frameworks)}\n")
        if langs:
            lines.append(f"## Languages\nDetected languages: {', '.join(langs)}\n")
        lines.append("## Recommended test structure\n- tests/unit/ for unit tests\n- tests/integration/ for end-to-end scenarios\n- tests/mock_data/ for sample fixtures\n")
        return "\n".join(lines)

    def _is_api_endpoint(self, chunk: dict) -> bool:
        content = chunk.get("content", "")
        if re.search(r"@app\.route|@router\.|router\.(get|post|put|delete)|fetch\(|axios\.|express\(|flask\.|FastAPI\(|app\.get\(|app\.post\(|rest_controller", content):
            return True
        return False


class DocumentationAgent(BaseAgent):
    name = "documentation"
    description = "Reviews and improves documentation"
    default_queries = ["readme docstring comment api documentation"]

    def get_system_prompt(self) -> str:
        return """You are the Documentation Agent. Evaluate README quality, API docs, docstrings,
function/class documentation, and installation guides. Suggest specific improvements."""

    async def run(self, state: dict) -> dict:
        start = time.time()
        chunks = await self.retrieve_context(state)
        findings = []
        artifacts = []
        repo_meta = state.get("repo_metadata", {})
        readme_present = any(c.get("file_path", "").lower().endswith("readme.md") for c in chunks)

        if not readme_present:
            readme_content = self._build_readme(repo_meta)
            artifacts.append({
                "type": "readme",
                "path": "README.md",
                "content": readme_content,
                "description": "Generated README with installation, usage, and contribution guidance.",
            })
            findings.append({
                "severity": "high",
                "category": "documentation",
                "title": "Missing README",
                "description": "No README.md was found in the retrieved repository context.",
                "file_path": None,
                "line_number": None,
                "suggestion": "Add a README.md with installation, usage, and project overview.",
            })

        for chunk in chunks:
            if chunk.get("chunk_type") in ("function", "method", "class"):
                if not self._has_documentation(chunk):
                    doc_stub = self._generate_doc_stub(chunk)
                    artifacts.append({
                        "type": "docstring",
                        "path": chunk.get("file_path"),
                        "content": doc_stub,
                        "description": f"Suggested documentation for {chunk.get('symbol_name') or 'code segment' }.",
                    })
                    findings.append({
                        "severity": "medium",
                        "category": "documentation",
                        "title": "Missing code documentation",
                        "description": f"{chunk.get('symbol_name')} in {chunk.get('file_path')} has no visible docstring or comments.",
                        "file_path": chunk.get("file_path"),
                        "line_number": chunk.get("start_line"),
                        "suggestion": "Add a summary and parameter descriptions for this symbol.",
                    })

            if self._is_api_endpoint(chunk) and not self._has_api_doc(chunk):
                api_doc = self._build_api_doc_stub(chunk)
                artifacts.append({
                    "type": "api_doc",
                    "path": "API.md",
                    "content": api_doc,
                    "description": f"Generated API documentation entry for endpoint in {chunk.get('file_path')}.",
                })
                findings.append({
                    "severity": "medium",
                    "category": "documentation",
                    "title": "Missing API documentation",
                    "description": f"API endpoint in {chunk.get('file_path')} lacks documented request and response examples.",
                    "file_path": chunk.get("file_path"),
                    "line_number": chunk.get("start_line"),
                    "suggestion": "Document API routes and provide example payloads.",
                })

        if not artifacts:
            findings.append({
                "severity": "low",
                "category": "documentation",
                "title": "Documentation review completed",
                "description": "No immediate documentation gaps were detected in the retrieved context.",
                "file_path": None,
                "line_number": None,
                "suggestion": "Consider adding README and API docs if repository is public-facing.",
            })

        duration_ms = int((time.time() - start) * 1000)
        score = max(0, 100 - len(findings) * 5)
        summary = f"Generated {len(artifacts)} documentation artifacts and identified {len(findings)} improvement opportunities."

        return {
            "agent_name": self.name,
            "score": score,
            "findings": findings,
            "summary": summary,
            "generated_artifacts": artifacts,
            "export_package": artifacts,
            "documentation_score": score,
            "duration_ms": duration_ms,
            "tokens_used": 0,
        }

    def _has_documentation(self, chunk: dict) -> bool:
        content = chunk.get("content", "")
        if chunk.get("language") == "python":
            return re.search(r"^[ \t]*('{3}|\"{3})", content, re.MULTILINE) is not None
        return re.search(r"/\*\*|//|#", content) is not None

    def _generate_doc_stub(self, chunk: dict) -> str:
        symbol = chunk.get("symbol_name") or "symbol"
        kind = chunk.get("chunk_type")
        return f"""{symbol}

{symbol} is a {kind} used in this repository.

Parameters:
- ...

Returns:
- ...
"""

    def _has_api_doc(self, chunk: dict) -> bool:
        return "API" in chunk.get("content", "") or "swagger" in chunk.get("content", "").lower()

    def _build_api_doc_stub(self, chunk: dict) -> str:
        endpoint = chunk.get("symbol_name") or "endpoint"
        return f"""### {endpoint}

- Path: TODO
- Method: TODO
- Description: Describe endpoint behavior.
- Request: JSON body example
- Response: JSON response example
"""

    def _build_readme(self, repo_meta: dict) -> str:
        languages = repo_meta.get("languages", {})
        frameworks = repo_meta.get("frameworks", [])
        dependencies = repo_meta.get("dependencies", [])
        lines = ["# Project Overview", "", "## Introduction", "A generated README for this repository.", ""]
        if frameworks:
            lines.append(f"## Frameworks\n{', '.join(frameworks)}")
            lines.append("")
        if languages:
            lines.append(f"## Languages\n{', '.join(languages.keys())}")
            lines.append("")
        lines.append("## Installation")
        if "python" in languages:
            lines.append("```bash\npip install -r requirements.txt\n```")
        if "javascript" in languages or "typescript" in languages:
            lines.append("```bash\nnpm install\n```")
        lines.append("")
        lines.append("## Usage")
        lines.append("Describe how to run the application and any examples.")
        lines.append("")
        lines.append("## Contributing")
        lines.append("Describe contribution and testing guidelines.")
        return "\n".join(lines)

    def _is_api_endpoint(self, chunk: dict) -> bool:
        content = chunk.get("content", "")
        return bool(re.search(r"@app\.route|@router\.|router\.(get|post|put|delete)|fetch\(|axios\.|express\(|flask\.|FastAPI\(|app\.get\(|app\.post\(|rest_controller", content))


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
        try:
            from langchain_core.messages import HumanMessage, SystemMessage
        except Exception:
            from agents.base import HumanMessage, SystemMessage

        await self._ensure_llm()
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
  "security_score": <0-100>,
  "architecture_score": <0-100>,
  "performance_score": <0-100>,
  "testing_score": <0-100>,
  "documentation_score": <0-100>,
  "dependency_score": <0-100>,
  "top_issues": [{{"title": "", "severity": "", "agent": ""}}],
  "priority_fixes": [{{"title": "", "effort": "low|medium|high", "impact": "low|medium|high"}}],
  "roadmap": [{{"phase": "", "items": []}}],
  "estimated_effort": "<estimated engineering effort>",
  "executive_summary": "<concise executive summary>"
}}"""
            ),
        ]

        response, _, _, _ = await measured_llm_ainvoke(self._llm, messages, operation="agent.summary")
        import json

        try:
            content = response.content
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0]
            parsed = json.loads(content.strip())
        except (json.JSONDecodeError, IndexError):
            parsed = self._fallback_summary(agent_results)

        parsed = self._normalize_summary(parsed, agent_results)
        return parsed

    def _fallback_summary(self, agent_results: list[dict]) -> dict:
        scores = [r.get("score") for r in agent_results if r.get("score") is not None]
        avg = sum(scores) // len(scores) if scores else 50
        return {
            "overall_score": avg,
            "summary": "Review completed.",
            "security_score": next((r.get("score") for r in agent_results if r.get("agent_name") == "security"), None),
            "architecture_score": next((r.get("architecture_score") or r.get("score") for r in agent_results if r.get("agent_name") == "architecture"), None),
            "performance_score": next((r.get("performance_score") or r.get("score") for r in agent_results if r.get("agent_name") == "performance"), None),
            "testing_score": next((r.get("score") for r in agent_results if r.get("agent_name") == "testing"), None),
            "documentation_score": next((r.get("documentation_score") or r.get("score") for r in agent_results if r.get("agent_name") == "documentation"), None),
            "dependency_score": next((r.get("score") for r in agent_results if r.get("agent_name") == "dependencies"), None),
            "top_issues": [],
            "priority_fixes": [],
            "roadmap": [],
            "estimated_effort": self._estimate_effort(agent_results),
            "executive_summary": "Review completed with a balanced focus on security, architecture, performance, testing, and documentation.",
        }

    def _normalize_summary(self, parsed: dict, agent_results: list[dict]) -> dict:
        normalized = {
            "overall_score": parsed.get("overall_score") or self._fallback_summary(agent_results)["overall_score"],
            "summary": parsed.get("executive_summary") or parsed.get("summary") or "Review completed.",
            "security_score": parsed.get("security_score") or next((r.get("score") for r in agent_results if r.get("agent_name") == "security"), None),
            "architecture_score": parsed.get("architecture_score") or next((r.get("architecture_score") or r.get("score") for r in agent_results if r.get("agent_name") == "architecture"), None),
            "performance_score": parsed.get("performance_score") or next((r.get("performance_score") or r.get("score") for r in agent_results if r.get("agent_name") == "performance"), None),
            "testing_score": parsed.get("testing_score") or next((r.get("score") for r in agent_results if r.get("agent_name") == "testing"), None),
            "documentation_score": parsed.get("documentation_score") or next((r.get("documentation_score") or r.get("score") for r in agent_results if r.get("agent_name") == "documentation"), None),
            "dependency_score": parsed.get("dependency_score") or next((r.get("score") for r in agent_results if r.get("agent_name") == "dependencies"), None),
            "top_issues": parsed.get("top_issues") or [],
            "priority_fixes": parsed.get("priority_fixes") or [],
            "roadmap": parsed.get("roadmap") or [],
            "estimated_effort": parsed.get("estimated_effort") or self._estimate_effort(agent_results),
            "executive_summary": parsed.get("executive_summary") or parsed.get("summary") or "Review completed.",
        }
        return normalized

    def _estimate_effort(self, agent_results: list[dict]) -> str:
        total_findings = sum(len(r.get("findings", [])) for r in agent_results)
        critical = sum(1 for r in agent_results for f in r.get("findings", []) if f.get("severity") == "critical")
        high = sum(1 for r in agent_results for f in r.get("findings", []) if f.get("severity") == "high")
        if critical >= 3 or total_findings > 20:
            return "4-6 weeks"
        if high >= 5 or total_findings > 10:
            return "2-4 weeks"
        if total_findings > 0:
            return "1-2 weeks"
        return "3-7 days"
