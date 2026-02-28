from wrapper.db.bootstrap import bootstrap_statements


def test_bootstrap_statements_uses_schema_qualified_migrations_table():
    stmts = bootstrap_statements("pbwrap_3")
    assert len(stmts) == 2
    assert 'create schema if not exists "pbwrap_3";' == stmts[0]
    assert 'create table if not exists "pbwrap_3".schema_migrations' in stmts[1]
