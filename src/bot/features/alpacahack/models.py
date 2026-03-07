from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class UserMutationStatus(Enum):
    CREATED = "created"
    ALREADY_EXISTS = "already_exists"
    DELETED = "deleted"
    NOT_FOUND = "not_found"
    INVALID_NAME = "invalid_name"


@dataclass(frozen=True, slots=True)
class UserMutationResult:
    status: UserMutationStatus
    normalized_name: str = ""


@dataclass(frozen=True, slots=True)
class SolvedChallenge:
    name: str
    url: str | None = None
