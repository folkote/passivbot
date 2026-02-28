# Wrapper service (phase 0 bootstrap)

Initial scaffold for wrapper implementation.

## Env vars

- `POSTGRES_DSN` (required)
- `POSTGRES_SCHEMA` (optional)
- `PBWRAP_INSTANCE_ID` (optional, default `1`)

If `POSTGRES_SCHEMA` is omitted, schema defaults to `pbwrap_<PBWRAP_INSTANCE_ID>`.

## Bootstrap SQL preview

```bash
python -m wrapper.db.bootstrap_cli --dry-run
```

## Apply bootstrap (requires psycopg)

```bash
python -m wrapper.db.bootstrap_cli
```
