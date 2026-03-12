from __future__ import annotations

from dataclasses import dataclass

from .config import Settings
from .db.connection import DatabaseConnectionFactory
from .db.migrations import ensure_current_schema
from .features.alpacahack.repository import AlpacaHackUserRepository
from .features.alpacahack.service import AlpacaHackService
from .features.alpacahack.usecase import AlpacaHackUseCase
from .features.ctf_team.repository import CTFTeamCampaignRepository
from .features.ctf_team.service import CTFTeamService
from .features.ctf_team.usecase import CTFTeamUseCase
from .features.ctftime.service import CTFTimeService
from .features.ctftime.usecase import CTFTimeUseCase


@dataclass(frozen=True, slots=True)
class AlpacaHackComponents:
    repository: AlpacaHackUserRepository
    service: AlpacaHackService
    usecase: AlpacaHackUseCase


@dataclass(frozen=True, slots=True)
class CTFTimeComponents:
    service: CTFTimeService
    usecase: CTFTimeUseCase


@dataclass(frozen=True, slots=True)
class CTFTeamComponents:
    repository: CTFTeamCampaignRepository
    service: CTFTeamService
    usecase: CTFTeamUseCase


def build_connection_factory(settings: Settings) -> DatabaseConnectionFactory:
    factory = DatabaseConnectionFactory(database_path=settings.database_path)
    ensure_current_schema(factory)
    return factory


def build_alpacahack_components(
    settings: Settings,
    factory: DatabaseConnectionFactory,
) -> AlpacaHackComponents:
    repository = AlpacaHackUserRepository(connection_factory=factory)
    service = AlpacaHackService(timezone=settings.tzinfo)
    usecase = AlpacaHackUseCase(repository=repository, service=service)
    return AlpacaHackComponents(repository=repository, service=service, usecase=usecase)


def build_ctftime_components(settings: Settings) -> CTFTimeComponents:
    service = CTFTimeService(
        timezone=settings.tzinfo,
        user_agent=settings.ctftime_user_agent,
    )
    usecase = CTFTimeUseCase(
        service=service,
        window_days=settings.ctftime_window_days,
        event_limit=settings.ctftime_event_limit,
    )
    return CTFTimeComponents(service=service, usecase=usecase)


def build_ctf_team_components(
    settings: Settings,
    factory: DatabaseConnectionFactory,
) -> CTFTeamComponents:
    repository = CTFTeamCampaignRepository(connection_factory=factory)
    service = CTFTeamService(timezone=settings.tzinfo)
    usecase = CTFTeamUseCase(repository=repository, service=service)
    return CTFTeamComponents(repository=repository, service=service, usecase=usecase)
