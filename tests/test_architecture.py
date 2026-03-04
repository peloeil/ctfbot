import ast
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))


def _load_imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.add(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            imports.add(f"{'.' * node.level}{node.module}")
    return imports


def _load_import_from_nodes(path: Path) -> list[ast.ImportFrom]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return [node for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]


def _normalise_import_name(name: str) -> str:
    trimmed = name.lstrip(".")
    if trimmed.startswith("bot."):
        return trimmed
    if trimmed.startswith(("cogs", "application", "services", "db", "features")):
        return f"bot.{trimmed}"
    return trimmed


def _imports_starting_with(imports: set[str], prefix: str) -> bool:
    return any(_normalise_import_name(name).startswith(prefix) for name in imports)


class ArchitectureBoundaryTests(unittest.TestCase):
    def test_cogs_do_not_depend_on_data_or_services(self):
        cogs_dir = SRC_ROOT / "bot" / "cogs"
        for path in cogs_dir.glob("*.py"):
            if path.name.startswith("_"):
                continue
            imports = _load_imports(path)
            with self.subTest(path=path.name):
                self.assertFalse(_imports_starting_with(imports, "bot.db"))
                self.assertFalse(_imports_starting_with(imports, "bot.services"))
                self.assertFalse(_imports_starting_with(imports, "bot.application"))

    def test_feature_usecases_do_not_depend_on_discord(self):
        for path in (SRC_ROOT / "bot" / "features").glob("*/usecase.py"):
            imports = _load_imports(path)
            with self.subTest(path=path.as_posix()):
                self.assertFalse(_imports_starting_with(imports, "discord"))
                self.assertFalse(_imports_starting_with(imports, "bot.cogs"))

    def test_feature_services_do_not_depend_on_cogs(self):
        for path in (SRC_ROOT / "bot" / "features").glob("*/service.py"):
            imports = _load_imports(path)
            with self.subTest(path=path.as_posix()):
                self.assertFalse(_imports_starting_with(imports, "bot.cogs"))

    def test_feature_repositories_are_persistence_only(self):
        for path in (SRC_ROOT / "bot" / "features").glob("*/repository.py"):
            imports = _load_imports(path)
            with self.subTest(path=path.as_posix()):
                self.assertFalse(_imports_starting_with(imports, "discord"))
                self.assertFalse(_imports_starting_with(imports, "bot.cogs"))
                self.assertFalse(_imports_starting_with(imports, "bot.services"))

    def test_feature_cogs_do_not_depend_on_service_or_repository(self):
        for path in (SRC_ROOT / "bot" / "features").glob("*/cog.py"):
            with self.subTest(path=path.as_posix()):
                import_from_nodes = _load_import_from_nodes(path)
                for node in import_from_nodes:
                    self.assertFalse(node.level == 1 and node.module == "service")
                    self.assertFalse(node.level == 1 and node.module == "repository")


if __name__ == "__main__":
    unittest.main()
