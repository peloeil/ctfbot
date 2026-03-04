from collections.abc import Generator

import requests
from bs4 import BeautifulSoup, element
from requests import RequestException

from ..utils.helpers import format_code_block, handle_error, logger

ALPACAHACK_BASE_URL = "https://alpacahack.com/users/"
REQUEST_TIMEOUT_SECONDS = 10


def is_leaf(tag: element.Tag) -> bool:
    """Return True if a BeautifulSoup tag has no child tags."""
    return all(not isinstance(child, element.Tag) for child in tag.children)


def get_alpacahack_solves(user: str) -> str:
    try:
        logger.info("Fetching solve information for user: %s", user)
        soup = _fetch_user_page(user)
        tbody = soup.find("tbody", class_="MuiTableBody-root")
        if not isinstance(tbody, element.Tag):
            logger.warning("No data found for user: %s", user)
            return format_code_block(f"No data found for user: {user}")

        result: list[str] = []
        result.append(user)
        result.append(f"{'CHALLENGE':20}{'SOLVES':20}{'SOLVED AT':20}")
        for row in tbody.find_all("tr"):
            if not isinstance(row, element.Tag):
                continue
            data = row.find_all("td")
            if len(data) < 3:
                continue
            challenge = data[0].get_text(strip=True)
            solves = data[1].get_text(strip=True)
            solve_at = data[2].get_text(strip=True)
            result.append(f"{challenge:20}{solves:20}{solve_at:20}")

        logger.info("Successfully fetched solve information for user: %s", user)
        return format_code_block("\n".join(result))
    except Exception as error:
        logger.error("Error fetching solve information for user %s: %s", user, error)
        return format_code_block(
            handle_error(error, f"Failed to get solves for {user}")
        )


def get_alpacahack_info(user: str) -> Generator[str, None, None]:
    try:
        logger.info("Fetching detailed information for user: %s", user)
        soup = _fetch_user_page(user)
        root_container = soup.find("div", class_="MuiContainer-root")
        if not isinstance(root_container, element.Tag):
            logger.warning("No data container found for user: %s", user)
            yield "No data found"
            return

        section_count = 0
        for section in root_container.contents[1:]:
            if not isinstance(section, element.Tag):
                continue

            tbody = section.find("tbody", class_="MuiTableBody-root")
            if not isinstance(tbody, element.Tag):
                continue
            thead = section.find("thead")
            if not isinstance(thead, element.Tag):
                continue
            header_title = section.find("p", class_="MuiTypography-root")
            if header_title is None:
                continue

            section_count += 1
            result: list[str] = []
            result.append(f"{header_title.text.center(50, '-')}")
            header_row = thead.find("tr")
            if not isinstance(header_row, element.Tag):
                continue

            header_cells = header_row.find_all("th")
            result.append(
                "".join(cell.get_text(strip=True).ljust(20) for cell in header_cells)
            )

            for row in tbody.find_all("tr"):
                if not isinstance(row, element.Tag):
                    continue
                data = row.find_all("td")
                row_text: list[str] = []
                for cell in data:
                    if not isinstance(cell, element.Tag):
                        continue
                    leaf_values: list[str] = []
                    for child_tag in cell.find_all():
                        if not isinstance(child_tag, element.Tag):
                            continue
                        if is_leaf(child_tag) and child_tag.name != "style":
                            leaf_values.append(child_tag.get_text(strip=True))
                    leaf_texts = " ".join(leaf_values)
                    row_text.append(leaf_texts.ljust(20))
                result.append("".join(row_text))

            yield "\n".join(result)
        logger.info(
            "Successfully fetched %s sections for user: %s", section_count, user
        )
    except Exception as error:
        logger.error("Error fetching detailed information for user %s: %s", user, error)
        yield handle_error(error, f"Failed to get info for {user}")


def _fetch_user_page(user: str) -> BeautifulSoup:
    try:
        response = requests.get(
            f"{ALPACAHACK_BASE_URL}{user}",
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
    except RequestException as error:
        raise RuntimeError(f"Failed to fetch AlpacaHack page for {user}") from error

    return BeautifulSoup(response.content, features="html.parser")
