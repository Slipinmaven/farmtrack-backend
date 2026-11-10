from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from uuid import UUID, uuid4

from sqlalchemy.exc import IntegrityError

from app.core.database_errors import integrity_constraint_name
from app.core.exceptions import ConflictError, ResourceNotFoundError
from app.core.unit_of_work import UnitOfWork
from app.models.farm import Farm
from app.repositories.batch_block_repository import BatchBlockRepository
from app.repositories.block_repository import BlockRepository
from app.repositories.chicken_batch_name_counter_repository import (
    ChickenBatchNameCounterRepository,
)
from app.repositories.chicken_batch_repository import ChickenBatchRepository
from app.repositories.inventory_movement_repository import InventoryMovementRepository
from app.repositories.purchase_replacement_repository import PurchaseReplacementRepository
from app.repositories.purchase_return_repository import PurchaseReturnRepository
from app.repositories.purchase_supplier_refund_repository import (
    PurchaseSupplierRefundRepository,
)
from app.repositories.product_repository import ProductRepository
from app.repositories.product_unit_repository import ProductUnitRepository
from app.repositories.farm_repository import FarmRepository
from app.repositories.sale_return_repository import SaleReturnRepository
from app.repositories.transaction_payment_repository import TransactionPaymentRepository
from app.repositories.transaction_refund_repository import TransactionRefundRepository
from app.repositories.transaction_repository import TransactionRepository
from app.repositories.transaction_settlement_repository import (
    TransactionSettlementRepository,
)
from app.schemas.enums import (
    ActivityEntityType,
    ActivityType,
    ChickenBatchStatus,
    InventoryMovementType,
    ProductType,
    TransactionStatus,
    TransactionType,
)
from app.schemas.transaction_settlement import (
    TransactionSettlementBalanceResponse,
    TransactionSettlementCreateRequest,
    TransactionSettlementResponse,
)
from app.services.activity_service import ActivityService
from app.services.chicken_age import calculate_hatch_date
from app.services.inventory_service import InventoryService
from app.services.transaction_balance import calculate_transaction_balance
from app.services.transaction_pricing import calculate_sale_return_credit_total

CENT = Decimal("0.01")
THOUSANDTH = Decimal("0.001")


