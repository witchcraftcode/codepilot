"""Parse unified diff format into structured changed files."""

import re
from dataclasses import dataclass, field


@dataclass
class DiffHunk:
    old_start: int
    old_count: int
    new_start: int
    new_count: int
    lines: list[tuple[str, str]] = field(default_factory=list)


@dataclass
class ChangedFile:
    file_path: str
    old_path: str | None = None
    status: str = "modified"
    hunks: list[DiffHunk] = field(default_factory=list)

    def added_content(self) -> str:
        lines = []
        for hunk in self.hunks:
            for prefix, content in hunk.lines:
                if prefix == "+":
                    lines.append(content)
        return "\n".join(lines)

    def added_lines_with_numbers(self) -> list[tuple[int, str]]:
        result: list[tuple[int, str]] = []
        for hunk in self.hunks:
            line_num = hunk.new_start
            for prefix, content in hunk.lines:
                if prefix == "+":
                    result.append((line_num, content))
                    line_num += 1
                elif prefix == " ":
                    line_num += 1
        return result

    @property
    def first_new_line(self) -> int:
        for hunk in self.hunks:
            if hunk.new_start:
                return hunk.new_start
        return 1


HUNK_HEADER = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


def parse_unified_diff(diff_text: str) -> list[ChangedFile]:
    """Parse a unified diff into a list of ChangedFile objects."""
    if not diff_text or not diff_text.strip():
        return []

    files: list[ChangedFile] = []
    current: ChangedFile | None = None
    current_hunk: DiffHunk | None = None

    for raw_line in diff_text.splitlines():
        if raw_line.startswith("diff --git"):
            if current is not None:
                files.append(current)
            match = re.search(r"diff --git a/(.+?) b/(.+)", raw_line)
            if match:
                old_path, new_path = match.group(1), match.group(2)
                status = "modified"
                if old_path == "/dev/null":
                    status = "added"
                elif new_path == "/dev/null":
                    status = "deleted"
                current = ChangedFile(
                    file_path=new_path if new_path != "/dev/null" else old_path,
                    old_path=old_path if old_path != "/dev/null" else None,
                    status=status,
                )
            else:
                current = ChangedFile(file_path="unknown")
            current_hunk = None
            continue

        if current is None:
            continue

        if raw_line.startswith("rename from "):
            current.status = "renamed"
            current.old_path = raw_line[len("rename from ") :]
            continue
        if raw_line.startswith("rename to "):
            current.file_path = raw_line[len("rename to ") :]
            continue
        if raw_line.startswith("new file mode"):
            current.status = "added"
            continue
        if raw_line.startswith("deleted file mode"):
            current.status = "deleted"
            continue
        if raw_line.startswith("--- ") or raw_line.startswith("+++ "):
            continue

        hunk_match = HUNK_HEADER.match(raw_line)
        if hunk_match:
            old_start = int(hunk_match.group(1))
            old_count = int(hunk_match.group(2) or 1)
            new_start = int(hunk_match.group(3))
            new_count = int(hunk_match.group(4) or 1)
            current_hunk = DiffHunk(
                old_start=old_start,
                old_count=old_count,
                new_start=new_start,
                new_count=new_count,
            )
            current.hunks.append(current_hunk)
            continue

        if current_hunk is not None and raw_line and raw_line[0] in "+- ":
            current_hunk.lines.append((raw_line[0], raw_line[1:]))

    if current is not None:
        files.append(current)

    return files


def build_context_chunks(changed_files: list[ChangedFile]) -> list[dict]:
    """Convert changed files into context chunks for agent analysis."""
    from parsers.language_utils import detect_language

    chunks: list[dict] = []
    for cf in changed_files:
        if cf.status == "deleted":
            continue
        content = cf.added_content()
        if not content.strip():
            continue
        added_lines = cf.added_lines_with_numbers()
        chunks.append(
            {
                "file_path": cf.file_path,
                "language": detect_language(cf.file_path),
                "content": content,
                "start_line": cf.first_new_line,
                "end_line": added_lines[-1][0] if added_lines else cf.first_new_line,
                "added_lines": [
                    {"line_number": line_number, "content": line}
                    for line_number, line in added_lines
                ],
                "chunk_type": "diff",
                "symbol_name": None,
            }
        )
    return chunks
