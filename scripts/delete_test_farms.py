import asyncio
from uuid import UUID

from sqlalchemy import delete, select

from app.core.database import async_session_factory, dispose_database_engine
from app.models.contact import Contact
from app.models.contact_roles import ContactRole
from app.models.farm import Farm
from app.models.farm_settings import FarmSettings


TEST_FARM_IDS = (
    UUID("70c6d7b1-de77-40a7-a4e5-3ac68c7a9390"),
    UUID("97160fd1-9602-4abe-be7c-02ad7836a88f"),
    UUID("d1e66f19-dce1-4f6d-bc66-a039365de687"),
)
EXPECTED_OWNER_ID = UUID("a87cd017-81ee-497e-b905-36f692853858")
EXPECTED_FARM_NAME = "Farm Track"


async def main() -> None:
    try:
        async with async_session_factory() as session:
            async with session.begin():
                farms = (
                    await session.scalars(
                        select(Farm)
                        .where(Farm.id.in_(TEST_FARM_IDS))
                        .with_for_update()
                    )
                ).all()
                if len(farms) != len(TEST_FARM_IDS) or any(
                    farm.owner_id != EXPECTED_OWNER_ID
                    or farm.name != EXPECTED_FARM_NAME
                    for farm in farms
                ):
                    raise RuntimeError(
                        "Cleanup aborted: the target farms no longer match the expected IDs, owner, and name."
                    )

                contact_ids = select(Contact.id).where(
                    Contact.farm_id.in_(TEST_FARM_IDS)
                )
                roles_result = await session.execute(
                    delete(ContactRole).where(ContactRole.contact_id.in_(contact_ids))
                )
                contacts_result = await session.execute(
                    delete(Contact).where(Contact.farm_id.in_(TEST_FARM_IDS))
                )
                settings_result = await session.execute(
                    delete(FarmSettings).where(FarmSettings.farm_id.in_(TEST_FARM_IDS))
                )
                farms_result = await session.execute(
                    delete(Farm).where(Farm.id.in_(TEST_FARM_IDS))
                )

            print(
                "Deleted test records: "
                f"farms={farms_result.rowcount}, "
                f"settings={settings_result.rowcount}, "
                f"contacts={contacts_result.rowcount}, "
                f"contact_roles={roles_result.rowcount}"
            )
    finally:
        await dispose_database_engine()


if __name__ == "__main__":
    asyncio.run(main())