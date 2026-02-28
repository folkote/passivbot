import os

import pytest

from wrapper.config import WrapperSettings, build_default_schema, validate_schema_name


@pytest.mark.parametrize(
    "instance_id,expected",
    [
        (1, "pbwrap_1"),
        (2, "pbwrap_2"),
        (77, "pbwrap_77"),
    ],
)
def test_build_default_schema(instance_id, expected):
    assert build_default_schema(instance_id) == expected


def test_build_default_schema_rejects_non_positive():
    with pytest.raises(ValueError):
        build_default_schema(0)


@pytest.mark.parametrize("schema", ["pbwrap_1", "_custom_2", "a1_b2"])
def test_validate_schema_name_ok(schema):
    assert validate_schema_name(schema) == schema


@pytest.mark.parametrize("schema", ["", "UPPER", "my-schema", "1abc", "a b"])
def test_validate_schema_name_rejects_bad_values(schema):
    with pytest.raises(ValueError):
        validate_schema_name(schema)


def test_settings_from_env_defaults_schema(monkeypatch):
    monkeypatch.setenv("POSTGRES_DSN", "postgresql://u:p@localhost:5432/db")
    monkeypatch.setenv("PBWRAP_INSTANCE_ID", "3")
    monkeypatch.delenv("POSTGRES_SCHEMA", raising=False)

    s = WrapperSettings.from_env()
    assert s.postgres_schema == "pbwrap_3"


def test_settings_from_env_schema_override(monkeypatch):
    monkeypatch.setenv("POSTGRES_DSN", "postgresql://u:p@localhost:5432/db")
    monkeypatch.setenv("PBWRAP_INSTANCE_ID", "3")
    monkeypatch.setenv("POSTGRES_SCHEMA", "custom_99")

    s = WrapperSettings.from_env()
    assert s.postgres_schema == "custom_99"


def test_settings_requires_dsn(monkeypatch):
    monkeypatch.delenv("POSTGRES_DSN", raising=False)
    monkeypatch.setenv("PBWRAP_INSTANCE_ID", "1")
    with pytest.raises(ValueError):
        WrapperSettings.from_env()
