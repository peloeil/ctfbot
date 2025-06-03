"""
Unit tests for the CTF Discord bot.
"""

import os
import sys
import unittest
from unittest.mock import MagicMock, patch

from bs4 import element

# Add src directory to path for imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))

from bot.db.database import (
    create_alpacahack_user_table_if_not_exists,
    delete_alpacahack_user,
    insert_alpacahack_user,
)
from bot.services.alpacahack_service import is_leaf
from bot.utils.helpers import chunk_message, format_code_block


class TestHelpers(unittest.TestCase):
    """Test cases for helper functions."""

    def test_format_code_block(self):
        """Test code block formatting."""
        content = "test content"
        result = format_code_block(content)
        self.assertEqual(result, "```\ntest content\n```")

        # With language
        result = format_code_block(content, "python")
        self.assertEqual(result, "```python\ntest content\n```")

    def test_chunk_message(self):
        """Test message chunking."""
        message = "a" * 2000
        chunks = chunk_message(message, 1000)
        self.assertEqual(len(chunks), 2)
        self.assertEqual(len(chunks[0]), 1000)
        self.assertEqual(len(chunks[1]), 1000)


class TestAlpacaHackService(unittest.TestCase):
    """Test cases for AlpacaHack service."""

    def test_is_leaf(self):
        """Test leaf node detection."""
        # Create a mock Tag with no children
        mock_tag = MagicMock(spec=element.Tag)
        mock_tag.children = []
        self.assertTrue(is_leaf(mock_tag))

        # Create a mock Tag with non-Tag children
        mock_tag.children = ["text"]
        self.assertTrue(is_leaf(mock_tag))

        # Create a mock Tag with Tag children
        child_tag = MagicMock(spec=element.Tag)
        # Set up the mock to return a Tag instance when iterating through children
        mock_tag.children = [child_tag]
        # Override the isinstance check to return True for element.Tag
        with patch("bot.services.alpacahack_service.isinstance", return_value=True):
            self.assertFalse(is_leaf(mock_tag))


class TestDatabase(unittest.TestCase):
    """Test cases for database functions."""

    @patch("bot.db.database.execute_query")
    def test_create_alpacahack_user_table(self, mock_execute_query):
        """Test table creation."""
        create_alpacahack_user_table_if_not_exists()
        mock_execute_query.assert_called_once()

    @patch("bot.db.database.execute_query")
    def test_insert_alpacahack_user(self, mock_execute_query):
        """Test user insertion."""
        result = insert_alpacahack_user("test_user")
        mock_execute_query.assert_called_once()
        self.assertEqual(result, "User 'test_user' added.")

    @patch("bot.db.database.get_db_connection")
    def test_delete_alpacahack_user_exists(self, mock_get_conn):
        """Test user deletion when user exists."""
        # Mock connection and cursor
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.__enter__.return_value = mock_conn
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.rowcount = 1
        mock_get_conn.return_value = mock_conn

        result = delete_alpacahack_user("test_user")
        mock_cursor.execute.assert_called_once()
        self.assertEqual(result, "Deleted user: test_user")

    @patch("bot.db.database.get_db_connection")
    def test_delete_alpacahack_user_not_exists(self, mock_get_conn):
        """Test user deletion when user doesn't exist."""
        # Mock connection and cursor
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.__enter__.return_value = mock_conn
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.rowcount = 0
        mock_get_conn.return_value = mock_conn

        result = delete_alpacahack_user("nonexistent_user")
        mock_cursor.execute.assert_called_once()
        self.assertEqual(result, "No user: nonexistent_user")


if __name__ == "__main__":
    unittest.main()
