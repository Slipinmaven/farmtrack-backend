from collections import deque

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.schema import Table

import app.models  # noqa: F401

_BATCH_SIZE = 1000


async def delete_record_tree(
    session: AsyncSession,
    root_table: Table,
    root_id: object,
) -> None:
    root_primary_key = list(root_table.primary_key.columns)
    if len(root_primary_key) != 1:
        raise ValueError(f"{root_table.name} must have a single-column primary key.")

    ids_by_table: dict[Table, set[object]] = {root_table: {root_id}}
    discovered_tables = [root_table]
    pending = deque([root_table])
    metadata_tables = list(root_table.metadata.tables.values())

    while pending:
        parent_table = pending.popleft()
        parent_ids = list(ids_by_table[parent_table])
        parent_primary_key = list(parent_table.primary_key.columns)[0]

        for child_table in metadata_tables:
            child_primary_key = list(child_table.primary_key.columns)
            if len(child_primary_key) != 1:
                continue
            for foreign_key in child_table.foreign_keys:
                if foreign_key.column.table is not parent_table:
                    continue
                if (foreign_key.ondelete or "").upper() == "SET NULL":
                    continue

                child_ids: set[object] = set()
                for start in range(0, len(parent_ids), _BATCH_SIZE):
                    parent_id_batch = parent_ids[start : start + _BATCH_SIZE]
                    child_ids.update(
                        (
                            await session.scalars(
                                select(child_primary_key[0]).where(
                                    foreign_key.parent.in_(parent_id_batch)
                                )
                            )
                        ).all()
                    )
                known_ids = ids_by_table.setdefault(child_table, set())
                new_ids = child_ids - known_ids
                if new_ids:
                    known_ids.update(new_ids)
                    if child_table not in discovered_tables:
                        discovered_tables.append(child_table)
                    pending.append(child_table)

    for table in reversed(discovered_tables):
        primary_key = list(table.primary_key.columns)[0]
        table_ids = list(ids_by_table[table])
        for start in range(0, len(table_ids), _BATCH_SIZE):
            id_batch = table_ids[start : start + _BATCH_SIZE]
            await session.execute(delete(table).where(primary_key.in_(id_batch)))
