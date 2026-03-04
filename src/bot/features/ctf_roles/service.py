from __future__ import annotations

import datetime

from ...errors import ServiceError

INPUT_DATETIME_FORMAT = "%Y-%m-%d %H:%M"


class CTFRoleService:
    def __init__(self, *, timezone: datetime.tzinfo) -> None:
        self._timezone = timezone

    @property
    def timezone(self) -> datetime.tzinfo:
        return self._timezone

    def parse_local_datetime(self, raw_value: str) -> datetime.datetime:
        normalized = raw_value.strip()
        if not normalized:
            raise ServiceError("日時を入力してください。")

        try:
            parsed = datetime.datetime.strptime(normalized, INPUT_DATETIME_FORMAT)
        except ValueError as exc:
            raise ServiceError(
                "日時は YYYY-MM-DD HH:MM 形式で入力してください。"
            ) from exc

        return parsed.replace(tzinfo=self._timezone)

    def now(self) -> datetime.datetime:
        return datetime.datetime.now(self._timezone)

    def now_unix(self) -> int:
        return int(self.now().astimezone(datetime.UTC).timestamp())

    @staticmethod
    def to_unix(value: datetime.datetime) -> int:
        return int(value.astimezone(datetime.UTC).timestamp())

    def from_unix(self, value: int) -> datetime.datetime:
        utc = datetime.datetime.fromtimestamp(value, tz=datetime.UTC)
        return utc.astimezone(self._timezone)

    def format_unix(self, value: int | None) -> str:
        if value is None:
            return "-"
        return self.from_unix(value).strftime("%Y-%m-%d %H:%M %Z")
