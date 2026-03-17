from __future__ import annotations

import datetime
from collections.abc import Sequence
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ChallengeRef:
    name: str
    url: str | None = None


@dataclass(frozen=True, slots=True)
class SolveRecord:
    challenge: ChallengeRef
    solved_at: datetime.datetime


def get_week_range(
    reference_date: datetime.date,
) -> tuple[datetime.date, datetime.date]:
    week_start = reference_date - datetime.timedelta(days=reference_date.weekday())
    week_end = week_start + datetime.timedelta(days=6)
    return week_start, week_end


def select_weekly_solves(
    records: Sequence[SolveRecord],
    *,
    today: datetime.date,
) -> list[ChallengeRef]:
    week_start, _week_end = get_week_range(today)
    challenges: list[ChallengeRef] = []
    seen: set[str] = set()
    for record in records:
        solved_date = record.solved_at.date()
        if solved_date < week_start or solved_date > today:
            continue
        challenge_key = record.challenge.url or record.challenge.name
        if challenge_key in seen:
            continue
        seen.add(challenge_key)
        challenges.append(record.challenge)
    return challenges
