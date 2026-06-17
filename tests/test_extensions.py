import importlib
import unittest

from bot.cogs_loader import DEFAULT_EXTENSIONS


class ExtensionsTest(unittest.TestCase):
    def test_default_extensions_are_importable(self) -> None:
        for extension in DEFAULT_EXTENSIONS:
            with self.subTest(extension=extension):
                module = importlib.import_module(extension)
                self.assertTrue(callable(getattr(module, "setup", None)))


if __name__ == "__main__":
    unittest.main()
