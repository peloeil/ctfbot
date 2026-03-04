from __future__ import annotations

from dataclasses import dataclass

from .config import Settings
from .db.connection import DatabaseConnectionFactory
from .features.alpacahack.repository import AlpacaHackUserRepository
from .features.alpacahack.service import AlpacaHackService
from .features.alpacahack.usecase import AlpacaHackUseCase
from .features.ctftime.service import CTFTimeService
from .features.ctftime.usecase import CTFTimeUseCase
from .runtime_providers import (
    build_alpacahack_components,
    build_connection_factory,
    build_ctftime_components,
)


@dataclass(frozen=True, slots=True)
class BotRuntime:
    settings: Settings
    connection_factory: DatabaseConnectionFactory
    alpacahack_repository: AlpacaHackUserRepository
    alpacahack_service: AlpacaHackService
    ctftime_service: CTFTimeService
    alpacahack_usecase: AlpacaHackUseCase
    ctftime_usecase: CTFTimeUseCase


def build_runtime(settings: Settings) -> BotRuntime:
    connection_factory = build_connection_factory(settings)
    alpacahack = build_alpacahack_components(settings, connection_factory)
    ctftime = build_ctftime_components(settings)
    return BotRuntime(
        settings=settings,
        connection_factory=connection_factory,
        alpacahack_repository=alpacahack.repository,
        alpacahack_service=alpacahack.service,
        ctftime_service=ctftime.service,
        alpacahack_usecase=alpacahack.usecase,
        ctftime_usecase=ctftime.usecase,
    )
