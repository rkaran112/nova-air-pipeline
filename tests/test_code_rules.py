"""Code review rules from the previous pipeline's bugs, checked automatically."""

import ast
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
CODE_FOLDERS = ("pipeline", "scripts", "dashboard")
MUTABLE_NODES = (ast.List, ast.Dict, ast.Set, ast.ListComp, ast.DictComp, ast.SetComp)
MUTABLE_CALLS = {"list", "dict", "set", "Counter", "defaultdict", "deque"}


def python_files():
    for folder in CODE_FOLDERS:
        yield from (REPO / folder).rglob("*.py")


def module_level_mutables(path):
    """Names assigned a list, dict or set at module level: state that would survive
    from one run to the next inside the same Python process."""
    found = []
    for node in ast.parse(path.read_text(encoding="utf-8")).body:
        if not isinstance(node, (ast.Assign, ast.AnnAssign)) or node.value is None:
            continue
        value = node.value
        is_call = isinstance(value, ast.Call) and getattr(value.func, "id", None) in MUTABLE_CALLS
        if isinstance(value, MUTABLE_NODES) or is_call:
            found.append(f"{path.relative_to(REPO)}:{node.lineno}")
    return found


def test_no_module_level_mutable_state():
    found = [hit for path in python_files() for hit in module_level_mutables(path)]
    assert found == []


def test_dashboard_reads_only_the_published_exports():
    forbidden = ("bronze.", "silver.", ".duckdb", "landing")
    for path in (REPO / "dashboard").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert not [word for word in forbidden if word in text], path


def test_no_blanket_warning_filters():
    for path in python_files():
        text = path.read_text(encoding="utf-8")
        assert "filterwarnings(\"ignore\")" not in text and "simplefilter" not in text, path
