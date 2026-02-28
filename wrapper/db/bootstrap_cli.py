import argparse
import sys

from wrapper.config import WrapperSettings
from wrapper.db.bootstrap import apply_bootstrap, list_bootstrap_sql


def main() -> int:
    parser = argparse.ArgumentParser(description="Bootstrap wrapper DB schema")
    parser.add_argument("--dry-run", action="store_true", help="Print SQL only")
    args = parser.parse_args()

    settings = WrapperSettings.from_env()
    if args.dry_run:
        for stmt in list_bootstrap_sql(settings.postgres_schema):
            print(stmt)
        return 0

    try:
        import psycopg
    except Exception as exc:
        raise RuntimeError(
            "psycopg is required for non-dry-run bootstrap; install dependency first"
        ) from exc

    with psycopg.connect(settings.postgres_dsn) as conn:
        apply_bootstrap(conn, settings.postgres_schema)
    return 0


if __name__ == "__main__":
    sys.exit(main())
