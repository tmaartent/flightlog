import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import Engine

from flightlog.infrastructure.tables import metadata


def revisions_oldest_first(cfg):
    script = ScriptDirectory.from_config(cfg)
    return list(reversed(list(script.walk_revisions("base", "heads"))))

@pytest.mark.db
def test_every_migration_can_be_undone_and_redone(migrations_cfg: Config):
    for revision in revisions_oldest_first(migrations_cfg):
        command.upgrade(migrations_cfg, revision.revision)
        command.downgrade(migrations_cfg, "-1")
        command.upgrade(migrations_cfg, revision.revision)

@pytest.mark.db
def test_the_migrations_produce_exactly_the_schema_in_tables_py(migrations_cfg: Config, migrations_engine: Engine):
    command.upgrade(migrations_cfg, "head")
    with migrations_engine.connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn), metadata)
    assert diff == []