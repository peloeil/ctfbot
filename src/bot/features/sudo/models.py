from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SudoGrant:
    user_id: int
    role_id: int
    granted_at_unix: int
    expires_at_unix: int
