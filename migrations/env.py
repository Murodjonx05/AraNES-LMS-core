from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool
from sqlalchemy.engine import Connection

from src.config import build_app_config
from src.database import Model

# Import model modules so SQLAlchemy metadata is fully populated for autogenerate.
import src.i18n.models  # noqa: F401
import src.user_role.models  # noqa: F401

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Alembic works more reliably with a synchronous SQLAlchemy URL/engine.
# The app itself remains async (`sqlite+aiosqlite`), but migrations use sync drivers.
APP_CONFIG = build_app_config()
alembic_url = APP_CONFIG.DATABASE_URL.replace("+aiosqlite", "")
config.set_main_option("sqlalchemy.url", alembic_url)

target_metadata = Model.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        do_run_migrations(connection)


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
