import unittest

from ctfbot.helpers import MAX_EMBED_DESCRIPTION_LENGTH, paginate_lines


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
