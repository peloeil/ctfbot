import unittest

from ctfbot.helpers import MAX_MESSAGE_CONTENT_LENGTH, paginate_lines


class PaginateLinesTest(unittest.TestCase):
    def test_input_within_limit_returns_one_page(self) -> None:
        self.assertEqual(paginate_lines(["first", "second"]), ["first\nsecond"])

    def test_over_limit_input_preserves_separators_within_page_limit(self) -> None:
        lines = ["a" * 1000, "b" * 1000, "c" * 1000]
        for separator in ("\n", "\n\n"):
            with self.subTest(separator=separator):
                pages = paginate_lines(lines, separator=separator)
                self.assertTrue(
                    all(len(page) <= MAX_MESSAGE_CONTENT_LENGTH for page in pages)
                )
                self.assertEqual(separator.join(pages), separator.join(lines))

    def test_line_over_limit_is_split_without_losing_content(self) -> None:
        line = "a" * (MAX_MESSAGE_CONTENT_LENGTH * 2 + 1)

        pages = paginate_lines([line])

        self.assertTrue(all(len(page) <= MAX_MESSAGE_CONTENT_LENGTH for page in pages))
        self.assertEqual("".join(pages), line)

    def test_empty_input_returns_no_pages(self) -> None:
        self.assertEqual(paginate_lines([]), [])

    def test_page_boundary_does_not_return_empty_page(self) -> None:
        line = "x" * MAX_MESSAGE_CONTENT_LENGTH

        self.assertEqual(paginate_lines(["", line]), [line])
