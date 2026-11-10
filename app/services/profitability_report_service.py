from collections import defaultdict
from datetime import date, datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.exceptions import ConflictError, ResourceNotFoundError
from app.core.unit_of_work import UnitOfWork
from app.models.egg_collections import EggCollection
from app.models.batch_blocks import BatchBlock
from app.models.chicken_batches import ChickenBatch
from app.models.chicken_losses import ChickenLoss
from app.models.egg_losses import EggLoss
from app.models.egg_production_cost_confirmations import EggProductionCostConfirmation
from app.models.expense_payment import ExpensePayment
from app.models.expenses import Expense
from app.models.inventory_movement import InventoryMovement
from app.models.product_consumptions import ProductConsumption
from app.models.products import Product
from app.models.product_units import ProductUnit
from app.models.purchase_return_items import PurchaseReturnItem
from app.models.purchase_returns import PurchaseReturn
from app.models.purchase_supplier_refunds import PurchaseSupplierRefund
from app.models.sale_delivery_items import SaleDeliveryItem
from app.models.sale_deliveries import SaleDelivery
from app.models.sale_return_items import SaleReturnItem
from app.models.sale_returns import SaleReturn
from app.models.transaction_refunds import TransactionRefund
from app.models.transactions import Transaction
from app.models.transaction_items import TransactionItem
from app.models.units import Unit
from app.schemas.enums import (
    ActivityEntityType,
    ActivityType,
    InventoryMovementType,
    ProductType,
    SaleReturnType,
    TransactionStatus,
    TransactionType,
)
from app.schemas.profitability_report import (
    EggProductionCostConfirmationResponse,
    EggStockReconciliationResponse,
    ProfitabilityProductResponse,
    ProfitabilityReportResponse,
    ProfitabilityStockResponse,
    ReservedEggSaleResponse,
    ProfitabilityStockValuationRequest,
    ProfitabilityStockValuationResponse,
)
from app.services.activity_service import ActivityService

ZERO = Decimal("0")
CENT = Decimal("0.01")


