import ast
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "ctfbot"


def module_name(path: Path) -> str:
    parts = path.relative_to(SRC.parent).with_suffix("").parts
    return ".".join(parts[:-1] if parts[-1] == "__init__" else parts)


def imports_for(path: Path) -> set[str]:
    return imports_in(
        path.read_text(encoding="utf-8"), module_name(path), path.name == "__init__.py"
    )


def imports_in(source: str, module: str, is_package: bool) -> set[str]:
    """Absolute names of imported modules, with relative imports resolved."""
    tree = ast.parse(source)
    package = module.split(".")
    if not is_package:
        package = package[:-1]
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            base = package[: len(package) - node.level + 1] if node.level else []
            module = ".".join([*base, *([node.module] if node.module else [])])
            imports.add(module)
            # "from ctfbot.features import ctftime" imports a submodule by name.
            if module in ("ctfbot", "ctfbot.features"):
                imports.update(f"{module}.{alias.name}" for alias in node.names)
    return imports


def feature_names() -> set[str]:
    return {
        entry.stem if entry.is_file() else entry.name
        for entry in (SRC / "features").iterdir()
        if (entry.is_file() and entry.suffix == ".py" and entry.stem != "__init__")
        or (entry.is_dir() and (entry / "__init__.py").exists())
    }


class ImportsInTest(unittest.TestCase):
    def test_relative_imports_are_resolved_to_absolute_names(self) -> None:
        imports = imports_in(
            "from .models import A\nfrom ..ctftime import B\nfrom . import helper\n",
            "ctfbot.features.ctfteam.service",
            is_package=False,
        )
        self.assertEqual(
            imports,
            {
                "ctfbot.features.ctfteam.models",
                "ctfbot.features.ctftime",
                "ctfbot.features.ctfteam",
            },
        )

    def test_submodule_imported_by_name_from_features_package_is_detected(
        self,
    ) -> None:
        imports = imports_in(
            "from ctfbot.features import ctftime\n",
            "ctfbot.features.times",
            is_package=False,
        )
        self.assertIn("ctfbot.features.ctftime", imports)


class ArchitectureTest(unittest.TestCase):
    def test_campaign_does_not_import_discord(self) -> None:
        imports = imports_for(SRC / "features" / "ctfteam" / "campaign.py")
        self.assertFalse(
            any(name == "discord" or name.startswith("discord.") for name in imports)
        )

    def test_alpacahack_service_does_not_import_discord(self) -> None:
        imports = imports_for(SRC / "features" / "alpacahack" / "service.py")
        self.assertFalse(
            any(name == "discord" or name.startswith("discord.") for name in imports)
        )

    def test_tts_service_and_client_do_not_import_discord(self) -> None:
        for name in ("service.py", "voicevox.py"):
            imports = imports_for(SRC / "features" / "tts" / name)
            self.assertFalse(
                any(
                    name == "discord" or name.startswith("discord.") for name in imports
                ),
                f"tts/{name} imports discord",
            )

    def test_podman_does_not_import_discord(self) -> None:
        imports = imports_for(SRC / "podman.py")
        self.assertFalse(
            any(name == "discord" or name.startswith("discord.") for name in imports)
        )

    def test_db_does_not_import_discord(self) -> None:
        imports = imports_for(SRC / "db.py")
        self.assertFalse(
            any(name == "discord" or name.startswith("discord.") for name in imports)
        )

    def test_discord_ops_does_not_import_db(self) -> None:
        imports = imports_for(SRC / "features" / "ctfteam" / "discord_ops.py")
        self.assertNotIn("ctfbot.db", imports)

    def test_feature_models_do_not_import_discord(self) -> None:
        for path in (SRC / "features").rglob("models.py"):
            imports = imports_for(path)
            self.assertFalse(
                any(
                    name == "discord" or name.startswith("discord.") for name in imports
                ),
                f"{path} imports discord",
            )

    def test_db_feature_imports_are_models_only(self) -> None:
        imports = imports_for(SRC / "db.py")
        feature_imports = {
            name for name in imports if name.startswith("ctfbot.features.")
        }
        for name in feature_imports:
            self.assertTrue(name.endswith(".models"), f"db.py imports {name}")

    def test_features_do_not_import_each_other(self) -> None:
        features = feature_names()
        self.assertIn("ctfteam", features)
        for path in (SRC / "features").rglob("*.py"):
            if path.name == "__init__.py" and path.parent == SRC / "features":
                continue
            owner = module_name(path).split(".")[2]
            for imported in imports_for(path):
                parts = imported.split(".")
                if parts[:2] != ["ctfbot", "features"] or len(parts) < 3:
                    continue
                self.assertFalse(
                    parts[2] in features and parts[2] != owner,
                    f"{module_name(path)} imports {imported}",
                )
