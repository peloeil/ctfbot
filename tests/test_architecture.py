import ast
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "bot"


def imports_for(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module)
    return imports


class ArchitectureTest(unittest.TestCase):
    def test_campaign_does_not_import_discord(self) -> None:
        imports = imports_for(SRC / "features" / "ctf_team" / "campaign.py")
        self.assertFalse(
            any(name == "discord" or name.startswith("discord.") for name in imports)
        )

    def test_db_does_not_import_discord(self) -> None:
        imports = imports_for(SRC / "db.py")
        self.assertFalse(
            any(name == "discord" or name.startswith("discord.") for name in imports)
        )

    def test_discord_ops_does_not_import_db(self) -> None:
        imports = imports_for(SRC / "features" / "ctf_team" / "discord_ops.py")
        self.assertNotIn("bot.db", imports)

    def test_features_do_not_import_each_other(self) -> None:
        feature_modules = {
            "bot.features.alpacahack",
            "bot.features.ctftime",
            "bot.features.times",
            "bot.features.utility",
            "bot.features.ctf_team",
        }
        for path in (SRC / "features").rglob("*.py"):
            if path.name == "__init__.py":
                continue
            module = "bot.features." + ".".join(
                path.relative_to(SRC / "features").with_suffix("").parts
            )
            imports = imports_for(path)
            forbidden = {
                imported
                for imported in imports
                for feature in feature_modules
                if imported == feature or imported.startswith(f"{feature}.")
            }
            allowed_self = {
                name
                for name in forbidden
                if name == module or name.startswith(f"{module}.")
            }
            forbidden -= allowed_self
            if module.startswith("bot.features.ctf_team."):
                forbidden = {
                    name
                    for name in forbidden
                    if not name.startswith("bot.features.ctf_team.")
                }
            self.assertFalse(forbidden, f"{module} imports {sorted(forbidden)}")


if __name__ == "__main__":
    unittest.main()
