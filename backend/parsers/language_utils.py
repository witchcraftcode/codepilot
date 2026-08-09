"""Language detection and file type utilities."""

from pathlib import Path

LANGUAGE_EXTENSIONS: dict[str, str] = {
    ".py": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".java": "java",
    ".cpp": "cpp",
    ".cc": "cpp",
    ".cxx": "cpp",
    ".h": "cpp",
    ".hpp": "cpp",
    ".go": "go",
    ".rs": "rust",
    ".rb": "ruby",
    ".php": "php",
    ".cs": "csharp",
    ".swift": "swift",
    ".kt": "kotlin",
    ".scala": "scala",
}

IGNORE_DIRS = {
    "node_modules",
    "venv",
    ".venv",
    "env",
    "dist",
    "build",
    ".git",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    "target",
    "vendor",
    ".next",
    "coverage",
    ".idea",
    ".vscode",
}

IGNORE_FILES = {
    ".DS_Store",
    "package-lock.json",
    "yarn.lock",
    "poetry.lock",
    "Pipfile.lock",
}

DEPENDENCY_FILES = {
    "requirements.txt",
    "pyproject.toml",
    "setup.py",
    "Pipfile",
    "package.json",
    "Cargo.toml",
    "pom.xml",
    "build.gradle",
    "go.mod",
    "Gemfile",
    "composer.json",
}


def detect_language(file_path: str) -> str | None:
    ext = Path(file_path).suffix.lower()
    return LANGUAGE_EXTENSIONS.get(ext)


def should_ignore_path(path: Path) -> bool:
    parts = set(path.parts)
    if parts & IGNORE_DIRS:
        return True
    if path.name in IGNORE_FILES:
        return True
    if path.suffix in {".min.js", ".min.css", ".map", ".lock"}:
        return True
    return False


def is_dependency_file(filename: str) -> bool:
    return filename in DEPENDENCY_FILES
