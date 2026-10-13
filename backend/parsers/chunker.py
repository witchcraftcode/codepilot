"""AST-based code chunker supporting multiple languages."""

from dataclasses import dataclass, field
from pathlib import Path

from parsers.language_utils import detect_language, should_ignore_path


@dataclass
class CodeChunk:
    content: str
    file_path: str
    chunk_type: str  # file, class, function, method
    language: str
    symbol_name: str | None = None
    start_line: int = 1
    end_line: int = 1
    parent_symbol: str | None = None
    metadata: dict = field(default_factory=dict)


class CodeChunker:
    """Hierarchical chunking: Repository → Folder → File → Class → Function → Method."""

    def chunk_repository(self, repo_path: Path) -> list[CodeChunk]:
        chunks: list[CodeChunk] = []
        for file_path in repo_path.rglob("*"):
            if not file_path.is_file() or should_ignore_path(file_path.relative_to(repo_path)):
                continue
            language = detect_language(str(file_path))
            if not language:
                continue
            relative_path = str(file_path.relative_to(repo_path))
            file_chunks = self.chunk_file(file_path, relative_path, language)
            chunks.extend(file_chunks)
        return chunks

    def chunk_file(self, file_path: Path, relative_path: str, language: str) -> list[CodeChunk]:
        try:
            content = file_path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            return []

        if not content.strip():
            return []

        if language == "python":
            return self._chunk_python(content, relative_path, language)
        if language in ("javascript", "typescript"):
            return self._chunk_js_ts(content, relative_path, language)
        if language == "java":
            return self._chunk_java(content, relative_path, language)
        if language == "cpp":
            return self._chunk_cpp(content, relative_path, language)
        if language == "go":
            return self._chunk_go(content, relative_path, language)

        return [self._file_chunk(content, relative_path, language)]

    def _file_chunk(self, content: str, file_path: str, language: str) -> CodeChunk:
        lines = content.count("\n") + 1
        return CodeChunk(
            content=content,
            file_path=file_path,
            chunk_type="file",
            language=language,
            end_line=lines,
        )


    def _chunk_python(
        self,
        content: str,
        file_path: str,
        language: str,
    ) -> list[CodeChunk]:
        import ast

        chunks: list[CodeChunk] = [
            self._file_chunk(content, file_path, language)
        ]

        try:
            tree = ast.parse(content)
        except SyntaxError:
            return chunks

        lines = content.splitlines()

        def add_chunk(
            node: ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef,
            chunk_type: str,
            parent_symbol: str | None = None,
        ) -> None:
            start = node.lineno
            end = node.end_lineno or start

            chunks.append(
                CodeChunk(
                    content="\n".join(lines[start - 1 : end]),
                    file_path=file_path,
                    chunk_type=chunk_type,
                    language=language,
                    symbol_name=node.name,
                    parent_symbol=parent_symbol,
                    start_line=start,
                    end_line=end,
                )
            )

        # Process top-level declarations and direct class methods.
        for node in tree.body:
            if isinstance(node, ast.ClassDef):
                add_chunk(node, "class")

                for item in node.body:
                    if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        add_chunk(item, "method", node.name)

            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                add_chunk(node, "function")

        return chunks


    def _chunk_js_ts(self, content: str, file_path: str, language: str) -> list[CodeChunk]:
        import re

        chunks: list[CodeChunk] = [self._file_chunk(content, file_path, language)]
        lines = content.splitlines()

        class_pattern = re.compile(r"(?:export\s+)?(?:abstract\s+)?class\s+(\w+)")
        func_patterns = [
            re.compile(r"(?:export\s+)?(?:async\s+)?function\s+(\w+)"),
            re.compile(r"(?:export\s+)?const\s+(\w+)\s*=\s*(?:async\s*)?\("),
            re.compile(r"(?:export\s+)?const\s+(\w+)\s*=\s*(?:async\s*)?function"),
        ]
        method_pattern = re.compile(r"(?:async\s+)?(\w+)\s*\([^)]*\)\s*(?::\s*\w+)?\s*\{")

        for i, line in enumerate(lines, 1):
            class_match = class_pattern.search(line)
            if class_match:
                block = self._extract_block(lines, i - 1)
                chunks.append(
                    CodeChunk(
                        content=block,
                        file_path=file_path,
                        chunk_type="class",
                        language=language,
                        symbol_name=class_match.group(1),
                        start_line=i,
                    )
                )
            for pattern in func_patterns:
                match = pattern.search(line)
                if match:
                    block = self._extract_block(lines, i - 1)
                    chunks.append(
                        CodeChunk(
                            content=block,
                            file_path=file_path,
                            chunk_type="function",
                            language=language,
                            symbol_name=match.group(1),
                            start_line=i,
                        )
                    )
                    break

        return chunks

    def _chunk_java(self, content: str, file_path: str, language: str) -> list[CodeChunk]:
        import re

        chunks: list[CodeChunk] = [self._file_chunk(content, file_path, language)]
        lines = content.splitlines()

        class_pattern = re.compile(r"(?:public|private|protected)?\s*(?:static\s+)?(?:abstract\s+)?class\s+(\w+)")
        for i, line in enumerate(lines, 1):
            match = class_pattern.search(line)
            if match:
                block = self._extract_block(lines, i - 1, open_char="{", close_char="}")
                chunks.append(
                    CodeChunk(
                        content=block,
                        file_path=file_path,
                        chunk_type="class",
                        language=language,
                        symbol_name=match.group(1),
                        start_line=i,
                    )
                )
        return chunks

    def _chunk_cpp(self, content: str, file_path: str, language: str) -> list[CodeChunk]:
        import re

        chunks: list[CodeChunk] = [self._file_chunk(content, file_path, language)]
        lines = content.splitlines()

        class_pattern = re.compile(r"class\s+(\w+)")
        for i, line in enumerate(lines, 1):
            match = class_pattern.search(line)
            if match:
                block = self._extract_block(lines, i - 1)
                chunks.append(
                    CodeChunk(
                        content=block,
                        file_path=file_path,
                        chunk_type="class",
                        language=language,
                        symbol_name=match.group(1),
                        start_line=i,
                    )
                )
        return chunks

    def _chunk_go(self, content: str, file_path: str, language: str) -> list[CodeChunk]:
        import re

        chunks: list[CodeChunk] = [self._file_chunk(content, file_path, language)]
        lines = content.splitlines()

        func_pattern = re.compile(r"func\s+(?:\([^)]+\)\s+)?(\w+)")
        for i, line in enumerate(lines, 1):
            match = func_pattern.search(line)
            if match:
                block = self._extract_block(lines, i - 1, open_char="{", close_char="}")
                chunks.append(
                    CodeChunk(
                        content=block,
                        file_path=file_path,
                        chunk_type="function",
                        language=language,
                        symbol_name=match.group(1),
                        start_line=i,
                    )
                )
        return chunks

    def _extract_block(
        self, lines: list[str], start_idx: int, open_char: str = "{", close_char: str = "}"
    ) -> str:
        depth = 0
        block_lines: list[str] = []
        started = False
        for line in lines[start_idx:]:
            block_lines.append(line)
            depth += line.count(open_char) - line.count(close_char)
            if open_char in line:
                started = True
            if started and depth <= 0:
                break
        return "\n".join(block_lines)
