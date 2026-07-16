from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SudoGrant:
    guild_id: int
    user_id: int
    role_id: int
    granted_at_unix: int
    expires_at_unix: int
