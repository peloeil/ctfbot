import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import Mock, patch
from zoneinfo import ZoneInfo

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from bot.db.connection import DatabaseConnectionFactory  # noqa: E402
from bot.db.migrations import apply_migrations  # noqa: E402
from bot.features.alpacahack.models import UserMutationStatus  # noqa: E402
from bot.features.alpacahack.repository import AlpacaHackUserRepository  # noqa: E402
from bot.features.alpacahack.service import AlpacaHackService  # noqa: E402
from bot.features.alpacahack.usecase import AlpacaHackUseCase  # noqa: E402
from bot.utils.helpers import chunk_message, format_code_block  # noqa: E402


class TestHelpers(unittest.TestCase):
    def test_format_code_block(self):
        self.assertEqual(format_code_block("test"), "```\ntest\n```")
        self.assertEqual(format_code_block("x", "python"), "```python\nx\n```")

    def test_chunk_message(self):
        message = "a" * 2000
        chunks = chunk_message(message, 1000)
        self.assertEqual(len(chunks), 2)
        self.assertEqual(len(chunks[0]), 1000)
        self.assertEqual(len(chunks[1]), 1000)


class TestAlpacaHackService(unittest.TestCase):
    def setUp(self):
        self.service = AlpacaHackService(timezone=ZoneInfo("Asia/Tokyo"))

    def test_get_week_range(self):
        start, end = self.service.get_week_range(date(2026, 3, 4))
        self.assertEqual(start, date(2026, 3, 2))
        self.assertEqual(end, date(2026, 3, 8))

    def test_get_weekly_solve_challenges_filters_by_current_week(self):
        html = """
        <html>
          <body>
            <p>SOLVED CHALLENGES</p>
            <div>
              <table>
                <tbody>
                  <tr>
                    <td><a>weekly-one</a></td>
                    <td><p>1</p></td>
                    <td><span aria-label="2026-03-03 10:00 UTC"></span></td>
                  </tr>
                  <tr>
                    <td><a>old-one</a></td>
                    <td><p>1</p></td>
                    <td><span aria-label="2026-02-28 23:00 UTC"></span></td>
                  </tr>
                </tbody>
              </table>
            </div>
          </body>
        </html>
        """
        response = Mock()
        response.content = html.encode("utf-8")
        response.raise_for_status.return_value = None

        with patch(
            "bot.features.alpacahack.service.requests.get", return_value=response
        ):
            solves = self.service.get_weekly_solve_challenges(
                "alice", reference_date=date(2026, 3, 4)
            )

        self.assertEqual(solves, ["weekly-one"])

    def test_get_weekly_solve_challenges_supports_gmt_label(self):
        html = """
        <html>
          <body>
            <p>SOLVED CHALLENGES</p>
            <div>
              <table>
                <tbody>
                  <tr>
                    <td><a>daily-one</a></td>
                    <td><p>1</p></td>
                    <td><span aria-label="2026-03-04 19:11 GMT+0"></span></td>
                  </tr>
                  <tr>
                    <td><a>daily-two</a></td>
                    <td><p>1</p></td>
                    <td><span aria-label="2026-03-04 19:03:30 GMT+0"></span></td>
                  </tr>
                </tbody>
              </table>
            </div>
          </body>
        </html>
        """
        response = Mock()
        response.content = html.encode("utf-8")
        response.raise_for_status.return_value = None

        with patch(
            "bot.features.alpacahack.service.requests.get", return_value=response
        ):
            solves = self.service.get_weekly_solve_challenges(
                "test-user", reference_date=date(2026, 3, 5)
            )

        self.assertEqual(solves, ["daily-one", "daily-two"])


class TestDatabaseAndUseCase(unittest.TestCase):
    def setUp(self):
        self.timezone = ZoneInfo("Asia/Tokyo")

    def test_insert_and_delete_user(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            connection_factory = DatabaseConnectionFactory(
                database_path=str(Path(tmp_dir) / "alpaca.db")
            )
            apply_migrations(connection_factory)
            repository = AlpacaHackUserRepository(connection_factory=connection_factory)
            usecase = AlpacaHackUseCase(
                repository=repository,
                service=AlpacaHackService(timezone=self.timezone),
                request_interval_seconds=0,
                sleep_fn=lambda _seconds: None,
            )

            added = usecase.add_user("alice")
            self.assertEqual(added.status, UserMutationStatus.CREATED)
            self.assertEqual(usecase.list_usernames(), ["alice"])

            deleted = usecase.delete_user("alice")
            self.assertEqual(deleted.status, UserMutationStatus.DELETED)
            self.assertEqual(usecase.list_usernames(), [])

    def test_insert_duplicate_user(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            connection_factory = DatabaseConnectionFactory(
                database_path=str(Path(tmp_dir) / "alpaca.db")
            )
            apply_migrations(connection_factory)
            repository = AlpacaHackUserRepository(connection_factory=connection_factory)
            usecase = AlpacaHackUseCase(
                repository=repository,
                service=AlpacaHackService(timezone=self.timezone),
                request_interval_seconds=0,
                sleep_fn=lambda _seconds: None,
            )

            usecase.add_user("alice")
            duplicate = usecase.add_user("alice")
            self.assertEqual(duplicate.status, UserMutationStatus.ALREADY_EXISTS)


if __name__ == "__main__":
    unittest.main()
