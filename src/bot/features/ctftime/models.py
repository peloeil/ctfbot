from __future__ import annotations

import datetime
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class CTFEvent:
    title: str
    start: datetime.datetime
    finish: datetime.datetime
    ctftime_url: str
