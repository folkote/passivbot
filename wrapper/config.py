import os
import re
from dataclasses import dataclass

_SCHEMA_RE = re.compile(r"^[a-z_][a-z0-9_]*$")


def build_default_schema(instance_id: int) -> str:
    if instance_id <= 0:
        raise ValueError(f"instance_id must be > 0, got {instance_id}")
    return f"pbwrap_{instance_id}"


def validate_schema_name(schema: str) -> str:
    s = (schema or "").strip()
    if not s:
        raise ValueError("schema must be non-empty")
    if not _SCHEMA_RE.match(s):
        raise ValueError(
            "invalid schema name; use lowercase letters, digits, underscore, and start with a letter/underscore"
        )
    return s


@dataclass(frozen=True)
class WrapperSettings:
    postgres_dsn: str
    postgres_schema: str
    instance_id: int

    @classmethod
    def from_env(cls) -> "WrapperSettings":
        dsn = os.environ.get("POSTGRES_DSN", "").strip()
        if not dsn:
            raise ValueError("POSTGRES_DSN is required")

        raw_instance_id = os.environ.get("PBWRAP_INSTANCE_ID", "1").strip()
        try:
            instance_id = int(raw_instance_id)
        except ValueError as exc:
            raise ValueError(f"PBWRAP_INSTANCE_ID must be integer, got {raw_instance_id!r}") from exc

        raw_schema = os.environ.get("POSTGRES_SCHEMA", "").strip()
        schema = raw_schema if raw_schema else build_default_schema(instance_id)
        schema = validate_schema_name(schema)
        return cls(postgres_dsn=dsn, postgres_schema=schema, instance_id=instance_id)
