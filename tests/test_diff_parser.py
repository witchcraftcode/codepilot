"""Tests for unified diff parsing."""

from parsers.diff_parser import ChangedFile, build_context_chunks, parse_unified_diff

SAMPLE_DIFF = """diff --git a/app/auth.py b/app/auth.py
index 1234567..abcdefg 100644
--- a/app/auth.py
+++ b/app/auth.py
@@ -10,6 +10,8 @@ def authenticate(user, password):
     if not user:
         return None
+    API_KEY = "super-secret-key"
+    token = jwt.encode({"sub": user.id}, API_KEY)
     return verify(user, password)

diff --git a/README.md b/README.md
new file mode 100644
index 0000000..1111111
--- /dev/null
+++ b/README.md
@@ -0,0 +1,3 @@
+# My App
+
+Initial readme.
"""


class TestDiffParser:
    def test_parse_unified_diff_returns_changed_files(self):
        files = parse_unified_diff(SAMPLE_DIFF)
        assert len(files) == 2

        auth = files[0]
        assert auth.file_path == "app/auth.py"
        assert auth.status == "modified"
        assert len(auth.hunks) == 1
        assert auth.hunks[0].new_start == 10

    def test_parse_new_file(self):
        files = parse_unified_diff(SAMPLE_DIFF)
        readme = files[1]
        assert readme.file_path == "README.md"
        assert readme.status == "added"

    def test_added_content(self):
        files = parse_unified_diff(SAMPLE_DIFF)
        auth = files[0]
        content = auth.added_content()
        assert 'API_KEY = "super-secret-key"' in content
        assert "jwt.encode" in content

    def test_added_lines_with_numbers(self):
        files = parse_unified_diff(SAMPLE_DIFF)
        auth = files[0]
        lines = auth.added_lines_with_numbers()
        assert lines[0][0] == 12
        assert "API_KEY" in lines[0][1]

    def test_build_context_chunks(self):
        files = parse_unified_diff(SAMPLE_DIFF)
        chunks = build_context_chunks(files)
        assert len(chunks) == 2
        assert chunks[0]["file_path"] == "app/auth.py"
        assert chunks[0]["language"] == "python"
        assert chunks[0]["start_line"] == 10
        assert chunks[0]["end_line"] == 13
        assert chunks[0]["added_lines"] == [
            {"line_number": 12, "content": '    API_KEY = "super-secret-key"'},
            {"line_number": 13, "content": '    token = jwt.encode({"sub": user.id}, API_KEY)'},
        ]

    def test_empty_diff(self):
        assert parse_unified_diff("") == []
        assert parse_unified_diff("   ") == []

    def test_deleted_file(self):
        diff = """diff --git a/old.py b/old.py
deleted file mode 100644
index abc..000 100644
--- a/old.py
+++ /dev/null
@@ -1,2 +0,0 @@
-def old():
-    pass
"""
        files = parse_unified_diff(diff)
        assert len(files) == 1
        assert files[0].status == "deleted"
        chunks = build_context_chunks(files)
        assert len(chunks) == 0
