import logging

logger = logging.getLogger("ctfbot")


def configure_logging(level: str) -> None:
    logging.getLogger("discord.player").setLevel(logging.WARNING)
    root = logging.getLogger()
    if root.handlers:
        root.setLevel(level)
        return
    logging.basicConfig(
        level=level,
        format="%(asctime)s:%(levelname)s:%(name)s: %(message)s",
    )