def _money(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def _product_margin_values(
    quantity_sold: Decimal,
    sales_value: Decimal,
    sales_credits: Decimal,
    cost_of_goods_sold: Decimal,
    uncosted_quantity: Decimal,
) -> tuple[Decimal, Decimal | None, Decimal | None, Decimal | None]:
    net_sales = sales_value - sales_credits
    cost_complete = uncosted_quantity == ZERO
    return (
        _money(net_sales),
        _money(sales_value / quantity_sold) if quantity_sold > ZERO else None,
        (
            _money(cost_of_goods_sold / quantity_sold)
            if quantity_sold > ZERO and cost_complete
            else None
        ),
        (
            _money(net_sales - cost_of_goods_sold)
            if cost_complete
            else None
        ),
    )


def _enum_value(value: Any) -> str:
    return str(getattr(value, "value", value))


def _period_contains(value: date, from_date: date, to_date: date) -> bool:
    return from_date <= value <= to_date


def net_revenue(gross_sales: Decimal, delivered_return_credits: Decimal) -> Decimal:
    return gross_sales - delivered_return_credits


def operating_expense_total(
    expenses: list[Any],
    *,
    expense_refunds: Decimal = ZERO,
) -> Decimal:
    """Exclude purchase-linked expenses; those purchases are inventory assets."""
    recorded = sum(
        (
            Decimal(expense.amount)
            for expense in expenses
            if expense.canceled_at is None
            and expense.purchase_transaction_id is None
        ),
        ZERO,
    )
    return recorded - expense_refunds


def net_profit(
    revenue: Decimal,
    cost_of_goods_sold: Decimal,
    operating_expenses: Decimal,
    inventory_losses: Decimal,
    *,
    complete: bool,
) -> Decimal | None:
    if not complete:
        return None
    return revenue - cost_of_goods_sold - operating_expenses - inventory_losses


def egg_available_quantity(
    collected: Decimal,
    losses: Decimal,
    sold: Decimal,
    delivered_returns: Decimal,
) -> Decimal:
    return max(ZERO, collected - losses - sold + delivered_returns)


def _event_date(movement: InventoryMovement) -> date:
    return movement.occurred_on


def _replay_inventory(
    movements: list[InventoryMovement],
    *,
    egg_collection_costs: dict[UUID, Decimal | None] | None = None,
    sale_delivery_items: dict[UUID, UUID] | None = None,
    sale_return_items: dict[UUID, UUID] | None = None,
    valuation_quantities: dict[UUID, Decimal] | None = None,
) -> tuple[dict[UUID, Decimal | None], dict[UUID, dict[str, Decimal]]]:
    """Replay the farm ledger without assigning a value to an uncosted quantity."""
    egg_collection_costs = egg_collection_costs or {}
    sale_delivery_items = sale_delivery_items or {}
    sale_return_items = sale_return_items or {}
    quantities: dict[UUID, Decimal] = defaultdict(lambda: ZERO)
    known_quantities: dict[UUID, Decimal] = defaultdict(lambda: ZERO)
    known_values: dict[UUID, Decimal] = defaultdict(lambda: ZERO)
    unknown_quantities: dict[UUID, Decimal] = defaultdict(lambda: ZERO)
    deficit_quantities: dict[UUID, Decimal] = defaultdict(lambda: ZERO)
    effective_costs: dict[UUID, Decimal | None] = {}
    sale_item_costs: dict[UUID, Decimal] = defaultdict(lambda: ZERO)
    sale_item_quantities: dict[UUID, Decimal] = defaultdict(lambda: ZERO)
    unknown_sale_items: set[UUID] = set()

    estimated_valuation_keys = {
        (movement.product_id, movement.occurred_on)
        for movement in movements
        if movement.source_type == "estimated_stock_valuation"
    }

    def movement_order(movement: InventoryMovement) -> tuple[Any, ...]:
        if (movement.product_id, movement.occurred_on) not in estimated_valuation_keys:
            return (movement.occurred_on, 0, movement.created_at, movement.id)
        if movement.source_type == "estimated_stock_valuation":
            priority = 1
        elif Decimal(movement.quantity_delta) > ZERO:
            priority = 0
        elif Decimal(movement.quantity_delta) < ZERO:
            priority = 2
        else:
            priority = 3
        return (movement.occurred_on, priority, movement.created_at, movement.id)

    for movement in sorted(movements, key=movement_order):
        product_id = movement.product_id
        delta = Decimal(movement.quantity_delta)
        unit_cost = movement.unit_cost
        movement_type = _enum_value(movement.movement_type)
        if movement_type == InventoryMovementType.VALUATION.value:
            if unit_cost is None:
                raise ConflictError(
                    "A stock valuation movement is missing its unit cost."
                )
            unvalued = unknown_quantities[product_id]
            unknown_quantities[product_id] = ZERO
            known_quantities[product_id] += unvalued
            known_values[product_id] += unvalued * Decimal(unit_cost)
            if valuation_quantities is not None:
                valuation_quantities[movement.id] = unvalued
            effective_costs[movement.id] = None
            continue
        if (
            movement.source_type == "egg_collection"
            and movement.source_id is not None
            and movement.source_id in egg_collection_costs
        ):
            unit_cost = egg_collection_costs[movement.source_id]
        if movement.source_type == "sale_delivery":
            sale_item_id = (
                sale_delivery_items.get(movement.source_item_id)
                if movement.source_item_id is not None
                else None
            )
        elif movement.source_type == "transaction":
            sale_item_id = movement.source_item_id
        else:
            sale_item_id = None
        if (
            movement.source_type == "sale_return"
            and unit_cost is None
            and movement.source_item_id is not None
            and movement.source_item_id in sale_return_items
        ):
            returned_item_id = sale_return_items[movement.source_item_id]
            delivered_quantity = sale_item_quantities.get(returned_item_id, ZERO)
            if (
                delivered_quantity > ZERO
                and returned_item_id not in unknown_sale_items
            ):
                unit_cost = (
                    sale_item_costs[returned_item_id] / delivered_quantity
                )

        if delta > ZERO:
            quantities[product_id] += delta
            deficit_covered = min(deficit_quantities[product_id], delta)
            deficit_quantities[product_id] -= deficit_covered
            received = delta - deficit_covered
            if received:
                if unit_cost is None:
                    unknown_quantities[product_id] += received
                else:
                    unit_cost = Decimal(unit_cost)
                    known_quantities[product_id] += received
                    known_values[product_id] += received * unit_cost
            effective_costs[movement.id] = (
                Decimal(unit_cost) if unit_cost is not None else None
            )
            continue

        removed = -delta
        quantities[product_id] -= removed
        if unit_cost is None:
            unknown_removed = min(unknown_quantities[product_id], removed)
            unknown_quantities[product_id] -= unknown_removed
            remaining = removed - unknown_removed
            known_removed = min(known_quantities[product_id], remaining)
            average_before_removal: Decimal | None = None
            if known_removed and known_quantities[product_id] > ZERO:
                average_before_removal = (
                    known_values[product_id] / known_quantities[product_id]
                )
                known_quantities[product_id] -= known_removed
                known_values[product_id] = max(
                    ZERO,
                    known_values[product_id]
                    - known_removed * average_before_removal,
                )
            deficit_quantities[product_id] += remaining - known_removed
            movement_cost: Decimal | None = (
                None
                if unknown_removed or unknown_quantities[product_id] > ZERO
                or deficit_quantities[product_id] > ZERO
                else (
                    known_values[product_id] / known_quantities[product_id]
                    if known_quantities[product_id] > ZERO
                    else None
                )
            )
            if known_removed and not unknown_removed and not deficit_quantities[product_id]:
                movement_cost = average_before_removal
            effective_costs[movement.id] = movement_cost
            if sale_item_id is not None and _enum_value(movement.movement_type) == "sale":
                sale_item_quantities[sale_item_id] += removed
                if movement_cost is None:
                    unknown_sale_items.add(sale_item_id)
                else:
                    sale_item_costs[sale_item_id] += removed * movement_cost
            continue

        if unit_cost is not None:
            unit_cost = Decimal(unit_cost)
            unknown_removed = min(unknown_quantities[product_id], removed)
            unknown_quantities[product_id] -= unknown_removed
            known_removed = min(
                known_quantities[product_id],
                removed - unknown_removed,
            )
            known_quantities[product_id] -= known_removed
            known_values[product_id] = max(
                ZERO,
                known_values[product_id] - known_removed * unit_cost,
            )
            effective_costs[movement.id] = unit_cost
            if sale_item_id is not None and _enum_value(movement.movement_type) == "sale":
                sale_item_quantities[sale_item_id] += removed
                sale_item_costs[sale_item_id] += removed * unit_cost
            continue

    stock: dict[UUID, dict[str, Decimal]] = {}
    for product_id, quantity in quantities.items():
        stock[product_id] = {
            "quantity": quantity,
            "valued_quantity": known_quantities[product_id],
            "valued_cost": known_values[product_id],
            "unvalued_quantity": unknown_quantities[product_id],
        }
    return effective_costs, stock


def _egg_sale_quantity_deducted_as_of(
    quantity: Decimal,
    conversion_factor: Decimal,
    fulfillment_required: bool,
    delivered_quantity: Decimal,
) -> Decimal:
    if fulfillment_required:
        return delivered_quantity
    return quantity * conversion_factor


def _requires_direct_sale_inventory_movement(
    product_type: str,
    fulfillment_required: bool,
) -> bool:
    return not (
        product_type == ProductType.EGGS.value
        and fulfillment_required
    )


def _reserved_egg_quantity(
    ordered_quantity: Decimal,
    delivered_quantity: Decimal,
    cancelled_quantity: Decimal = ZERO,
) -> Decimal:
    return max(
        ZERO,
        ordered_quantity - delivered_quantity - cancelled_quantity,
    )


class ProfitabilityReportService:
    def __init__(
        self,
        session: AsyncSession,
        unit_of_work: UnitOfWork,
        activity_service: ActivityService,
    ) -> None:
        self.session = session
        self.unit_of_work = unit_of_work
        self.activity_service = activity_service

    async def confirm_zero_egg_production_cost(
        self,
        farm_id: UUID,
        *,
        user_id: UUID,
        from_date: date,
        to_date: date,
    ) -> EggProductionCostConfirmationResponse:
        if from_date > to_date:
            raise ConflictError(
                "Report start date must be on or before its end date."
            )

        async with self.unit_of_work:
            collections_exist = (
                await self.session.execute(
                    select(EggCollection.id)
                    .join(Product, Product.id == EggCollection.product_id)
                    .where(
                        EggCollection.farm_id == farm_id,
                        EggCollection.entry_type == "collection",
                        EggCollection.collected_at >= datetime.combine(
                            from_date, datetime.min.time()
                        ),
                        EggCollection.collected_at
                        <= datetime.combine(to_date, datetime.max.time()),
                        Product.product_type == ProductType.EGGS,
                    )
                    .limit(1)
                )
            ).scalar_one_or_none()
            if collections_exist is None:
                raise ConflictError(
                    "No egg production was recorded in this report period."
                )

            consumption_exists = (
                await self.session.execute(
                    select(ProductConsumption.id)
                    .where(
                        ProductConsumption.farm_id == farm_id,
                        ProductConsumption.consumption_date >= from_date,
                        ProductConsumption.consumption_date <= to_date,
                    )
                    .limit(1)
                )
            ).scalar_one_or_none()
            if consumption_exists is not None:
                raise ConflictError(
                    "Product use is recorded in this period. Review its cost instead "
                    "of confirming zero production cost."
                )

            confirmation = (
                await self.session.execute(
                    select(EggProductionCostConfirmation).where(
                        EggProductionCostConfirmation.farm_id == farm_id,
                        EggProductionCostConfirmation.from_date == from_date,
                        EggProductionCostConfirmation.to_date == to_date,
                    )
                )
            ).scalar_one_or_none()
            if confirmation is None:
                confirmation = EggProductionCostConfirmation(
                    farm_id=farm_id,
                    confirmed_by=user_id,
                    from_date=from_date,
                    to_date=to_date,
                )
                self.session.add(confirmation)
            else:
                confirmation.confirmed_by = user_id
                confirmation.confirmed_at = datetime.now(timezone.utc)

            await self.unit_of_work.commit()

        return EggProductionCostConfirmationResponse(
            confirmed=True,
            from_date=from_date,
            to_date=to_date,
        )

    async def _egg_stock_as_of(
        self,
        farm_id: UUID,
        as_of: date,
        product_ids: list[UUID],
    ) -> dict[UUID, Decimal]:
        if not product_ids:
            return {}
        cutoff = datetime.combine(
            as_of,
            datetime.max.time(),
            tzinfo=timezone.utc,
        )
        collected_rows = (
            await self.session.execute(
                select(
                    EggCollection.product_id,
                    func.coalesce(
                        func.sum(
                            EggCollection.quantity * EggCollection.conversion_factor
                        ),
                        0,
                    ),
                )
                .where(
                    EggCollection.farm_id == farm_id,
                    EggCollection.product_id.in_(product_ids),
                    EggCollection.collected_at <= cutoff,
                )
                .group_by(EggCollection.product_id)
            )
        ).all()
        loss_rows = (
            await self.session.execute(
                select(
                    EggLoss.product_id,
                    func.coalesce(
                        func.sum(EggLoss.quantity * EggLoss.conversion_factor),
                        0,
                    ),
                )
                .where(
                    EggLoss.farm_id == farm_id,
                    EggLoss.product_id.in_(product_ids),
                    EggLoss.loss_date <= as_of,
                )
                .group_by(EggLoss.product_id)
            )
        ).all()
        delivered_quantities = (
            select(
                SaleDeliveryItem.transaction_item_id.label("transaction_item_id"),
                func.sum(SaleDeliveryItem.quantity).label("quantity"),
            )
            .join(
                SaleDelivery,
                SaleDelivery.id == SaleDeliveryItem.sale_delivery_id,
            )
            .where(SaleDelivery.delivered_date <= as_of)
            .group_by(SaleDeliveryItem.transaction_item_id)
            .subquery()
        )
        sale_rows = (
            await self.session.execute(
                select(
                    TransactionItem.product_id,
                    TransactionItem.quantity,
                    TransactionItem.conversion_factor,
                    Transaction.fulfillment_required,
                    func.coalesce(delivered_quantities.c.quantity, 0),
                )
                .join(Transaction, Transaction.id == TransactionItem.transaction_id)
                .outerjoin(
                    delivered_quantities,
                    delivered_quantities.c.transaction_item_id == TransactionItem.id,
                )
                .where(
                    Transaction.farm_id == farm_id,
                    Transaction.transaction_type == TransactionType.SALE,
                    Transaction.status == TransactionStatus.COMPLETED,
                    Transaction.transaction_date <= as_of,
                    TransactionItem.product_id.in_(product_ids),
                )
            )
        ).all()
        return_rows = (
            await self.session.execute(
                select(
                    TransactionItem.product_id,
                    func.coalesce(
                        func.sum(
                            SaleReturnItem.quantity
                            * TransactionItem.conversion_factor
                        ),
                        0,
                    ),
                )
                .join(
                    TransactionItem,
                    TransactionItem.id == SaleReturnItem.transaction_item_id,
                )
                .join(
                    SaleReturn,
                    SaleReturn.id == SaleReturnItem.sale_return_id,
                )
                .join(Transaction, Transaction.id == SaleReturn.transaction_id)
                .where(
                    Transaction.farm_id == farm_id,
                    SaleReturn.return_date <= as_of,
                    SaleReturn.return_type == "delivered_return",
                    TransactionItem.product_id.in_(product_ids),
                )
                .group_by(TransactionItem.product_id)
            )
        ).all()
        collected = {product_id: Decimal(value) for product_id, value in collected_rows}
        losses = {product_id: Decimal(value) for product_id, value in loss_rows}
        sold: defaultdict[UUID, Decimal] = defaultdict(lambda: ZERO)
        for (
            product_id,
            quantity,
            conversion_factor,
            fulfillment_required,
            delivered_quantity,
        ) in sale_rows:
            sold[product_id] += _egg_sale_quantity_deducted_as_of(
                Decimal(quantity),
                Decimal(conversion_factor),
                fulfillment_required,
                Decimal(delivered_quantity),
            )
        returned = {product_id: Decimal(value) for product_id, value in return_rows}
        return {
            product_id: egg_available_quantity(
                collected.get(product_id, ZERO),
                losses.get(product_id, ZERO),
                sold.get(product_id, ZERO),
                returned.get(product_id, ZERO),
            )
            for product_id in product_ids
        }

    async def record_stock_valuation(
        self,
        farm_id: UUID,
        *,
        user_id: UUID,
        request: ProfitabilityStockValuationRequest,
    ) -> ProfitabilityStockValuationResponse:
        valuation_date = date.today()
        async with self.unit_of_work:
            product = (
                await self.session.execute(
                    select(Product)
                    .where(
                        Product.farm_id == farm_id,
                        Product.id == request.product_id,
                    )
                    .options(
                        selectinload(Product.product_units).selectinload(
                            ProductUnit.unit
                        )
                    )
                    .with_for_update()
                )
            ).scalar_one_or_none()
            if product is None:
                raise ResourceNotFoundError(
                    "The inventory product was not found for this farm."
                )
            base_unit = next(
                (
                    product_unit.unit
                    for product_unit in product.product_units
                    if product_unit.is_base_unit
                ),
                None,
            )
            if base_unit is None:
                raise ConflictError(
                    f"Base unit is missing for '{product.name}'. "
                    "Configure the product before recording stock cost."
                )
            if request.from_date is not None and request.to_date is not None:
                return await self._record_historical_stock_estimate(
                    farm_id=farm_id,
                    user_id=user_id,
                    product=product,
                    base_unit=base_unit,
                    unit_cost=request.unit_cost,
                    from_date=request.from_date,
                    to_date=request.to_date,
                )

            movements = list(
                (
                    await self.session.execute(
                        select(InventoryMovement)
                        .where(
                            InventoryMovement.farm_id == farm_id,
                            InventoryMovement.product_id == product.id,
                            InventoryMovement.occurred_on <= valuation_date,
                        )
                        .order_by(
                            InventoryMovement.occurred_on,
                            InventoryMovement.created_at,
                            InventoryMovement.id,
                        )
                    )
                ).scalars().all()
            )
            stock = _replay_inventory(movements)[1].get(product.id, {})
            unvalued_quantity = stock.get("unvalued_quantity", ZERO)
            untracked_quantity = ZERO

            if product.product_type == ProductType.CHICKENS:
                chicken_products = list(
                    (
                        await self.session.execute(
                            select(Product)
                            .where(
                                Product.farm_id == farm_id,
                                Product.product_type == ProductType.CHICKENS,
                                Product.is_active.is_(True),
                            )
                            .order_by(Product.id)
                        )
                    ).scalars().all()
                )
                actual_chickens = Decimal(
                    (
                        await self.session.execute(
                            select(func.coalesce(func.sum(BatchBlock.quantity), 0))
                            .join(
                                ChickenBatch,
                                ChickenBatch.id == BatchBlock.batch_id,
                            )
                            .where(ChickenBatch.farm_id == farm_id)
                        )
                    ).scalar_one()
                )
                ledger_chickens = Decimal(
                    (
                        await self.session.execute(
                            select(
                                func.coalesce(
                                    func.sum(InventoryMovement.quantity_delta), 0
                                )
                            )
                            .join(Product, Product.id == InventoryMovement.product_id)
                            .where(
                                InventoryMovement.farm_id == farm_id,
                                InventoryMovement.occurred_on <= valuation_date,
                                Product.product_type == ProductType.CHICKENS,
                            )
                        )
                    ).scalar_one()
                )
                untracked_quantity = max(
                    ZERO,
                    actual_chickens - ledger_chickens,
                )
                if (
                    untracked_quantity
                    and len(chicken_products) != 1
                    and unvalued_quantity <= ZERO
                ):
                    raise ConflictError(
                        "Current chicken batches are not fully represented by one "
                        "chicken inventory product. Reconcile chicken product links "
                        "before valuing the opening flock."
                    )
                if len(chicken_products) != 1:
                    untracked_quantity = ZERO
            elif product.product_type == ProductType.EGGS:
                actual_egg_stock = await self._egg_stock_as_of(
                    farm_id,
                    valuation_date,
                    [product.id],
                )
                ledger_quantity = stock.get("quantity", ZERO)
                untracked_quantity = max(
                    ZERO,
                    actual_egg_stock.get(product.id, ZERO) - ledger_quantity,
                )

            if unvalued_quantity <= ZERO and untracked_quantity <= ZERO:
                raise ConflictError(
                    "This product has no unvalued stock to assign a cost to."
                )

            audit_movement: InventoryMovement | None = None
            if untracked_quantity > ZERO:
                opening_movement = InventoryMovement(
                    farm_id=farm_id,
                    user_id=user_id,
                    product_id=product.id,
                    unit_id=base_unit.id,
                    quantity_delta=untracked_quantity,
                    movement_type=InventoryMovementType.OPENING_BALANCE,
                    source_type="stock_valuation_opening",
                    source_id=uuid4(),
                    source_item_id=product.id,
                    unit_cost=request.unit_cost,
                    occurred_on=valuation_date,
                    notes=(
                        "Opening flock reconciled during stock valuation"
                        if product.product_type == ProductType.CHICKENS
                        else "Opening egg stock reconciled during stock valuation"
                    ),
                )
                self.session.add(opening_movement)
                audit_movement = opening_movement

            if unvalued_quantity > ZERO:
                valuation_movement = InventoryMovement(
                    farm_id=farm_id,
                    user_id=user_id,
                    product_id=product.id,
                    unit_id=base_unit.id,
                    quantity_delta=ZERO,
                    movement_type=InventoryMovementType.VALUATION,
                    source_type="stock_valuation",
                    source_id=uuid4(),
                    source_item_id=product.id,
                    unit_cost=request.unit_cost,
                    occurred_on=valuation_date,
                    notes="Current unvalued stock cost baseline",
                )
                self.session.add(valuation_movement)
                audit_movement = valuation_movement

            if audit_movement is None:
                raise ConflictError(
                    "No stock quantity could be included in this valuation."
                )
            await self.session.flush()
            await self.activity_service.record(
                farm_id=farm_id,
                user_id=user_id,
                activity_type=ActivityType.INVENTORY_ADJUSTED,
                entity_type=ActivityEntityType.INVENTORY_MOVEMENT,
                entity_id=audit_movement.id,
                details={
                    "product_id": str(product.id),
                    "product_name": product.name,
                    "movement_type": "stock_valuation",
                    "unit_cost": str(request.unit_cost),
                    "unit_name": base_unit.name,
                    "quantity_valued": str(
                        unvalued_quantity + untracked_quantity
                    ),
                    "valuation_date": valuation_date.isoformat(),
                },
            )
            await self.unit_of_work.commit()
            return ProfitabilityStockValuationResponse(
                product_id=product.id,
                product_name=product.name,
                unit_name=base_unit.name,
                unit_abbreviation=base_unit.abbreviation,
                valuation_date=valuation_date,
                quantity_valued=unvalued_quantity + untracked_quantity,
                unit_cost=request.unit_cost,
                inventory_movement_id=audit_movement.id,
            )

    async def _record_historical_stock_estimate(
        self,
        *,
        farm_id: UUID,
        user_id: UUID,
        product: Product,
        base_unit: Unit,
        unit_cost: Decimal,
        from_date: date,
        to_date: date,
    ) -> ProfitabilityStockValuationResponse:
        if to_date > date.today():
            raise ConflictError("The report period cannot end in the future.")

        movements = list(
            (
                await self.session.execute(
                    select(InventoryMovement)
                    .where(
                        InventoryMovement.farm_id == farm_id,
                        InventoryMovement.product_id == product.id,
                        InventoryMovement.occurred_on <= to_date,
                    )
                    .order_by(
                        InventoryMovement.occurred_on,
                        InventoryMovement.created_at,
                        InventoryMovement.id,
                    )
                    .with_for_update()
                )
            ).scalars().all()
        )
        current_costs, _ = _replay_inventory(movements)
        target_movements = [
            movement
            for movement in movements
            if _enum_value(movement.movement_type)
            in {
                InventoryMovementType.SALE.value,
                InventoryMovementType.CONSUMPTION.value,
                InventoryMovementType.LOSS.value,
            }
            and movement.quantity_delta < ZERO
            and from_date <= movement.occurred_on <= to_date
            and current_costs.get(movement.id) is None
        ]
        if not target_movements:
            raise ConflictError(
                f"No uncosted inventory movement for '{product.name}' can be fixed "
                "with an estimated stock cost in this report period."
            )

        candidate_dates = sorted(
            {movement.occurred_on for movement in target_movements} | {to_date}
        )
        estimates = [
            InventoryMovement(
                id=uuid4(),
                farm_id=farm_id,
                user_id=user_id,
                product_id=product.id,
                unit_id=base_unit.id,
                quantity_delta=ZERO,
                movement_type=InventoryMovementType.VALUATION,
                source_type="estimated_stock_valuation",
                source_id=uuid4(),
                source_item_id=product.id,
                unit_cost=unit_cost,
                occurred_on=valuation_date,
                notes="User-entered estimated cost for historical stock activity",
            )
            for valuation_date in candidate_dates
        ]
        valuation_quantities: dict[UUID, Decimal] = {}
        estimated_costs, _ = _replay_inventory(
            [*movements, *estimates],
            valuation_quantities=valuation_quantities,
        )
        resolved_movements = [
            movement
            for movement in target_movements
            if estimated_costs.get(movement.id) is not None
        ]
        if not resolved_movements:
            raise ConflictError(
                f"No uncosted stock quantity for '{product.name}' is available "
                "to estimate before its sales in this period."
            )

        resolved_dates = {movement.occurred_on for movement in resolved_movements}
        applied_estimates = [
            estimate
            for estimate in estimates
            if (
                estimate.occurred_on in resolved_dates
                or estimate.occurred_on == to_date
            )
            and valuation_quantities.get(estimate.id, ZERO) > ZERO
        ]
        if not applied_estimates:
            raise ConflictError(
                f"No uncosted stock quantity for '{product.name}' was valued."
            )

        self.session.add_all(applied_estimates)
        await self.session.flush()
        await self.activity_service.record(
            farm_id=farm_id,
            user_id=user_id,
            activity_type=ActivityType.INVENTORY_ADJUSTED,
            entity_type=ActivityEntityType.INVENTORY_MOVEMENT,
            entity_id=applied_estimates[0].id,
            details={
                "product_id": str(product.id),
                "product_name": product.name,
                "unit_cost": str(unit_cost),
                "estimated": True,
                "from_date": from_date.isoformat(),
                "to_date": to_date.isoformat(),
                "valuation_dates": [
                    movement.occurred_on.isoformat()
                    for movement in applied_estimates
                ],
            },
        )
        await self.unit_of_work.commit()
        return ProfitabilityStockValuationResponse(
            product_id=product.id,
            product_name=product.name,
            unit_name=base_unit.name,
            unit_abbreviation=base_unit.abbreviation,
            valuation_date=min(
                movement.occurred_on for movement in applied_estimates
            ),
            quantity_valued=sum(
                (valuation_quantities[movement.id] for movement in applied_estimates),
                ZERO,
            ),
            unit_cost=unit_cost,
            inventory_movement_id=applied_estimates[0].id,
        )

    async def build_report(
        self,
        farm_id: UUID,
        *,
        from_date: date,
        to_date: date,
    ) -> ProfitabilityReportResponse:
        products = list(
            (
                await self.session.execute(
                    select(Product)
                    .where(Product.farm_id == farm_id)
                    .options(
                        selectinload(Product.product_units).selectinload(
                            ProductUnit.unit
                        )
                    )
                )
            ).scalars().all()
        )
        product_by_id = {product.id: product for product in products}
        product_performance: dict[UUID, dict[str, Any]] = {}

        def performance_for(product_id: UUID) -> dict[str, Any] | None:
            product = product_by_id.get(product_id)
            if product is None:
                return None
            if product_id not in product_performance:
                base_unit = next(
                    (
                        product_unit.unit
                        for product_unit in product.product_units
                        if product_unit.is_base_unit
                    ),
                    None,
                )
                if base_unit is None:
                    raise ConflictError(
                        f"Base unit is missing for inventory product '{product.name}'. "
                        "Configure a base unit before generating profitability reports."
                    )
                product_performance[product_id] = {
                    "product_id": product_id,
                    "product_name": product.name,
                    "product_type": _enum_value(product.product_type),
                    "unit_name": base_unit.name,
                    "unit_abbreviation": base_unit.abbreviation,
                    "quantity_sold": ZERO,
                    "sales_value": ZERO,
                    "sales_credits": ZERO,
                    "cost_of_goods_sold": ZERO,
                    "uncosted_quantity": ZERO,
                    "uncosted_movement_quantity": ZERO,
                    "uncosted_movement_types": set(),
                }
            return product_performance[product_id]

        transactions = list(
            (
                await self.session.execute(
                    select(Transaction)
                    .where(
                        Transaction.farm_id == farm_id,
                        Transaction.transaction_date <= to_date,
                    )
                    .options(selectinload(Transaction.items))
                )
            ).scalars().all()
        )
        transaction_item_by_id = {
            item.id: item for transaction in transactions for item in transaction.items
        }
        movements = list(
            (
                await self.session.execute(
                    select(InventoryMovement)
                    .where(
                        InventoryMovement.farm_id == farm_id,
                        InventoryMovement.occurred_on <= to_date,
                    )
                    .order_by(
                        InventoryMovement.occurred_on,
                        InventoryMovement.created_at,
                        InventoryMovement.id,
                    )
                )
            ).scalars().all()
        )
        all_deliveries = list(
            (
                await self.session.execute(
                    select(SaleDeliveryItem, SaleDelivery)
                    .join(SaleDelivery, SaleDelivery.id == SaleDeliveryItem.sale_delivery_id)
                    .join(Transaction, Transaction.id == SaleDelivery.transaction_id)
                    .where(
                        Transaction.farm_id == farm_id,
                        SaleDelivery.delivered_date <= to_date,
                    )
                )
            ).all()
        )
        delivered_quantity_by_item: dict[UUID, Decimal] = {}
        for delivery_item, _ in all_deliveries:
            delivered_quantity_by_item[delivery_item.transaction_item_id] = (
                delivered_quantity_by_item.get(
                    delivery_item.transaction_item_id,
                    ZERO,
                )
                + Decimal(delivery_item.quantity)
            )
        sale_delivery_item_to_transaction_item = {
            delivery_item.id: delivery_item.transaction_item_id
            for delivery_item, _ in all_deliveries
        }
        sale_return_item_rows = list(
            (
                await self.session.execute(
                    select(SaleReturnItem, SaleReturn.return_type)
                    .join(SaleReturn, SaleReturn.id == SaleReturnItem.sale_return_id)
                    .join(Transaction, Transaction.id == SaleReturn.transaction_id)
                    .where(Transaction.farm_id == farm_id, SaleReturn.return_date <= to_date)
                )
            ).all()
        )
        cancelled_quantity_by_item: dict[UUID, Decimal] = {}
        for return_item, return_type in sale_return_item_rows:
            if return_type != SaleReturnType.UNDELIVERED_CANCELLED.value:
                continue
            cancelled_quantity_by_item[return_item.transaction_item_id] = (
                cancelled_quantity_by_item.get(return_item.transaction_item_id, ZERO)
                + Decimal(return_item.quantity)
            )
        reserved_egg_sales = []
        for transaction in transactions:
            if (
                _enum_value(transaction.transaction_type) != "sale"
                or _enum_value(transaction.status) != "completed"
                or not transaction.fulfillment_required
            ):
                continue
            for item in transaction.items:
                product = product_by_id.get(item.product_id)
                if (
                    product is None
                    or _enum_value(product.product_type) != ProductType.EGGS.value
                ):
                    continue
                ordered_quantity = Decimal(item.quantity) * Decimal(
                    item.conversion_factor
                )
                reserved_quantity = _reserved_egg_quantity(
                    ordered_quantity,
                    delivered_quantity_by_item.get(item.id, ZERO),
                    cancelled_quantity_by_item.get(item.id, ZERO),
                )
                if reserved_quantity <= ZERO:
                    continue
                base_unit = next(
                    (
                        product_unit.unit
                        for product_unit in product.product_units
                        if product_unit.is_base_unit
                    ),
                    None,
                )
                reserved_egg_sales.append(
                    ReservedEggSaleResponse(
                        transaction_id=transaction.id,
                        reference_number=transaction.reference_number,
                        transaction_date=transaction.transaction_date,
                        product_id=product.id,
                        product_name=product.name,
                        unit_abbreviation=(
                            base_unit.abbreviation if base_unit is not None else "units"
                        ),
                        reserved_quantity=reserved_quantity,
                    )
                )
        reserved_egg_sales.sort(
            key=lambda item: (
                item.transaction_date,
                item.product_name.casefold(),
                str(item.transaction_id),
            )
        )
        sale_return_item_to_transaction_item = {
            row.id: row.transaction_item_id for row, _ in sale_return_item_rows
        }
        consumption_rows = list(
            (
                await self.session.execute(
                    select(ProductConsumption).where(
                        ProductConsumption.farm_id == farm_id,
                        ProductConsumption.consumption_date >= from_date,
                        ProductConsumption.consumption_date <= to_date,
                    )
                )
            ).scalars().all()
        )
        collection_rows = list(
            (
                await self.session.execute(
                    select(EggCollection).where(
                        EggCollection.farm_id == farm_id,
                        EggCollection.collected_at >= datetime.combine(
                            from_date, datetime.min.time()
                        ),
                        EggCollection.collected_at
                        <= datetime.combine(to_date, datetime.max.time()),
                    )
                )
            ).scalars().all()
        )
        has_egg_production = any(
            collection.entry_type == "collection"
            and (product := product_by_id.get(collection.product_id)) is not None
            and _enum_value(product.product_type) == ProductType.EGGS.value
            for collection in collection_rows
        )
        zero_egg_cost_confirmation = None
        if has_egg_production and not consumption_rows:
            zero_egg_cost_confirmation = (
                await self.session.execute(
                    select(EggProductionCostConfirmation.id).where(
                        EggProductionCostConfirmation.farm_id == farm_id,
                        EggProductionCostConfirmation.from_date == from_date,
                        EggProductionCostConfirmation.to_date == to_date,
                    )
                )
            ).scalar_one_or_none()
        egg_production_zero_cost_confirmed = (
            zero_egg_cost_confirmation is not None
        )

        consumption_by_id = {row.id: row for row in consumption_rows}
        consumption_movement_by_id = {
            movement.source_id: movement
            for movement in movements
            if movement.source_type == "product_consumption"
            and movement.source_id in consumption_by_id
        }

        # First pass prices recorded consumption at the moving average of its inputs.
        preliminary_costs, _ = _replay_inventory(
            movements,
            sale_delivery_items=sale_delivery_item_to_transaction_item,
            sale_return_items=sale_return_item_to_transaction_item,
        )
        consumption_cost_by_id: dict[UUID, Decimal | None] = {}
        missing_inventory_record_count = 0
        for consumption_id, consumption in consumption_by_id.items():
            movement = consumption_movement_by_id.get(consumption_id)
            if movement is None:
                missing_inventory_record_count += 1
                consumption_cost_by_id[consumption_id] = None
                continue
            unit_cost = preliminary_costs.get(movement.id)
            consumption_cost_by_id[consumption_id] = (
                abs(Decimal(movement.quantity_delta)) * unit_cost
                if unit_cost is not None
                else None
            )

        egg_outputs_by_block: dict[UUID, Decimal] = defaultdict(lambda: ZERO)
        for collection in collection_rows:
            if collection.entry_type == "collection":
                product = product_by_id.get(collection.product_id)
                if product is not None and _enum_value(product.product_type) == "eggs":
                    egg_outputs_by_block[collection.block_id] += (
                        Decimal(collection.quantity) * Decimal(collection.conversion_factor)
                    )
        consumption_cost_by_block: dict[UUID, Decimal] = defaultdict(lambda: ZERO)
        unknown_consumption_blocks: set[UUID] = set()
        unassigned_consumption_cost = ZERO
        has_unassigned_consumption = False
        unknown_unassigned_consumption = False
        total_consumption_cost = ZERO
        unvalued_consumption_records = 0
        for consumption_id, consumption in consumption_by_id.items():
            value = consumption_cost_by_id.get(consumption_id)
            if value is None:
                unvalued_consumption_records += 1
                if consumption.block_id is None:
                    unknown_unassigned_consumption = True
                else:
                    unknown_consumption_blocks.add(consumption.block_id)
                continue
            total_consumption_cost += value
            if consumption.block_id is None:
                has_unassigned_consumption = True
                unassigned_consumption_cost += value
            else:
                consumption_cost_by_block[consumption.block_id] += value

        allocatable_block_costs: dict[UUID, Decimal] = {}
        for block_id, amount in consumption_cost_by_block.items():
            if egg_outputs_by_block.get(block_id, ZERO) > ZERO:
                allocatable_block_costs[block_id] = amount
        total_egg_output = sum(egg_outputs_by_block.values(), ZERO)
        collection_costs: dict[UUID, Decimal | None] = {}
        allocated_egg_cost = ZERO
        for collection in collection_rows:
            if collection.entry_type != "collection":
                continue
            product = product_by_id.get(collection.product_id)
            if product is None or _enum_value(product.product_type) != "eggs":
                continue
            if egg_production_zero_cost_confirmed:
                collection_costs[collection.id] = ZERO
                continue
            block_id = collection.block_id
            block_output = egg_outputs_by_block[block_id]
            block_cost = allocatable_block_costs.get(block_id)
            has_unknown_cost = (
                block_id in unknown_consumption_blocks
                or unknown_unassigned_consumption
            )
            if (
                block_cost is None
                and not has_unassigned_consumption
            ):
                collection_costs[collection.id] = None
                continue
            amount = (
                (block_cost or ZERO) * (
                    Decimal(collection.quantity) * Decimal(collection.conversion_factor)
                ) / block_output
                if block_output > ZERO and block_cost is not None
                else ZERO
            )
            if unassigned_consumption_cost and total_egg_output > ZERO:
                amount += unassigned_consumption_cost * (
                    Decimal(collection.quantity) * Decimal(collection.conversion_factor)
                ) / total_egg_output
            if has_unknown_cost:
                collection_costs[collection.id] = None
            else:
                qty = Decimal(collection.quantity) * Decimal(collection.conversion_factor)
                collection_costs[collection.id] = amount / qty if qty else None
                allocated_egg_cost += amount

        effective_costs, closing = _replay_inventory(
            movements,
            egg_collection_costs=collection_costs,
            sale_delivery_items=sale_delivery_item_to_transaction_item,
            sale_return_items=sale_return_item_to_transaction_item,
        )

        deliveries = list(
            (
                await self.session.execute(
                    select(SaleDeliveryItem, SaleDelivery)
                    .join(SaleDelivery, SaleDelivery.id == SaleDeliveryItem.sale_delivery_id)
                    .join(Transaction, Transaction.id == SaleDelivery.transaction_id)
                    .where(
                        Transaction.farm_id == farm_id,
                        SaleDelivery.delivered_date >= from_date,
                        SaleDelivery.delivered_date <= to_date,
                    )
                )
            ).all()
        )
        delivered_by_item: dict[UUID, Decimal] = defaultdict(lambda: ZERO)
        for delivery_item, _ in deliveries:
            delivered_by_item[delivery_item.transaction_item_id] += Decimal(
                delivery_item.quantity
            )

        gross_sales = ZERO
        for transaction in transactions:
            if (
                _enum_value(transaction.transaction_type) != "sale"
                or _enum_value(transaction.status) != "completed"
            ):
                continue
            for item in transaction.items:
                product = product_by_id.get(item.product_id)
                if product is None:
                    continue
                is_chicken = _enum_value(product.product_type) == "chickens"
                if is_chicken:
                    delivered_quantity = delivered_by_item.get(item.id, ZERO)
                    denominator = Decimal(item.quantity) * Decimal(item.conversion_factor)
                    if denominator and delivered_quantity:
                        item_sales = (
                            Decimal(item.total_amount) * delivered_quantity / denominator
                        )
                        gross_sales += item_sales
                        row = performance_for(item.product_id)
                        if row is not None:
                            row["quantity_sold"] += delivered_quantity
                            row["sales_value"] += item_sales
                elif _period_contains(
                    transaction.transaction_date,
                    from_date,
                    to_date,
                ):
                    gross_sales += Decimal(item.total_amount)
                    row = performance_for(item.product_id)
                    if row is not None:
                        row["quantity_sold"] += (
                            Decimal(item.quantity) * Decimal(item.conversion_factor)
                        )
                        row["sales_value"] += Decimal(item.total_amount)

        sale_returns = list(
            (
                await self.session.execute(
                    select(SaleReturn, SaleReturnItem)
                    .join(SaleReturnItem, SaleReturnItem.sale_return_id == SaleReturn.id)
                    .join(Transaction, Transaction.id == SaleReturn.transaction_id)
                    .where(
                        Transaction.farm_id == farm_id,
                        SaleReturn.return_date >= from_date,
                        SaleReturn.return_date <= to_date,
                        SaleReturn.return_type == "delivered_return",
                    )
                )
            ).all()
        )
        sales_credits = sum(
            (Decimal(item.credit_amount) for _, item in sale_returns),
            ZERO,
        )
        for _, return_item in sale_returns:
            transaction_item = transaction_item_by_id.get(
                return_item.transaction_item_id
            )
            if transaction_item is not None:
                row = performance_for(transaction_item.product_id)
                if row is not None:
                    row["sales_credits"] += Decimal(return_item.credit_amount)

        cash_refunds = list(
            (
                await self.session.execute(
                    select(TransactionRefund)
                    .join(Transaction, Transaction.id == TransactionRefund.transaction_id)
                    .where(
                        Transaction.farm_id == farm_id,
                        Transaction.transaction_type == TransactionType.SALE,
                        TransactionRefund.refund_date >= from_date,
                        TransactionRefund.refund_date <= to_date,
                    )
                )
            ).scalars().all()
        )
        supplier_refunds = list(
            (
                await self.session.execute(
                    select(PurchaseSupplierRefund)
                    .join(
                        Transaction,
                        Transaction.id == PurchaseSupplierRefund.transaction_id,
                    )
                    .where(
                        Transaction.farm_id == farm_id,
                        PurchaseSupplierRefund.refund_date >= from_date,
                        PurchaseSupplierRefund.refund_date <= to_date,
                    )
                )
            ).scalars().all()
        )
        supplier_returns = list(
            (
                await self.session.execute(
                    select(PurchaseReturnItem, PurchaseReturn)
                    .join(
                        PurchaseReturn,
                        PurchaseReturn.id == PurchaseReturnItem.purchase_return_id,
                    )
                    .join(Transaction, Transaction.id == PurchaseReturn.transaction_id)
                    .where(
                        Transaction.farm_id == farm_id,
                        PurchaseReturn.return_date >= from_date,
                        PurchaseReturn.return_date <= to_date,
                    )
                )
            ).all()
        )

        expenses = list(
            (
                await self.session.execute(
                    select(Expense)
                    .where(
                        Expense.farm_id == farm_id,
                        Expense.expense_date >= from_date,
                        Expense.expense_date <= to_date,
                        Expense.canceled_at.is_(None),
                    )
                )
            ).scalars().all()
        )
        expense_refunds = list(
            (
                await self.session.execute(
                    select(ExpensePayment)
                    .join(Expense, Expense.id == ExpensePayment.expense_id)
                    .where(
                        Expense.farm_id == farm_id,
                        Expense.canceled_at.is_(None),
                        Expense.purchase_transaction_id.is_(None),
                        ExpensePayment.kind == "refund",
                        ExpensePayment.payment_date >= from_date,
                        ExpensePayment.payment_date <= to_date,
                    )
                )
            ).scalars().all()
        )
        operating_expenses = operating_expense_total(
            expenses,
            expense_refunds=sum(
                (Decimal(row.amount) for row in expense_refunds),
                ZERO,
            ),
        )

        chicken_loss_rows = list(
            (
                await self.session.execute(
                    select(ChickenLoss).where(
                        ChickenLoss.farm_id == farm_id,
                        ChickenLoss.loss_date >= from_date,
                        ChickenLoss.loss_date <= to_date,
                    )
                )
            ).scalars().all()
        )
        egg_loss_rows = list(
            (
                await self.session.execute(
                    select(EggLoss).where(
                        EggLoss.farm_id == farm_id,
                        EggLoss.loss_date >= from_date,
                        EggLoss.loss_date <= to_date,
                    )
                )
            ).scalars().all()
        )
        sale_cogs = ZERO
        inventory_losses = ZERO
        unvalued_period_movement_count = 0
        recorded_sale_sources = {
            (movement.source_type, movement.source_item_id)
            for movement in movements
            if _enum_value(movement.movement_type) == "sale"
            and movement.quantity_delta < ZERO
            and _period_contains(movement.occurred_on, from_date, to_date)
        }
        for transaction in transactions:
            if (
                _enum_value(transaction.transaction_type) != "sale"
                or _enum_value(transaction.status) != "completed"
            ):
                continue
            for item in transaction.items:
                product = product_by_id.get(item.product_id)
                if product is None or _enum_value(product.product_type) == "chickens":
                    continue
                if not _requires_direct_sale_inventory_movement(
                    _enum_value(product.product_type),
                    transaction.fulfillment_required,
                ):
                    continue
                if _period_contains(transaction.transaction_date, from_date, to_date):
                    if ("transaction", item.id) not in recorded_sale_sources:
                        unvalued_period_movement_count += 1
                        missing_inventory_record_count += 1
                        row = performance_for(item.product_id)
                        if row is not None:
                            row["uncosted_quantity"] += (
                                Decimal(item.quantity) * Decimal(item.conversion_factor)
                            )
        for delivery_item, _ in deliveries:
            if (
                "sale_delivery",
                delivery_item.id,
            ) not in recorded_sale_sources:
                unvalued_period_movement_count += 1
                missing_inventory_record_count += 1
                transaction_item = transaction_item_by_id.get(
                    delivery_item.transaction_item_id
                )
                if transaction_item is not None:
                    row = performance_for(transaction_item.product_id)
                    if row is not None:
                        row["uncosted_quantity"] += Decimal(delivery_item.quantity)
        for movement in movements:
            if not _period_contains(_event_date(movement), from_date, to_date):
                continue
            cost = effective_costs.get(movement.id)
            movement_type = _enum_value(movement.movement_type)
            if movement_type == "sale" and movement.quantity_delta < ZERO:
                if cost is None:
                    unvalued_period_movement_count += 1
                    row = performance_for(movement.product_id)
                    if row is not None:
                        row["uncosted_quantity"] += abs(
                            Decimal(movement.quantity_delta)
                        )
                        row["uncosted_movement_quantity"] += abs(
                            Decimal(movement.quantity_delta)
                        )
                        row["uncosted_movement_types"].add("sale")
                else:
                    movement_cost = abs(Decimal(movement.quantity_delta)) * cost
                    sale_cogs += movement_cost
                    row = performance_for(movement.product_id)
                    if row is not None:
                        row["cost_of_goods_sold"] += movement_cost
            elif movement_type in {"consumption", "loss"} and movement.quantity_delta < ZERO:
                if cost is None:
                    unvalued_period_movement_count += 1
                    row = performance_for(movement.product_id)
                    if row is not None:
                        row["uncosted_movement_quantity"] += abs(
                            Decimal(movement.quantity_delta)
                        )
                        row["uncosted_movement_types"].add(movement_type)
                else:
                    movement_cost = abs(Decimal(movement.quantity_delta)) * cost
                    if movement_type == "loss":
                        inventory_losses += movement_cost
        recorded_loss_ids = {
            movement.source_id
            for movement in movements
            if movement.source_type in {"chicken_loss", "egg_loss"}
            and _period_contains(movement.occurred_on, from_date, to_date)
        }
        missing_loss_records = sum(
            1 for row in chicken_loss_rows + egg_loss_rows if row.id not in recorded_loss_ids
        )
        unvalued_period_movement_count += missing_loss_records
        missing_inventory_record_count += missing_loss_records

        # Consumption costs assigned to egg production become egg inventory cost;
        # the unallocated remainder is recognized as a period expense.
        unallocated_consumption_expense = max(
            ZERO,
            total_consumption_cost - allocated_egg_cost,
        )
        if unvalued_consumption_records:
            unvalued_period_movement_count += unvalued_consumption_records

        closing_stock: list[ProfitabilityStockResponse] = []
        egg_stock_reconciliation: list[EggStockReconciliationResponse] = []
        closing_valued_cost = ZERO
        closing_unvalued_quantity = ZERO
        untracked_egg_quantity = ZERO
        overrepresented_egg_quantity = ZERO
        egg_actual_stock = await self._egg_stock_as_of(
            farm_id,
            to_date,
            [
                product.id
                for product in products
                if _enum_value(product.product_type) == ProductType.EGGS.value
            ],
        )
        for product in products:
            balance = closing.get(
                product.id,
                {
                    "quantity": ZERO,
                    "valued_quantity": ZERO,
                    "valued_cost": ZERO,
                    "unvalued_quantity": ZERO,
                },
            )
            ledger_quantity = balance["quantity"]
            egg_quantity = (
                egg_actual_stock.get(product.id, ZERO)
                if _enum_value(product.product_type) == ProductType.EGGS.value
                else ledger_quantity
            )
            untracked_quantity = max(ZERO, egg_quantity - ledger_quantity)
            overrepresented_quantity = max(ZERO, ledger_quantity - egg_quantity)
            untracked_egg_quantity += untracked_quantity
            overrepresented_egg_quantity += overrepresented_quantity
            if ledger_quantity <= ZERO and untracked_quantity <= ZERO:
                continue
            base_unit = next(
                (
                    product_unit.unit
                    for product_unit in product.product_units
                    if product_unit.is_base_unit
                ),
                None,
            )
            if base_unit is None:
                raise ConflictError(
                    f"Base unit is missing for inventory product '{product.name}'. "
                    "Configure a base unit before generating profitability reports."
                )
            if (
                _enum_value(product.product_type) == ProductType.EGGS.value
                and untracked_quantity + overrepresented_quantity > ZERO
            ):
                egg_stock_reconciliation.append(
                    EggStockReconciliationResponse(
                        product_id=product.id,
                        product_name=product.name,
                        unit_name=base_unit.name,
                        unit_abbreviation=base_unit.abbreviation,
                        supported_quantity=egg_quantity,
                        ledger_quantity=ledger_quantity,
                        difference=egg_quantity - ledger_quantity,
                    )
                )
            valued_cost = balance["valued_cost"]
            unvalued_quantity = (
                balance["unvalued_quantity"] + untracked_quantity
            )
            closing_valued_cost += valued_cost
            closing_unvalued_quantity += unvalued_quantity
            closing_stock.append(
                ProfitabilityStockResponse(
                    product_id=product.id,
                    product_name=product.name,
                    product_type=_enum_value(product.product_type),
                    unit_name=base_unit.name,
                    unit_abbreviation=base_unit.abbreviation,
                    quantity=ledger_quantity + untracked_quantity,
                    valued_quantity=balance["valued_quantity"],
                    valued_cost=_money(valued_cost),
                    unvalued_quantity=unvalued_quantity,
                )
            )

        chicken_batch_quantity = ZERO
        if to_date >= date.today():
            chicken_batch_quantity = Decimal(
                (
                    await self.session.execute(
                        select(func.coalesce(func.sum(BatchBlock.quantity), 0))
                        .join(ChickenBatch, ChickenBatch.id == BatchBlock.batch_id)
                        .where(ChickenBatch.farm_id == farm_id)
                    )
                ).scalar_one()
            )
        chicken_ledger_quantity = sum(
            (
                balance["quantity"]
                for product_id, balance in closing.items()
                if product_id in product_by_id
                and _enum_value(product_by_id[product_id].product_type) == "chickens"
            ),
            ZERO,
        )
        untracked_chicken_quantity = max(
            ZERO,
            chicken_batch_quantity - chicken_ledger_quantity,
        )
        if untracked_chicken_quantity > ZERO and to_date >= date.today():
            closing_unvalued_quantity += untracked_chicken_quantity

        incompleteness_reasons: list[str] = []
        if closing_unvalued_quantity > ZERO:
            incompleteness_reasons.append(
                "One or more products still on hand have no recorded acquisition or production cost."
            )
        if untracked_egg_quantity > ZERO:
            incompleteness_reasons.append(
                "Egg production, sales, returns, or loss records show stock that is not represented in the inventory ledger."
            )
        if overrepresented_egg_quantity > ZERO:
            incompleteness_reasons.append(
                "The egg inventory ledger exceeds the quantity supported by production, sales, returns, and loss records."
            )
        if unvalued_period_movement_count:
            incompleteness_reasons.append(
                "At least one sale, consumption, or loss in this period could not be valued from recorded stock costs."
            )
        if any(value is None for value in collection_costs.values()):
            incompleteness_reasons.append(
                "Egg production in this period lacks recorded, allocatable consumption cost."
            )
        if untracked_chicken_quantity > ZERO and to_date >= date.today():
            incompleteness_reasons.append(
                "Current chicken batch stock is not fully represented in the valued inventory ledger."
            )
        complete = not incompleteness_reasons
        total_cogs = sale_cogs + unallocated_consumption_expense
        net = net_profit(
            net_revenue(gross_sales, sales_credits),
            total_cogs,
            operating_expenses,
            inventory_losses,
            complete=complete,
        )
        product_performance_rows = []
        estimated_product_ids = {
            movement.product_id
            for movement in movements
            if movement.source_type == "estimated_stock_valuation"
            and movement.occurred_on <= to_date
        }
        for row in product_performance.values():
            quantity_sold = row["quantity_sold"]
            uncosted_quantity = row["uncosted_quantity"]
            net_sales, average_selling_price, average_unit_cost, gross_profit = (
                _product_margin_values(
                    quantity_sold,
                    row["sales_value"],
                    row["sales_credits"],
                    row["cost_of_goods_sold"],
                    uncosted_quantity,
                )
            )
            product_performance_rows.append(
                ProfitabilityProductResponse(
                    product_id=row["product_id"],
                    product_name=row["product_name"],
                    product_type=row["product_type"],
                    unit_name=row["unit_name"],
                    unit_abbreviation=row["unit_abbreviation"],
                    quantity_sold=quantity_sold,
                    sales_value=_money(row["sales_value"]),
                    sales_credits=_money(row["sales_credits"]),
                    net_sales=net_sales,
                    cost_of_goods_sold=_money(row["cost_of_goods_sold"]),
                    average_selling_price=average_selling_price,
                    average_unit_cost=average_unit_cost,
                    gross_profit=gross_profit,
                    uncosted_quantity=uncosted_quantity,
                    uncosted_movement_quantity=row[
                        "uncosted_movement_quantity"
                    ],
                    uncosted_movement_types=sorted(
                        row["uncosted_movement_types"]
                    ),
                    estimated_cost_used=(
                        row["product_id"] in estimated_product_ids
                        and quantity_sold > ZERO
                    ),
                )
            )
        product_performance_rows.sort(key=lambda item: item.product_name.casefold())
        return ProfitabilityReportResponse(
            farm_id=farm_id,
            from_date=from_date,
            to_date=to_date,
            complete=complete,
            incompleteness_reasons=incompleteness_reasons,
            gross_sales=_money(gross_sales),
            sales_credits=_money(sales_credits),
            net_revenue=_money(net_revenue(gross_sales, sales_credits)),
            cost_of_goods_sold=_money(sale_cogs),
            product_consumption_cost=_money(total_consumption_cost),
            egg_production_cost_allocated=_money(allocated_egg_cost),
            egg_production_zero_cost_confirmed=egg_production_zero_cost_confirmed,
            egg_production_zero_cost_confirmation_available=(
                has_egg_production
                and not consumption_rows
                and not egg_production_zero_cost_confirmed
            ),
            unallocated_consumption_expense=_money(unallocated_consumption_expense),
            operating_expenses=_money(operating_expenses),
            inventory_losses=_money(inventory_losses),
            net_profit=_money(net) if net is not None else None,
            closing_stock_as_of=to_date,
            closing_stock=closing_stock,
            product_performance=product_performance_rows,
            egg_stock_reconciliation=egg_stock_reconciliation,
            reserved_egg_sales=reserved_egg_sales,
            unvalued_period_movement_count=unvalued_period_movement_count,
            missing_inventory_record_count=missing_inventory_record_count,
            closing_stock_valued_cost=_money(closing_valued_cost),
            closing_stock_unvalued_quantity=closing_unvalued_quantity,
            untracked_chicken_quantity=untracked_chicken_quantity,
            untracked_egg_quantity=untracked_egg_quantity,
            overrepresented_egg_quantity=overrepresented_egg_quantity,
            customer_cash_refunds_excluded=_money(
                sum((Decimal(row.amount) for row in cash_refunds), ZERO)
            ),
            supplier_cash_refunds_excluded=_money(
                sum((Decimal(row.amount) for row in supplier_refunds), ZERO)
            ),
            supplier_return_credits_excluded=_money(
                sum((Decimal(item.credit_amount) for item, _ in supplier_returns), ZERO)
            ),
        )
