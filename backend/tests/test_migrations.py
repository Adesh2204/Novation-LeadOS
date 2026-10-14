import os
import subprocess
import sys

from sqlalchemy import inspect

from leados import models  # noqa: F401
from leados.config import ROOT
from leados.db import Base, make_engine


def test_migrations_upgrade_downgrade_and_model_parity(tmp_path):
    url = f"sqlite:///{tmp_path}/migration.db"
    env = {**os.environ, "DATABASE_URL": url}
    command = [sys.executable, "-m", "alembic", "-c", str(ROOT / "alembic.ini")]

    def run(*args):
        subprocess.run([*command, *args], env=env, cwd=ROOT, check=True, capture_output=True)

    run("upgrade", "head")
    engine = make_engine(url)
    assert set(inspect(engine).get_table_names()) == set(Base.metadata.tables) | {"alembic_version"}
    run("check")
    run("downgrade", "base")
    assert inspect(engine).get_table_names() == ["alembic_version"]
    run("upgrade", "head")
    run("check")
    engine.dispose()


def test_postgresql_migration_generates_target_dialect_sql(tmp_path):
    env = {**os.environ, "DATABASE_URL": "postgresql+psycopg://unused:unused@localhost/unused"}
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "-c", str(ROOT / "alembic.ini"), "upgrade", "head", "--sql"],
        env=env,
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    assert "CREATE EXTENSION IF NOT EXISTS vector" in result.stdout
    assert "CREATE TABLE opportunities" in result.stdout
    assert "FOREIGN KEY(company_id) REFERENCES companies" in result.stdout
