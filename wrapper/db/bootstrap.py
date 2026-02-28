from typing import Iterable


def quote_ident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def bootstrap_statements(schema: str) -> list[str]:
    s = quote_ident(schema)
    return [
        f"create schema if not exists {s};",
        f"create table if not exists {s}.schema_migrations ("
        "id bigserial primary key, "
        "name text not null unique, "
        "applied_at timestamptz not null default now()"
        ");",
    ]


def apply_bootstrap(conn, schema: str) -> None:
    stmts = bootstrap_statements(schema)
    with conn.cursor() as cur:
        for stmt in stmts:
            cur.execute(stmt)
    conn.commit()


def list_bootstrap_sql(schema: str) -> Iterable[str]:
    for stmt in bootstrap_statements(schema):
        yield stmt
