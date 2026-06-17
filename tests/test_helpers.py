import datetime
import unittest

from bot.helpers import (
    format_timestamp,
    format_timestamp_with_relative,
    sanitize_audit_text,
)


class HelpersTest(unittest.TestCase):
    def test_format_timestamp(self) -> None:
        self.assertEqual(format_timestamp(None), "-")
        self.assertEqual(format_timestamp(123, style="R"), "<t:123:R>")
        value = datetime.datetime(1970, 1, 1, 0, 2, 3, tzinfo=datetime.UTC)
        self.assertEqual(format_timestamp(value), "<t:123:f>")

    def test_format_timestamp_with_relative(self) -> None:
        self.assertEqual(format_timestamp_with_relative(None), "-")
        self.assertEqual(
            format_timestamp_with_relative(123),
            "<t:123:f> (<t:123:R>)",
        )

    def test_sanitize_audit_text(self) -> None:
        self.assertEqual(sanitize_audit_text(" a \n b\tc "), "a b c")
        self.assertEqual(sanitize_audit_text("<@123>"), "<@\u200b123>")


if __name__ == "__main__":
    unittest.main()
