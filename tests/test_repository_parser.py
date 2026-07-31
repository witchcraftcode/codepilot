import tempfile
from pathlib import Path

from parsers.repository_parser import RepositoryParser


def test_python_repository_parser_extracts_semantic_units():
    parser = RepositoryParser()
    code = '''
"""Module docstring."""

class MyClass:
    """Class docstring."""

    def method_one(self):
        """Method docstring."""
        return True


def top_level_function():
    """Function docstring."""
    return False
'''

    with tempfile.TemporaryDirectory() as tmp:
        repo_path = Path(tmp)
        file_path = repo_path / "test.py"
        file_path.write_text(code, encoding="utf-8")

        structure = parser.parse_structure(repo_path)
        assert "test.py" in structure["files"]

        file_data = structure["files"]["test.py"]
        assert file_data["language"] == "python"
        assert len(file_data["classes"]) == 1
        assert len(file_data["functions"]) == 1
        assert len(file_data["methods"]) == 1

        class_data = file_data["classes"][0]
        assert class_data["name"] == "MyClass"
        assert class_data["docstring"] == "Class docstring."
        assert class_data["methods"][0]["name"] == "method_one"
        assert class_data["methods"][0]["docstring"] == "Method docstring."

        function_data = file_data["functions"][0]
        assert function_data["name"] == "top_level_function"
        assert function_data["docstring"] == "Function docstring."


def test_javascript_repository_parser_extracts_semantic_units():
    parser = RepositoryParser()
    code = '''
/**
 * Service class description.
 */
export class Service {
    /**
     * Fetch user data.
     */
    async fetchData() {
        return [];
    }
}

/**
 * Top-level helper.
 */
export function helper() {
    return 42;
}
'''

    with tempfile.TemporaryDirectory() as tmp:
        repo_path = Path(tmp)
        file_path = repo_path / "service.js"
        file_path.write_text(code, encoding="utf-8")

        structure = parser.parse_structure(repo_path)
        assert "service.js" in structure["files"]

        file_data = structure["files"]["service.js"]
        assert file_data["language"] == "javascript"
        assert len(file_data["classes"]) == 1
        assert len(file_data["functions"]) == 1
        assert len(file_data["methods"]) == 1

        class_data = file_data["classes"][0]
        assert class_data["name"] == "Service"
        assert "Service class description." in class_data["docstring"]
        assert class_data["methods"][0]["name"] == "fetchData"
        assert "Fetch user data." in class_data["methods"][0]["docstring"]

        function_data = file_data["functions"][0]
        assert function_data["name"] == "helper"
        assert "Top-level helper." in function_data["docstring"]


def test_typescript_repository_parser_extracts_semantic_units():
    parser = RepositoryParser()
    code = '''
/**
 * Calculator class.
 */
export class Calculator {
    /**
     * Compute the total.
     */
    compute(total: number): number {
        return total * 2;
    }
}

/**
 * Multiply numbers.
 */
export const multiply = async (value: number): Promise<number> => {
    return value * 3;
};
'''

    with tempfile.TemporaryDirectory() as tmp:
        repo_path = Path(tmp)
        file_path = repo_path / "calc.ts"
        file_path.write_text(code, encoding="utf-8")

        structure = parser.parse_structure(repo_path)
        assert "calc.ts" in structure["files"]

        file_data = structure["files"]["calc.ts"]
        assert file_data["language"] == "typescript"
        assert len(file_data["classes"]) == 1
        assert len(file_data["functions"]) == 1
        assert len(file_data["methods"]) == 1

        class_data = file_data["classes"][0]
        assert class_data["name"] == "Calculator"
        assert "Calculator class." in class_data["docstring"]
        assert class_data["methods"][0]["name"] == "compute"
        assert "Compute the total." in class_data["methods"][0]["docstring"]

        function_data = file_data["functions"][0]
        assert function_data["name"] == "multiply"
        assert "Multiply numbers." in function_data["docstring"]
