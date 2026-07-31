"""Repository metadata parser for languages, frameworks, and dependencies."""

import ast
import json
import re
from pathlib import Path

from parsers.language_utils import DEPENDENCY_FILES, detect_language, is_dependency_file, should_ignore_path


class RepositoryParser:
    def parse(self, repo_path: Path) -> dict:
        languages: dict[str, int] = {}
        frameworks: set[str] = set()
        dependencies: dict[str, list[str]] = {}
        file_count = 0

        for file_path in repo_path.rglob("*"):
            if not file_path.is_file():
                continue
            rel = file_path.relative_to(repo_path)
            if should_ignore_path(rel):
                continue

            file_count += 1
            lang = detect_language(str(file_path))
            if lang:
                languages[lang] = languages.get(lang, 0) + 1

            if is_dependency_file(file_path.name):
                deps = self._parse_dependency_file(file_path)
                if deps:
                    dependencies[file_path.name] = deps
                    frameworks.update(self._detect_frameworks(deps, file_path.name))

        return {
            "languages": languages,
            "frameworks": sorted(frameworks),
            "dependencies": dependencies,
            "file_count": file_count,
        }

    def parse_structure(self, repo_path: Path) -> dict[str, dict]:
        """Parse repository source files into semantic units grouped by file."""
        files: dict[str, dict] = {}

        supported_languages = {"python", "javascript", "typescript"}
        for file_path in repo_path.rglob("*"):
            if not file_path.is_file():
                continue
            rel = file_path.relative_to(repo_path)
            if should_ignore_path(rel):
                continue

            language = detect_language(str(file_path))
            if language not in supported_languages:
                continue

            file_structure = self._parse_file_structure(file_path, language)
            file_structure["language"] = language
            files[str(rel)] = file_structure

        return {"files": files}

    def _parse_file_structure(self, file_path: Path, language: str) -> dict[str, list[dict]]:
        try:
            content = file_path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            return {"classes": [], "functions": [], "methods": []}

        if language == "python":
            return self._parse_python_file(content)
        return self._parse_js_ts_file(content, language)

    def _parse_python_file(self, content: str) -> dict[str, list[dict]]:
        classes: list[dict] = []
        functions: list[dict] = []
        methods: list[dict] = []

        try:
            tree = ast.parse(content)
        except SyntaxError:
            return {"classes": classes, "functions": functions, "methods": methods}

        for node in tree.body:
            if isinstance(node, ast.ClassDef):
                class_doc = ast.get_docstring(node)
                class_start = node.lineno
                class_end = getattr(node, "end_lineno", class_start)
                class_methods: list[dict] = []
                for item in node.body:
                    if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        method_doc = ast.get_docstring(item)
                        method_start = item.lineno
                        method_end = getattr(item, "end_lineno", method_start)
                        method_content = ast.get_source_segment(content, item) or ""
                        method = {
                            "name": item.name,
                            "docstring": method_doc,
                            "content": method_content,
                            "symbol_type": "method",
                            "parent_class": node.name,
                            "start_line": method_start,
                            "end_line": method_end,
                        }
                        class_methods.append(method.copy())
                        methods.append(method)

                class_content = ast.get_source_segment(content, node) or ""
                classes.append(
                    {
                        "name": node.name,
                        "docstring": class_doc,
                        "content": class_content,
                        "symbol_type": "class",
                        "start_line": class_start,
                        "end_line": class_end,
                        "methods": class_methods,
                    }
                )
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                function_doc = ast.get_docstring(node)
                function_start = node.lineno
                function_end = getattr(node, "end_lineno", function_start)
                function_content = ast.get_source_segment(content, node) or ""
                functions.append(
                    {
                        "name": node.name,
                        "docstring": function_doc,
                        "content": function_content,
                        "symbol_type": "function",
                        "start_line": function_start,
                        "end_line": function_end,
                    }
                )

        return {"classes": classes, "functions": functions, "methods": methods}

    def _parse_js_ts_file(self, content: str, language: str) -> dict[str, list[dict]]:
        classes: list[dict] = []
        functions: list[dict] = []
        methods: list[dict] = []

        lines = content.splitlines()
        class_ranges: list[tuple[int, int]] = []

        class_pattern = re.compile(r"^\s*(?:export\s+)?(?:default\s+)?(?:abstract\s+)?class\s+([A-Za-z_\w]*)")
        function_patterns = [
            re.compile(r"^\s*(?:export\s+)?(?:async\s+)?function\s+([A-Za-z_]\w*)\s*\("),
            re.compile(r"^\s*(?:export\s+)?(?:const|let|var)\s+([A-Za-z_]\w*)\s*=\s*(?:async\s+)?function\s*\("),
            re.compile(r"^\s*(?:export\s+)?(?:const|let|var)\s+([A-Za-z_]\w*)\s*=\s*(?:async\s*)?\([^)]*\)\s*(?::\s*[^=\s]+)?\s*=>"),
        ]
        method_pattern = re.compile(
            r"^\s*(?:public\s+|private\s+|protected\s+|static\s+|async\s+|abstract\s+)*([A-Za-z_]\w*)\s*\([^)]*\)\s*(?::\s*[^\{\s]+)?\s*\{"
        )

        for i, line in enumerate(lines, 1):
            class_match = class_pattern.match(line)
            if not class_match:
                continue

            block, end_line = self._extract_js_block(lines, i - 1)
            class_doc = self._extract_jsdoc(lines, i - 1)
            class_name = class_match.group(1)
            class_methods: list[dict] = []
            class_lines = block.splitlines()

            for offset, class_line in enumerate(class_lines[1:], start=1):
                method_match = method_pattern.match(class_line)
                if method_match:
                    method_name = method_match.group(1)
                    method_line = i + offset
                    method_doc = self._extract_jsdoc(lines, method_line - 1)
                    method_block, method_end = self._extract_js_block(lines, method_line - 1)
                    method = {
                        "name": method_name,
                        "docstring": method_doc,
                        "content": method_block,
                        "symbol_type": "method",
                        "parent_class": class_name,
                        "start_line": method_line,
                        "end_line": method_end,
                    }
                    methods.append(method)
                    class_methods.append(method.copy())

            classes.append(
                {
                    "name": class_name,
                    "docstring": class_doc,
                    "content": block,
                    "symbol_type": "class",
                    "start_line": i,
                    "end_line": end_line,
                    "methods": class_methods,
                }
            )
            class_ranges.append((i, end_line))

        def is_inside_class(line_number: int) -> bool:
            return any(start <= line_number <= end for start, end in class_ranges)

        for i, line in enumerate(lines, 1):
            if is_inside_class(i):
                continue
            for pattern in function_patterns:
                match = pattern.match(line)
                if match:
                    function_name = match.group(1)
                    function_doc = self._extract_jsdoc(lines, i - 1)
                    block, end_line = self._extract_js_block(lines, i - 1)
                    functions.append(
                        {
                            "name": function_name,
                            "docstring": function_doc,
                            "content": block,
                            "symbol_type": "function",
                            "start_line": i,
                            "end_line": end_line,
                        }
                    )
                    break

        return {"classes": classes, "functions": functions, "methods": methods}

    def _extract_jsdoc(self, lines: list[str], start_idx: int) -> str | None:
        idx = start_idx - 1
        while idx >= 0 and not lines[idx].strip():
            idx -= 1
        if idx < 0:
            return None

        line = lines[idx].strip()
        if line.endswith("*/"):
            doc_lines: list[str] = []
            while idx >= 0:
                current = lines[idx].strip()
                doc_lines.append(current)
                if current.startswith("/**") or current.startswith("/*"):
                    break
                idx -= 1
            doc_lines.reverse()
            cleaned = []
            for doc_line in doc_lines:
                doc_line = doc_line.strip()
                if doc_line.startswith("/**"):
                    doc_line = doc_line[3:]
                if doc_line.endswith("*/"):
                    doc_line = doc_line[:-2]
                if doc_line.startswith("*"):
                    doc_line = doc_line[1:]
                cleaned.append(doc_line.strip())
            return "\n".join(line for line in cleaned if line).strip() or None

        if line.startswith("//"):
            comments: list[str] = []
            while idx >= 0 and lines[idx].strip().startswith("//"):
                comments.append(lines[idx].strip()[2:].strip())
                idx -= 1
            comments.reverse()
            return "\n".join(comments).strip() or None

        return None

    def _extract_js_block(self, lines: list[str], start_idx: int) -> tuple[str, int]:
        depth = 0
        block_lines: list[str] = []
        started = False

        for line in lines[start_idx:]:
            block_lines.append(line)
            if "{" in line:
                started = True
                depth += line.count("{") - line.count("}")
            elif started:
                depth += line.count("{") - line.count("}")

            if started and depth <= 0:
                break

        end_line = start_idx + len(block_lines)
        return "\n".join(block_lines), end_line

    def _parse_dependency_file(self, file_path: Path) -> list[str]:
        name = file_path.name
        try:
            content = file_path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            return []

        if name == "package.json":
            try:
                data = json.loads(content)
                deps = list(data.get("dependencies", {}).keys()) + list(data.get("devDependencies", {}).keys())
                return deps
            except json.JSONDecodeError:
                return []

        if name == "requirements.txt":
            return [
                line.split("==")[0].split(">=")[0].strip()
                for line in content.splitlines()
                if line.strip() and not line.startswith("#")
            ]

        if name == "pyproject.toml":
            deps = []
            in_deps = False
            for line in content.splitlines():
                if line.strip().startswith("[") and "dependencies" in line:
                    in_deps = True
                    continue
                if line.strip().startswith("[") and in_deps:
                    break
                if in_deps and "=" in line:
                    deps.append(line.split("=")[0].strip().strip('"'))
            return deps

        if name == "Cargo.toml":
            deps = []
            in_deps = False
            for line in content.splitlines():
                if line.strip() == "[dependencies]":
                    in_deps = True
                    continue
                if line.strip().startswith("[") and in_deps:
                    break
                if in_deps and "=" in line:
                    deps.append(line.split("=")[0].strip())
            return deps

        if name == "go.mod":
            return [
                line.split()[0]
                for line in content.splitlines()
                if line.strip().startswith("require") or (line.strip() and not line.startswith("//") and "v" in line)
            ]

        return []

    def _detect_frameworks(self, deps: list[str], file_name: str) -> set[str]:
        framework_map = {
            "fastapi": "FastAPI",
            "django": "Django",
            "flask": "Flask",
            "react": "React",
            "next": "Next.js",
            "vue": "Vue",
            "angular": "Angular",
            "express": "Express",
            "spring-boot": "Spring Boot",
            "rails": "Rails",
            "gin": "Gin",
            "actix-web": "Actix",
        }
        detected = set()
        for dep in deps:
            dep_lower = dep.lower().replace("_", "-")
            for key, name in framework_map.items():
                if key in dep_lower:
                    detected.add(name)
        return detected
