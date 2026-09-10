"""Module dependency-boundary tests (spec 002 T101)."""

from __future__ import annotations

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src" / "intel_agent"

FORBIDDEN_IMPORTS = {
    "conversation",
    "api",
    "bootstrap",
}

BUSINESS_MODULES = ["monitoring", "factcheck", "media"]


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    out: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            out.add(mod.split(".")[0] if mod else "")
        elif isinstance(node, ast.Import):
            for alias in node.names:
                out.add(alias.name.split(".")[0])
    return out


def _module_files(name: str) -> list[Path]:
    base = SRC / name
    if not base.exists():
        return []
    return [p for p in base.rglob("*.py") if p.name != "__init__.py"]


def test_business_modules_do_not_import_conversation_api_bootstrap():
    for name in BUSINESS_MODULES:
        for path in _module_files(name):
            imports = _imports(path)
            leaked = imports & FORBIDDEN_IMPORTS
            assert not leaked, f"{path} imports forbidden modules: {leaked}"


def test_business_modules_do_not_import_each_other():
    for name in BUSINESS_MODULES:
        for path in _module_files(name):
            imports = _imports(path)
            for other in BUSINESS_MODULES:
                if other == name:
                    continue
                assert other not in imports, (
                    f"{path} imports sibling business module {other}"
                )


def test_sql_lives_only_in_storage():
    for path in SRC.rglob("*.py"):
        if path.name == "__init__.py":
            continue
        rel = path.relative_to(SRC)
        if rel.parts[0] in ("storage",):
            continue
        text = path.read_text(encoding="utf-8")
        has_sql = any(
            kw in text for kw in ("SELECT ", "INSERT ", "UPDATE ", "DELETE ")
        )
        assert not has_sql, f"{path} contains SQL outside storage/"


def test_material_store_does_not_own_task_execution():
    tree = ast.parse(
        (SRC / "storage/materials.py").read_text(encoding="utf-8")
    )
    methods = {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef)
    }
    task_methods = {
        "create_task",
        "get_task",
        "update_task_status",
        "save_checkpoint",
        "record_budget_change",
        "create_work_item",
        "update_work_item",
        "get_work_item",
        "reserve_budget",
        "settle_budget",
        "budget_usage",
        "begin_attempt",
        "finish_attempt",
        "list_task_artifacts",
        "latest_task_id",
        "list_work_items",
    }
    assert not methods & task_methods


def test_conversation_does_not_own_search_settings():
    tree = ast.parse((SRC / "conversation.py").read_text(encoding="utf-8"))
    settings_methods = {
        "search_sources",
        "ai_search_tools",
        "add_search_source",
        "toggle_search_source",
        "update_search_source",
        "toggle_ai_tool",
        "update_ai_tool_key",
    }
    methods = {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef)
    }
    assert not methods & settings_methods, "SearchSettings owns configuration"
