from datetime import datetime
from uuid import UUID

from sqlalchemy import String, and_, case, cast, desc, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.activities import Activity
from app.schemas.enums import ActivityCategory, ActivityEntityType, ActivityType


CATEGORY_ENTITY_TYPES: dict[ActivityCategory, tuple[ActivityEntityType, ...]] = {
    ActivityCategory.FARM: (ActivityEntityType.FARM,),
    ActivityCategory.HOUSING: (ActivityEntityType.BLOCK,),
    ActivityCategory.CONTACTS: (
        ActivityEntityType.CONTACT,
        ActivityEntityType.CONTACT_ROLE,
        ActivityEntityType.CONTACT_ROLE_PRODUCT,
    ),
    ActivityCategory.SALES: (
        ActivityEntityType.SALE_DELIVERY,
        ActivityEntityType.SALE_RETURN,
        ActivityEntityType.TRANSACTION_REFUND,
    ),
    ActivityCategory.PURCHASES: (
        ActivityEntityType.PURCHASE_RECEIPT,
        ActivityEntityType.PURCHASE_RETURN,
        ActivityEntityType.PURCHASE_SUPPLIER_REFUND,
        ActivityEntityType.PURCHASE_REPLACEMENT,
    ),
    ActivityCategory.FLOCK: (
        ActivityEntityType.CHICKEN_MOVEMENT,
        ActivityEntityType.CHICKEN_LOSS,
    ),
    ActivityCategory.EGGS: (
        ActivityEntityType.EGG_COLLECTION,
        ActivityEntityType.EGG_LOSS,
    ),
    ActivityCategory.INVENTORY: (
        ActivityEntityType.PRODUCT_CONSUMPTION,
        ActivityEntityType.INVENTORY_MOVEMENT,
        ActivityEntityType.INVENTORY_OPENING_SETUP,
    ),
    ActivityCategory.EXPENSES: (ActivityEntityType.EXPENSE,),
}


class ActivityRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, activity: Activity) -> Activity:
        self.session.add(activity)
        await self.session.flush()
        return activity

    async def get_by_id_for_farm(
        self, farm_id: UUID, activity_id: UUID
    ) -> Activity | None:
        result = await self.session.execute(
            select(Activity).where(
                Activity.farm_id == farm_id,
                Activity.id == activity_id,
            )
        )
        return result.scalar_one_or_none()

    async def get_summary_for_farm(
        self,
        farm_id: UUID,
        period_end: datetime,
        current_period_start: datetime,
        previous_period_start: datetime,
    ) -> dict[str, int]:
        sales_condition = or_(
            Activity.entity_type.in_(CATEGORY_ENTITY_TYPES[ActivityCategory.SALES]),
            and_(
                Activity.entity_type.in_(
                    (
                        ActivityEntityType.TRANSACTION,
                        ActivityEntityType.TRANSACTION_PAYMENT,
                        ActivityEntityType.TRANSACTION_SETTLEMENT,
                    )
                ),
                Activity.details["transaction_type"].as_string() == "sale",
            ),
        )
        purchase_condition = or_(
            Activity.entity_type.in_(CATEGORY_ENTITY_TYPES[ActivityCategory.PURCHASES]),
            and_(
                Activity.entity_type.in_(
                    (
                        ActivityEntityType.TRANSACTION,
                        ActivityEntityType.TRANSACTION_PAYMENT,
                        ActivityEntityType.TRANSACTION_SETTLEMENT,
                    )
                ),
                Activity.details["transaction_type"].as_string() == "purchase",
            ),
        )
        category_conditions = {
            ActivityCategory.FARM: Activity.entity_type.in_(
                CATEGORY_ENTITY_TYPES[ActivityCategory.FARM]
            ),
            ActivityCategory.HOUSING: Activity.entity_type.in_(
                CATEGORY_ENTITY_TYPES[ActivityCategory.HOUSING]
            ),
            ActivityCategory.CONTACTS: Activity.entity_type.in_(
                CATEGORY_ENTITY_TYPES[ActivityCategory.CONTACTS]
            ),
            ActivityCategory.SALES: sales_condition,
            ActivityCategory.PURCHASES: purchase_condition,
            ActivityCategory.FLOCK: Activity.entity_type.in_(
                CATEGORY_ENTITY_TYPES[ActivityCategory.FLOCK]
            ),
            ActivityCategory.EGGS: Activity.entity_type.in_(
                CATEGORY_ENTITY_TYPES[ActivityCategory.EGGS]
            ),
            ActivityCategory.INVENTORY: Activity.entity_type.in_(
                CATEGORY_ENTITY_TYPES[ActivityCategory.INVENTORY]
            ),
            ActivityCategory.EXPENSES: Activity.entity_type.in_(
                CATEGORY_ENTITY_TYPES[ActivityCategory.EXPENSES]
            ),
            ActivityCategory.UPDATES: Activity.type == ActivityType.NOTIFICATION_CREATED,
        }
        attention_types = (
            ActivityType.CHICKEN_LOSS_RECORDED,
            ActivityType.EGG_LOSS_RECORDED,
            ActivityType.PURCHASE_RETURN_CREATED,
            ActivityType.PURCHASE_SUPPLIER_REFUND_RECORDED,
            ActivityType.SALE_RETURN_CREATED,
            ActivityType.TRANSACTION_REFUND_CREATED,
        )
        columns = [
            func.sum(
                case(
                    (
                        and_(
                            Activity.created_at >= current_period_start,
                            Activity.created_at < period_end,
                        ),
                        1,
                    ),
                    else_=0,
                )
            ).label("last_7_days_count"),
            func.sum(
                case(
                    (
                        and_(
                            Activity.created_at >= previous_period_start,
                            Activity.created_at < current_period_start,
                        ),
                        1,
                    ),
                    else_=0,
                )
            ).label("previous_7_days_count"),
            func.sum(
                case(
                    (
                        and_(
                            Activity.created_at >= current_period_start,
                            Activity.created_at < period_end,
                            Activity.type.in_(attention_types),
                        ),
                        1,
                    ),
                    else_=0,
                )
            ).label("losses_and_returns_count"),
        ]
        columns.extend(
            func.sum(
                case(
                    (
                        and_(
                            Activity.created_at >= current_period_start,
                            condition,
                        ),
                        1,
                    ),
                    else_=0,
                )
            ).label(category.value)
            for category, condition in category_conditions.items()
        )
        result = await self.session.execute(
            select(*columns).where(
                Activity.farm_id == farm_id,
                Activity.created_at >= previous_period_start,
                Activity.created_at < period_end,
            )
        )
        row = result.one()._mapping
        return {key: int(value or 0) for key, value in row.items()}

    async def list_for_farm(
        self,
        farm_id: UUID,
        limit: int,
        before: tuple[datetime, UUID] | None = None,
        search: str | None = None,
        category: ActivityCategory | None = None,
        from_datetime: datetime | None = None,
        to_datetime: datetime | None = None,
    ) -> list[Activity]:
        query = select(Activity).where(
            *self._farm_activity_filters(
                farm_id,
                search,
                category,
                from_datetime,
                to_datetime,
            )
        )
        if before is not None:
            created_at, activity_id = before
            query = query.where(
                or_(
                    Activity.created_at < created_at,
                    and_(
                        Activity.created_at == created_at,
                        Activity.id < activity_id,
                    ),
                )
            )
        result = await self.session.execute(
            query.order_by(desc(Activity.created_at), desc(Activity.id)).limit(limit)
        )
        return list(result.scalars().all())

    async def count_for_farm(
        self,
        farm_id: UUID,
        search: str | None = None,
        category: ActivityCategory | None = None,
        from_datetime: datetime | None = None,
        to_datetime: datetime | None = None,
    ) -> int:
        result = await self.session.execute(
            select(func.count())
            .select_from(Activity)
            .where(
                *self._farm_activity_filters(
                    farm_id,
                    search,
                    category,
                    from_datetime,
                    to_datetime,
                )
            )
        )
        return int(result.scalar_one())

    @staticmethod
    def _farm_activity_filters(
        farm_id: UUID,
        search: str | None,
        category: ActivityCategory | None,
        from_datetime: datetime | None,
        to_datetime: datetime | None,
    ):
        filters = [Activity.farm_id == farm_id]
        if from_datetime is not None:
            filters.append(Activity.created_at >= from_datetime)
        if to_datetime is not None:
            filters.append(Activity.created_at < to_datetime)
        if category == ActivityCategory.UPDATES:
            filters.append(Activity.type == ActivityType.NOTIFICATION_CREATED)
        elif category in (ActivityCategory.SALES, ActivityCategory.PURCHASES):
            transaction_type = (
                "sale" if category == ActivityCategory.SALES else "purchase"
            )
            entity_types = (
                CATEGORY_ENTITY_TYPES[ActivityCategory.SALES]
                if category == ActivityCategory.SALES
                else CATEGORY_ENTITY_TYPES[ActivityCategory.PURCHASES]
            )
            filters.append(
                or_(
                    Activity.entity_type.in_(entity_types),
                    and_(
                        Activity.entity_type.in_(
                            (
                                ActivityEntityType.TRANSACTION,
                                ActivityEntityType.TRANSACTION_PAYMENT,
                            )
                        ),
                        Activity.details["transaction_type"].as_string()
                        == transaction_type,
                    ),
                )
            )
        elif category is not None:
            filters.append(
                Activity.entity_type.in_(CATEGORY_ENTITY_TYPES[category])
            )
        if search:
            search_term = f"%{'%'.join(search.split())}%"
            filters.append(
                or_(
                    func.replace(cast(Activity.type, String), "_", " ").ilike(
                        search_term
                    ),
                    func.replace(
                        cast(Activity.entity_type, String), "_", " "
                    ).ilike(search_term),
                    cast(Activity.details, String).ilike(search_term),
                )
            )
        return filters

    async def list_for_session(
        self,
        session_id: UUID,
        limit: int,
        before: tuple[datetime, UUID] | None = None,
    ) -> list[Activity]:
        query = select(Activity).where(Activity.session_id == session_id)
        if before is not None:
            created_at, activity_id = before
            query = query.where(
                or_(
                    Activity.created_at < created_at,
                    and_(
                        Activity.created_at == created_at,
                        Activity.id < activity_id,
                    ),
                )
            )
        result = await self.session.execute(
            query.order_by(desc(Activity.created_at), desc(Activity.id)).limit(limit)
        )
        return list(result.scalars().all())