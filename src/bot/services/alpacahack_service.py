"""
AlpacaHack service module for the CTF Discord bot.
Handles web scraping and data retrieval from AlpacaHack website.
"""
from collections.abc import Generator

import requests
from bs4 import BeautifulSoup, element

from ..utils.helpers import format_code_block, handle_error, logger


def is_leaf(tag: element.Tag) -> bool:
    """
    Check if a BeautifulSoup tag is a leaf node (has no child tags).

    Args:
        tag: BeautifulSoup tag to check

    Returns:
        True if the tag is a leaf node, False otherwise
    """
    # Fix the logic to correctly identify tags with Tag children
    return all(not isinstance(child, element.Tag) for child in tag.children)


def get_alpacahack_solves(user: str) -> str:
    """
    Get solve information for a user from AlpacaHack website.

    Args:
        user: Username to get solves for

    Returns:
        Formatted string with solve information
    """
    try:
        logger.info(f"Fetching solve information for user: {user}")
        response = requests.get(f"https://alpacahack.com/users/{user}")
        response.raise_for_status()  # Raise exception for HTTP errors
        soup = BeautifulSoup(response.content, features="html.parser")
        tbody = soup.find("tbody", class_="MuiTableBody-root")
        if not tbody:
            logger.warning(f"No data found for user: {user}")
            return format_code_block(f"No data found for user: {user}")
        result = []
        result.append(user)
        result.append(f"{'CHALLENGE':20}{'SOLVES':20}{'SOLVED AT':20}")
        for row in tbody.find_all("tr"):
            data = row.find_all("td")
            challenge = data[0].find("a").text
            solves = data[1].find("p").text
            solve_at = data[2].find("p").text
            result.append(f"{challenge:20}{solves:20}{solve_at:20}")
        logger.info(f"Successfully fetched solve information for user: {user}")
        return format_code_block("\n".join(result))
    except Exception as e:
        logger.error(f"Error fetching solve information for user {user}: {e}")
        return format_code_block(handle_error(e, f"Failed to get solves for {user}"))


def get_alpacahack_info(user: str) -> Generator[str, None, None]:
    """
    Get detailed information for a user from AlpacaHack website.

    Args:
        user: Username to get information for

    Returns:
        Generator yielding formatted strings with user information
    """
    try:
        logger.info(f"Fetching detailed information for user: {user}")
        response = requests.get(f"https://alpacahack.com/users/{user}")
        response.raise_for_status()  # Raise exception for HTTP errors
        soup = BeautifulSoup(response.content, features="html.parser")
        root_container = soup.find("div", class_="MuiContainer-root")
        if not root_container:
            logger.warning(f"No data container found for user: {user}")
            yield "No data found"
            return
        section_count = 0
        for section in root_container.contents[1:]:
            tbody = section.find("tbody", class_="MuiTableBody-root")
            if tbody is None:
                continue
            thead = section.find("thead")
            if thead is None:
                continue
            header_title = section.find("p", class_="MuiTypography-root")
            if header_title is None:
                continue
            section_count += 1
            result = []
            result.append(f"{header_title.text.center(50, '-')}")
            # Add header row
            header_cells = thead.find("tr").find_all("th")
            result.append("".join(cell.text.ljust(20) for cell in header_cells))
            # Add data rows
            for row in tbody.find_all("tr"):
                data = row.find_all("td")
                row_text = []
                for cell in data:
                    leaf_texts = " ".join(
                        [tag.get_text(strip=True) for tag in cell.find_all()
                         if is_leaf(tag) and tag.name != "style"])
                    row_text.append(leaf_texts.ljust(20))
                result.append("".join(row_text))
            yield "\n".join(result)
        logger.info(f"Successfully fetched {section_count} sections for user: {user}")
    except Exception as e:
        logger.error(f"Error fetching detailed information for user {user}: {e}")
        yield handle_error(e, f"Failed to get info for {user}")
