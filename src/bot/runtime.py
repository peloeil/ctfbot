from __future__ import annotations

from dataclasses import dataclass

from .config import Settings
from .db.connection import DatabaseConnectionFactory
from .features.alpacahack.repository import AlpacaHackUserRepository
from .features.alpacahack.usecase import AlpacaHackUseCase
from .features.ctf_team.repository import CTFTeamCampaignRepository
from .features.ctf_team.service import CTFTeamService
from .features.ctf_team.usecase import CTFTeamUseCase
from .features.ctftime.usecase import CTFTimeUseCase
from .integrations.alpacahack_scraper import AlpacaHackClient
from .integrations.ctftime_api import CTFTimeClient
from .runtime_providers import (
    build_alpacahack_components,
    build_connection_factory,
    build_ctf_team_components,
    build_ctftime_components,
)


@dataclass(frozen=True, slots=True)
class BotRuntime:
    settings: Settings
    connection_factory: DatabaseConnectionFactory
    alpacahack_repository: AlpacaHackUserRepository
    alpacahack_client: AlpacaHackClient
    ctf_team_repository: CTFTeamCampaignRepository
    ctf_team_service: CTFTeamService
    ctftime_client: CTFTimeClient
    alpacahack_usecase: AlpacaHackUseCase
    ctf_team_usecase: CTFTeamUseCase
    ctftime_usecase: CTFTimeUseCase


def build_runtime(settings: Settings) -> BotRuntime:
    connection_factory = build_connection_factory(settings)
    alpacahack = build_alpacahack_components(settings, connection_factory)
    ctf_team = build_ctf_team_components(settings, connection_factory)
    ctftime = build_ctftime_components(settings)
    return BotRuntime(
        settings=settings,
        connection_factory=connection_factory,
        alpacahack_repository=alpacahack.repository,
        alpacahack_client=alpacahack.client,
        ctf_team_repository=ctf_team.repository,
        ctf_team_service=ctf_team.service,
        ctftime_client=ctftime.client,
        alpacahack_usecase=alpacahack.usecase,
        ctf_team_usecase=ctf_team.usecase,
        ctftime_usecase=ctftime.usecase,
    )