class TransactionSettlementService:
    def __init__(
        self,
        transaction_repository: TransactionRepository,
        settlement_repository: TransactionSettlementRepository,
        payment_repository: TransactionPaymentRepository,
        refund_repository: TransactionRefundRepository,
        supplier_refund_repository: PurchaseSupplierRefundRepository,
        sale_return_repository: SaleReturnRepository,
        purchase_return_repository: PurchaseReturnRepository,
        replacement_repository: PurchaseReplacementRepository,
        product_repository: ProductRepository,
        product_unit_repository: ProductUnitRepository,
        movement_repository: InventoryMovementRepository,
        chicken_batch_repository: ChickenBatchRepository,
        chicken_batch_name_counter_repository: ChickenBatchNameCounterRepository,
        block_repository: BlockRepository,
        batch_block_repository: BatchBlockRepository,
        inventory_service: InventoryService,
        unit_of_work: UnitOfWork,
        activity_service: ActivityService,
        farm_repository: FarmRepository | None = None,
    ) -> None:
        self.transaction_repository = transaction_repository
        self.settlement_repository = settlement_repository
        self.payment_repository = payment_repository
        self.refund_repository = refund_repository
        self.supplier_refund_repository = supplier_refund_repository
        self.sale_return_repository = sale_return_repository
        self.purchase_return_repository = purchase_return_repository
        self.replacement_repository = replacement_repository
        self.product_repository = product_repository
        self.product_unit_repository = product_unit_repository
        self.movement_repository = movement_repository
        self.chicken_batch_repository = chicken_batch_repository
        self.chicken_batch_name_counter_repository = chicken_batch_name_counter_repository
        self.block_repository = block_repository
        self.batch_block_repository = batch_block_repository
        self.inventory_service = inventory_service
        self.unit_of_work = unit_of_work
        self.activity_service = activity_service
        self.farm_repository = farm_repository

    async def create(
        self,
        farm: Farm,
        transaction_id: UUID,
        request: TransactionSettlementCreateRequest,
    ) -> TransactionSettlementBalanceResponse:
        async with self.unit_of_work:
            if self.farm_repository is not None:
                locked_farm = await self.farm_repository.get_by_id_for_update(farm.id)
                if locked_farm is None:
                    raise ResourceNotFoundError("Farm not found.")
            transaction = await self.transaction_repository.get_by_id_for_update(
                farm.id,
                transaction_id,
            )
            if transaction is None:
                raise ResourceNotFoundError("Transaction not found for this farm.")
            if transaction.status == TransactionStatus.CANCELLED:
                raise ConflictError("A cancelled transaction cannot be settled.")

            lines, total_value = await self._resolve_lines(farm, request)
            balance = await self._get_balance(transaction)
            direction_sign = self._direction_sign(
                transaction.transaction_type,
                request.direction,
            )
            if direction_sign > 0:
                available = balance.balance_due
            else:
                available = balance.credit_balance
            if total_value > available:
                raise ConflictError(
                    f"This settlement is worth {total_value}, but only "
                    f"{available} is available to settle in this direction."
                )

            chicken_placements = await self._prepare_chicken_placements(
                farm,
                request,
                lines,
            )
            settlement = await self.settlement_repository.create(
                {
                    "transaction_id": transaction.id,
                    "direction": request.direction,
                    "settlement_date": request.settlement_date,
                    "total_value": total_value,
                    "lines": lines,
                    "reason": request.reason,
                    "notes": request.notes,
                }
            )
            for line in lines:
                if line["kind"] != "goods":
                    continue
                placement_plan = chicken_placements.get(str(line["id"]))
                if placement_plan is not None:
                    await self._apply_chicken_placement(placement_plan)
                quantity_delta = Decimal(str(line["quantity_in_base_unit"]))
                if request.direction == "farm_to_contact":
                    quantity_delta = -quantity_delta
                await self.inventory_service.append_movement(
                    farm_id=farm.id,
                    user_id=farm.owner_id,
                    product_id=UUID(str(line["product_id"])),
                    quantity_delta=quantity_delta,
                    movement_type=(
                        InventoryMovementType.SETTLEMENT_ISSUED
                        if quantity_delta < 0
                        else InventoryMovementType.SETTLEMENT_RECEIVED
                    ),
                    occurred_on=request.settlement_date,
                    notes=f"Settlement for transaction {transaction.reference_number or transaction.id}",
                    source_type="transaction_settlement",
                    source_id=settlement.id,
                    source_item_id=UUID(str(line["id"])),
                )

            await self.activity_service.record(
                farm_id=farm.id,
                user_id=farm.owner_id,
                activity_type=ActivityType.TRANSACTION_SETTLEMENT_RECORDED,
                entity_type=ActivityEntityType.TRANSACTION_SETTLEMENT,
                entity_id=settlement.id,
                details={
                    "transaction_id": str(transaction.id),
                    "transaction_type": transaction.transaction_type.value,
                    "transaction_reference_number": transaction.reference_number,
                    "direction": request.direction,
                    "settlement_date": request.settlement_date.isoformat(),
                    "total_value": str(total_value),
                    "reason": request.reason,
                    "notes": request.notes,
                    "items": lines,
                },
            )
            updated_balance = await self._get_balance(transaction)
            await self.unit_of_work.commit()
            response = TransactionSettlementResponse.model_validate(settlement)
            return TransactionSettlementBalanceResponse(
                settlement=response,
                amount_paid=updated_balance.amount_paid,
                balance_due=updated_balance.balance_due,
                credit_balance=updated_balance.credit_balance,
            )

    async def list_for_transaction(
        self,
        farm: Farm,
        transaction_id: UUID,
    ) -> list[TransactionSettlementResponse]:
        async with self.unit_of_work:
            transaction = await self.transaction_repository.get_by_id(
                farm.id,
                transaction_id,
            )
            if transaction is None:
                raise ResourceNotFoundError("Transaction not found for this farm.")
            settlements = await self.settlement_repository.list_by_transaction(
                transaction_id
            )
            return [
                TransactionSettlementResponse.model_validate(item)
                for item in settlements
            ]

    async def _resolve_lines(
        self,
        farm: Farm,
        request: TransactionSettlementCreateRequest,
    ) -> tuple[list[dict[str, object]], Decimal]:
        result: list[dict[str, object]] = []
        total_value = Decimal("0.00")
        for item in request.lines:
            line_id = uuid4()
            if item.kind == "cash":
                line_value = item.amount.quantize(CENT, rounding=ROUND_HALF_UP)
                line = {
                    "id": str(line_id),
                    "kind": "cash",
                    "amount": str(line_value),
                    "payment_method": item.payment_method.value,
                    "reference_number": item.reference_number,
                    "value": str(line_value),
                }
            elif item.kind == "service":
                line_value = item.value.quantize(CENT, rounding=ROUND_HALF_UP)
                line = {
                    "id": str(line_id),
                    "kind": "service",
                    "description": item.description,
                    "value": str(line_value),
                }
            else:
                product = await self.product_repository.get_by_id(
                    farm.id,
                    item.product_id,
                )
                if product is None:
                    raise ResourceNotFoundError(
                        "A settlement product was not found for this farm."
                    )
                product_unit = (
                    await self.product_unit_repository.get_by_product_and_unit(
                        product.id,
                        item.unit_id,
                    )
                )
                if product_unit is None:
                    raise ConflictError(
                        f"The selected unit is not configured for {product.name}."
                    )
                base_unit = (
                    await self.product_unit_repository.get_base_unit_for_product(
                        product.id
                    )
                )
                if base_unit is None:
                    raise ConflictError(
                        f"The base unit is not configured for {product.name}."
                    )
                base_quantity = (
                    item.quantity * product_unit.conversion_factor
                ).quantize(THOUSANDTH, rounding=ROUND_HALF_UP)
                if base_quantity <= 0:
                    raise ConflictError(
                        "The goods quantity is too small for the product's base unit."
                    )
                line_value = (
                    item.quantity * item.agreed_unit_value
                ).quantize(CENT, rounding=ROUND_HALF_UP)
                gross_value = line_value
                discount_amount = Decimal("0.00")
                if item.discount_type == "fixed":
                    discount_amount = item.discount_value.quantize(
                        CENT,
                        rounding=ROUND_HALF_UP,
                    )
                    if discount_amount > gross_value:
                        raise ConflictError(
                            "A fixed goods discount cannot exceed the line value."
                        )
                elif item.discount_type == "percentage":
                    discount_amount = (
                        gross_value * item.discount_value / Decimal("100")
                    ).quantize(CENT, rounding=ROUND_HALF_UP)
                line_value = (gross_value - discount_amount).quantize(
                    CENT,
                    rounding=ROUND_HALF_UP,
                )
                if request.direction == "farm_to_contact":
                    current = await self.movement_repository.get_balance(
                        farm.id,
                        product.id,
                    )
                    if current < base_quantity:
                        raise ConflictError(
                            f"Not enough {product.name} in stock. "
                            f"{current} {base_unit.name} is available."
                        )
                line = {
                    "id": str(line_id),
                    "kind": "goods",
                    "product_id": str(product.id),
                    "product_name": product.name,
                    "unit_id": str(product_unit.unit_id),
                    "unit_name": product_unit.unit.name,
                    "unit_abbreviation": product_unit.unit.abbreviation,
                    "quantity": str(item.quantity),
                    "conversion_factor": str(product_unit.conversion_factor),
                    "quantity_in_base_unit": str(base_quantity),
                    "base_unit_id": str(base_unit.id),
                    "base_unit_name": base_unit.name,
                    "base_unit_abbreviation": base_unit.abbreviation,
                    "agreed_unit_value": str(item.agreed_unit_value),
                    "gross_value": str(gross_value),
                    "discount_type": item.discount_type,
                    "discount_value": str(item.discount_value),
                    "discount_amount": str(discount_amount),
                    "discount_reason": item.discount_reason,
                    "value": str(line_value),
                }
                if item.chicken_placement is not None:
                    line["chicken_placement"] = item.chicken_placement.model_dump(
                        mode="json"
                    )
            if line_value <= 0:
                raise ConflictError(
                    "Each settlement line must have a value of at least 0.01."
                )
            total_value += line_value
            result.append(line)
        total_value = total_value.quantize(CENT, rounding=ROUND_HALF_UP)
        if total_value <= 0:
            raise ConflictError("A settlement must have a positive total value.")
        return result, total_value

    async def _prepare_chicken_placements(
        self,
        farm: Farm,
        request: TransactionSettlementCreateRequest,
        lines: list[dict[str, object]],
    ) -> dict[str, dict[str, object]]:
        block_rows = {}
        batch_rows = {}
        planned_block_receipts: dict[UUID, int] = {}
        planned_stock_changes: dict[tuple[UUID, UUID], int] = {}
        plans: dict[str, dict[str, object]] = {}
        new_batch_requests = []

        for item, line in zip(request.lines, lines, strict=True):
            if item.kind != "goods":
                continue
            product = await self.product_repository.get_by_id(farm.id, item.product_id)
            if product is None:
                raise ResourceNotFoundError("A settlement product was not found for this farm.")
            placement = item.chicken_placement
            if product.product_type != ProductType.CHICKENS:
                if placement is not None:
                    raise ConflictError(
                        "Chicken placement can only be recorded for chicken products."
                    )
                continue
            if placement is None:
                raise ConflictError(
                    "Chicken settlement goods require batch and housing placement details."
                )

            receives_chickens = request.direction == "contact_to_farm"
            if receives_chickens:
                if placement.mode not in {"receive_existing", "receive_new"}:
                    raise ConflictError(
                        "Chickens received by the farm must be recorded as a receipt."
                    )
            elif placement.mode != "issue":
                raise ConflictError(
                    "Chickens given by the farm must be allocated from current flock stock."
                )

            base_quantity = Decimal(str(line["quantity_in_base_unit"]))
            if base_quantity != base_quantity.to_integral_value():
                raise ConflictError("Chicken settlement quantities must be whole chickens.")
            quantity = int(base_quantity)
            if sum(allocation.quantity for allocation in placement.allocations) != quantity:
                raise ConflictError(
                    "Chicken batch and block allocations must equal the converted quantity."
                )

            resolved_allocations = []
            batch = None
            if placement.mode == "receive_existing":
                batch = await self.chicken_batch_repository.get_by_id(
                    farm.id,
                    placement.batch_id,
                )
                if batch is None:
                    raise ResourceNotFoundError(
                        "Selected chicken batch was not found for this farm."
                    )
                if batch.status != ChickenBatchStatus.ACTIVE:
                    raise ConflictError("Received chickens must enter an active batch.")
                if batch.product_id != product.id:
                    raise ConflictError(
                        f"Batch '{batch.name}' is not linked to the selected chicken product."
                    )
                batch_rows[batch.id] = batch
                for allocation in placement.allocations:
                    resolved_allocations.append(
                        {
                            "batch_id": batch.id,
                            "block_id": allocation.block_id,
                            "quantity": allocation.quantity,
                        }
                    )
            elif placement.mode == "receive_new":
                hatch_date = calculate_hatch_date(
                    request.settlement_date,
                    placement.new_batch.age,
                    placement.new_batch.age_unit,
                )
                new_batch_requests.append((line, placement.new_batch, hatch_date))
                for allocation in placement.allocations:
                    resolved_allocations.append(
                        {
                            "batch_id": None,
                            "block_id": allocation.block_id,
                            "quantity": allocation.quantity,
                        }
                    )
            else:
                for allocation in placement.allocations:
                    batch = await self.chicken_batch_repository.get_by_id(
                        farm.id,
                        allocation.batch_id,
                    )
                    if batch is None:
                        raise ResourceNotFoundError(
                            "Selected chicken batch was not found for this farm."
                        )
                    if batch.status != ChickenBatchStatus.ACTIVE:
                        raise ConflictError(
                            "Chickens can only be issued from an active batch."
                        )
                    if batch.product_id != product.id:
                        raise ConflictError(
                            f"Batch '{batch.name}' is not linked to the selected chicken product."
                        )
                    batch_rows[batch.id] = batch
                    resolved_allocations.append(
                        {
                            "batch_id": batch.id,
                            "block_id": allocation.block_id,
                            "quantity": allocation.quantity,
                        }
                    )

            for allocation in resolved_allocations:
                block_id = allocation["block_id"]
                block = block_rows.get(block_id)
                if block is None:
                    block = await self.block_repository.get_by_id_for_update(
                        farm.id,
                        block_id,
                    )
                    if block is None:
                        raise ResourceNotFoundError(
                            "A selected chicken block was not found for this farm."
                        )
                    block_rows[block_id] = block

                batch_id = allocation["batch_id"]
                stock_key = (
                    batch_id if batch_id is not None else UUID(int=0),
                    block_id,
                )
                if receives_chickens:
                    if not block.is_active:
                        raise ConflictError("Received chickens must go into an active block.")
                    planned_block_receipts[block_id] = (
                        planned_block_receipts.get(block_id, 0)
                        + allocation["quantity"]
                    )
                else:
                    planned_stock_changes[stock_key] = (
                        planned_stock_changes.get(stock_key, 0)
                        + allocation["quantity"]
                    )

            plans[str(line["id"])] = {
                "receives_chickens": receives_chickens,
                "allocations": resolved_allocations,
                "batch": batch,
                "new_batch": placement.new_batch,
                "new_batch_hatch_date": (
                    hatch_date if placement.mode == "receive_new" else None
                ),
                "line": line,
            }

        for block_id, receipt_quantity in planned_block_receipts.items():
            block = block_rows[block_id]
            current_quantity = await self.batch_block_repository.get_total_quantity_by_block(
                block_id
            )
            if (
                current_quantity + receipt_quantity
                > block.capacity + block.over_capacity_limit
            ):
                raise ConflictError(
                    f"Placing these chickens would exceed block '{block.name}' capacity."
                )

        stock_rows = {}
        for (batch_id, block_id), requested_quantity in planned_stock_changes.items():
            actual_batch_id = batch_id
            stock = await self.batch_block_repository.get_by_batch_and_block(
                actual_batch_id,
                block_id,
            )
            if stock is None or stock.quantity < requested_quantity:
                batch_name = batch_rows[actual_batch_id].name
                block_name = block_rows[block_id].name
                available_stock = stock.quantity if stock is not None else 0
                raise ConflictError(
                    f"Only {available_stock} chickens from {batch_name} are in "
                    f"{block_name}; {requested_quantity} were requested."
                )
            stock_rows[(actual_batch_id, block_id)] = stock

        for line, batch_request, hatch_date in new_batch_requests:
            if batch_request.name:
                batch_name = batch_request.name
            else:
                number = await self.chicken_batch_name_counter_repository.allocate_next_number(
                    farm.id,
                    request.settlement_date,
                )
                batch_name = (
                    f"{request.settlement_date.year} "
                    f"{request.settlement_date.strftime('%B')} "
                    f"{request.settlement_date.day} Batch {number}"
                )
            try:
                batch = await self.chicken_batch_repository.create(
                    farm.id,
                    {
                        "name": batch_name,
                        "product_id": UUID(str(line["product_id"])),
                        "chicken_type": batch_request.chicken_type,
                        "hatch_date": hatch_date,
                        "status": ChickenBatchStatus.ACTIVE,
                    },
                )
            except IntegrityError as exc:
                if (
                    integrity_constraint_name(exc)
                    == "uq_chicken_batches_farm_id_name"
                ):
                    raise ConflictError(
                        "A chicken batch with this name already exists for this farm."
                    ) from exc
                raise
            plan = plans[str(line["id"])]
            plan["batch"] = batch
            for allocation in plan["allocations"]:
                allocation["batch_id"] = batch.id

        for plan in plans.values():
            if not plan["receives_chickens"]:
                continue
            for allocation in plan["allocations"]:
                key = (allocation["batch_id"], allocation["block_id"])
                if key not in stock_rows:
                    stock_rows[key] = (
                        await self.batch_block_repository.get_by_batch_and_block(
                            allocation["batch_id"],
                            allocation["block_id"],
                        )
                    )

        for line_id, plan in plans.items():
            line = plan["line"]
            allocations_snapshot = []
            for allocation in plan["allocations"]:
                batch = batch_rows.get(allocation["batch_id"])
                if batch is None:
                    batch = plan["batch"]
                allocations_snapshot.append(
                    {
                        "batch_id": str(allocation["batch_id"]),
                        "batch_name": batch.name,
                        "chicken_type": batch.chicken_type.value,
                        "block_id": str(allocation["block_id"]),
                        "block_name": block_rows[allocation["block_id"]].name,
                        "quantity": allocation["quantity"],
                    }
                )
            line["chicken_placement"] = {
                "mode": "receive" if plan["receives_chickens"] else "issue",
                "allocations": allocations_snapshot,
            }
            if plan["new_batch"] is not None:
                line["chicken_placement"]["new_batch"] = {
                    "chicken_type": plan["new_batch"].chicken_type.value,
                    "hatch_date": plan["new_batch_hatch_date"].isoformat(),
                }
            plan["stock_rows"] = stock_rows
            plans[line_id] = plan

        return plans

    async def _apply_chicken_placement(self, plan: dict[str, object]) -> None:
        receives_chickens = bool(plan["receives_chickens"])
        stock_rows = plan["stock_rows"]
        for allocation in plan["allocations"]:
            key = (allocation["batch_id"], allocation["block_id"])
            stock = stock_rows.get(key)
            if receives_chickens:
                if stock is None:
                    stock_rows[key] = await self.batch_block_repository.create(
                        {
                            "batch_id": allocation["batch_id"],
                            "block_id": allocation["block_id"],
                            "quantity": allocation["quantity"],
                        }
                    )
                else:
                    stock.quantity += allocation["quantity"]
                    await self.batch_block_repository.update(stock)
            else:
                stock.quantity -= allocation["quantity"]
                await self.batch_block_repository.update(stock)

    async def _get_balance(
        self,
        transaction,
        *,
        extra_settlement: tuple[str, Decimal] | None = None,
    ):
        payments = await self.payment_repository.list_by_transaction(transaction.id)
        amount_received = sum(
            (payment.amount for payment in payments),
            Decimal("0.00"),
        )
        transaction_total = sum(
            (item.total_amount for item in transaction.items),
            Decimal("0.00"),
        )
        settlement_adjustment = Decimal("0.00")
        for settlement in await self.settlement_repository.list_by_transaction(
            transaction.id
        ):
            sign = self._direction_sign(
                transaction.transaction_type,
                settlement.direction,
            )
            settlement_adjustment += settlement.total_value * sign
        if extra_settlement is not None:
            settlement_adjustment += extra_settlement[1] * self._direction_sign(
                transaction.transaction_type,
                extra_settlement[0],
            )
        if transaction.transaction_type == TransactionType.SALE:
            amount_refunded = await self.refund_repository.get_total_by_transaction(
                transaction.id
            )
            returned_quantities = (
                await self.sale_return_repository.get_credited_quantities_by_item(
                    transaction.id
                )
            )
            credit_notes = calculate_sale_return_credit_total(
                transaction.items,
                returned_quantities,
            )
        else:
            amount_refunded = (
                await self.supplier_refund_repository.get_total_by_transaction(
                    transaction.id
                )
            )
            credit_notes = (
                await self.purchase_return_repository.get_total_credit_by_transaction(
                    transaction.id
                )
            )
            replacement_credit = (
                await self.replacement_repository.get_total_credit_applied_by_transaction(
                    transaction.id
                )
            )
            settlement_adjustment -= replacement_credit
        return calculate_transaction_balance(
            transaction_total,
            amount_received,
            amount_refunded,
            credit_notes,
            settlement_adjustment=settlement_adjustment,
        )

    @staticmethod
    def _direction_sign(transaction_type: TransactionType, direction: str) -> Decimal:
        if (
            transaction_type == TransactionType.SALE
            and direction == "contact_to_farm"
        ) or (
            transaction_type == TransactionType.PURCHASE
            and direction == "farm_to_contact"
        ):
            return Decimal("1")
        return Decimal("-1")
