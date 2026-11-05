import unittest
from types import SimpleNamespace

from ctfbot.helpers import (
    MAX_EMBED_DESCRIPTION_LENGTH,
    format_log_channel,
    format_log_guild,
    format_log_role,
    format_log_user,
    paginate_lines,
)


class LogEntityFormatTest(unittest.TestCase):
    def test_entities_show_name_with_id(self) -> None:
        self.assertEqual(
            format_log_user(SimpleNamespace(name="alice", id=1)), "alice(1)"
        )
        self.assertEqual(
            format_log_channel(SimpleNamespace(name="general", id=2)), "#general(2)"
        )
        self.assertEqual(format_log_role(SimpleNamespace(name="CTF", id=3)), "CTF(3)")
        self.assertEqual(
            format_log_guild(SimpleNamespace(name="guild", id=4)), "guild(4)"
        )

    def test_missing_entity_falls_back_to_unknown(self) -> None:
        self.assertEqual(format_log_user(None, 1), "unknown(1)")
        self.assertEqual(format_log_channel(None, 2), "unknown(2)")
        self.assertEqual(format_log_role(None, 3), "unknown(3)")
        self.assertEqual(format_log_guild(None, 4), "unknown(4)")

    def test_missing_id_omits_parentheses(self) -> None:
        self.assertEqual(format_log_user(None), "unknown")


class PaginateLinesTest(unittest.TestCase):
    def test_input_within_limit_returns_one_page(self) -> None:
        self.assertEqual(paginate_lines(["first", "second"]), ["first\nsecond"])

    def test_over_limit_input_preserves_lines_within_page_limit(self) -> None:
        lines = ["a" * 2000, "b" * 2000, "c" * 2000]

        pages = paginate_lines(lines)

        self.assertTrue(
            all(len(page) <= MAX_EMBED_DESCRIPTION_LENGTH for page in pages)
        )
        self.assertEqual("\n".join(pages), "\n".join(lines))

    def test_line_over_limit_is_split_without_losing_content(self) -> None:
        line = "a" * (MAX_EMBED_DESCRIPTION_LENGTH * 2 + 1)

        pages = paginate_lines([line])

        self.assertTrue(
            all(len(page) <= MAX_EMBED_DESCRIPTION_LENGTH for page in pages)
        )
        self.assertEqual("".join(pages), line)

    def test_empty_input_returns_no_pages(self) -> None:
        self.assertEqual(paginate_lines([]), [])

    def test_page_boundary_does_not_return_empty_page(self) -> None:
        line = "x" * MAX_EMBED_DESCRIPTION_LENGTH

        self.assertEqual(paginate_lines(["", line]), [line])
