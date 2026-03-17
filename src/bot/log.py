from __future__ import annotations

import logging

logger = logging.getLogger("ctfbot")


def configure_logging(level: str) -> None:
    """Configure root logger once at startup."""
    root = logging.getLogger()
    if root.handlers:
        root.setLevel(level)
        return

    logging.basicConfig(
        level=level,
        format="%(asctime)s:%(levelname)s:%(name)s: %(message)s",
    )
