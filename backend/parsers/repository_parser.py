"""Repository metadata parser for languages, frameworks, and dependencies."""

import json
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
