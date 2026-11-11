import ast
from pathlib import Path

TESTS = Path(__file__).resolve().parent


def is_forbidden(module: str) -> bool:
    parts = module.split(".")
    return any(part == "conftest" or part.startswith("test_") for part in (parts[0], parts[-1]))


def imported_modules(tree: ast.AST) -> list[str]:
    modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.module is None:
                modules.extend(alias.name for alias in node.names)
            else:
                modules.append(node.module)
    return modules


def test_no_test_module_imports_another_test_module_or_conftest() -> None:
    violations = [
        f"{path.relative_to(TESTS)}: {module}"
        for path in sorted(TESTS.rglob("*.py"))
        for module in imported_modules(ast.parse(path.read_text(), filename=str(path)))
        if is_forbidden(module)
    ]

    assert violations == []
