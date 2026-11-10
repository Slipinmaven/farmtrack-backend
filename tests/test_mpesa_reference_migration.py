import importlib.util
from pathlib import Path
from unittest.mock import patch


MIGRATION_PATH = (
    Path(__file__).parents[1]
    / "alembic"
    / "versions"
    / "e9a1c4d7b602_unique_mpesa_transaction_references.py"
)
SPEC = importlib.util.spec_from_file_location(
    "unique_mpesa_transaction_references",
    MIGRATION_PATH,
)
assert SPEC is not None
assert SPEC.loader is not None
MIGRATION = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MIGRATION)


def test_upgrade_reconciles_duplicate_references_before_creating_unique_index():
    with (
        patch.object(MIGRATION.op, "execute") as execute,
        patch.object(MIGRATION.op, "create_index") as create_index,
    ):
        MIGRATION.upgrade()

    reconciliation_sql = str(execute.call_args.args[0])
    assert "row_number() OVER" in reconciliation_sql
    assert "ORDER BY created_at, id" in reconciliation_sql
    assert "'-LEGACY-'" in reconciliation_sql
    assert "RAISE EXCEPTION" not in reconciliation_sql
    create_index.assert_called_once()
