import ast
import sys
import unittest
from pathlib import Path
from unittest import mock

import main

MAIN_PATH = Path(main.__file__).resolve()
PROJECT_VENV = MAIN_PATH.parents[1] / ".venv"


def module_level_imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imports: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module)
    return imports


class EnsureProjectVenvTest(unittest.TestCase):
    def test_accepts_interpreter_inside_project_venv(self) -> None:
        with mock.patch.object(sys, "prefix", str(PROJECT_VENV)):
            main.ensure_project_venv()

    def test_exits_when_interpreter_is_outside_project_venv(self) -> None:
        with (
            mock.patch.object(sys, "prefix", "/usr"),
            self.assertRaises(SystemExit) as ctx,
        ):
            main.ensure_project_venv()

        self.assertIn("uv run --env-file .env src/main.py", str(ctx.exception.code))

    def test_bot_package_is_not_imported_before_the_venv_check(self) -> None:
        imports = module_level_imports(MAIN_PATH)
        self.assertFalse(
            any(name == "bot" or name.startswith("bot.") for name in imports),
            "module-level import of bot defeats ensure_project_venv",
        )
