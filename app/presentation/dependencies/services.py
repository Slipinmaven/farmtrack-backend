from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_database_session
from app.core.unit_of_work import UnitOfWork
from app.repositories.block_repository import BlockRepository
from app.repositories.contact_repository import ContactRepository
from app.repositories.contact_role_repository import ContactRoleRepository
from app.repositories.contact_role_product_repository import ContactRoleProductRepository
from app.repositories.farm_repository import FarmRepository
from app.repositories.farm_membership_repository import FarmMembershipRepository
from app.repositories.refresh_token_repository import RefreshTokenRepository
from app.repositories.user_session_repository import UserSessionRepository
from app.repositories.user_repository import UserRepository
from app.repositories.farm_settings_repository import FarmSettingsRepository
from app.repositories.transaction_reference_counter_repository import (
    TransactionReferenceCounterRepository,
)
from app.repositories.unit_repository import UnitRepository
from app.repositories.product_repository import ProductRepository
from app.repositories.product_unit_repository import ProductUnitRepository
from app.repositories.transaction_repository import TransactionRepository
from app.repositories.transaction_item_repository import TransactionItemRepository
from app.repositories.transaction_payment_repository import TransactionPaymentRepository
from app.repositories.purchase_receipt_repository import PurchaseReceiptRepository
from app.repositories.purchase_receipt_item_repository import PurchaseReceiptItemRepository
from app.repositories.purchase_receipt_item_block_allocation_repository import (
    PurchaseReceiptItemBlockAllocationRepository,
)
from app.repositories.purchase_return_repository import PurchaseReturnRepository
from app.repositories.purchase_supplier_refund_repository import (
    PurchaseSupplierRefundRepository,
)
from app.repositories.purchase_replacement_repository import PurchaseReplacementRepository
from app.repositories.sale_delivery_repository import SaleDeliveryRepository
from app.repositories.chicken_movement_repository import ChickenMovementRepository
from app.repositories.chicken_loss_repository import ChickenLossRepository
from app.repositories.egg_collection_repository import EggCollectionRepository
from app.repositories.egg_loss_repository import EggLossRepository
from app.repositories.sale_return_repository import SaleReturnRepository
from app.repositories.transaction_refund_repository import TransactionRefundRepository
from app.repositories.transaction_settlement_repository import (
    TransactionSettlementRepository,
)
from app.repositories.chicken_batch_repository import ChickenBatchRepository
from app.repositories.chicken_batch_name_counter_repository import (
    ChickenBatchNameCounterRepository,
)
from app.repositories.chicken_transaction_item_repository import (
    ChickenTransactionItemRepository,
)
from app.repositories.expense_repository import ExpenseRepository
from app.repositories.expense_payment_repository import ExpensePaymentRepository
from app.repositories.expense_category_repository import ExpenseCategoryRepository
from app.repositories.product_consumption_repository import ProductConsumptionRepository
from app.repositories.notification_repository import NotificationRepository
from app.repositories.assistant_conversation_repository import (
    AssistantConversationRepository,
)
from app.repositories.notification_outbox_repository import NotificationOutboxRepository
from app.repositories.reminder_repository import ReminderRepository
from app.repositories.batch_block_repository import BatchBlockRepository
from app.repositories.inventory_movement_repository import (
    InventoryMovementRepository,
)
from app.repositories.app_security_settings_repository import (
    AppSecuritySettingsRepository,
)
from app.repositories.activity_repository import ActivityRepository
from app.services.auth_service import AuthService
from app.services.activity_service import ActivityService
from app.services.email_gateway_service import FarmTrackEmailService
from app.services.block_service import BlockService
from app.services.contact_service import ContactService
from app.services.contact_history_service import ContactHistoryService
from app.services.account_ledger_service import AccountLedgerService
from app.services.farm_service import FarmService
from app.services.farm_membership_service import FarmMembershipService
from app.services.security_settings_service import SecuritySettingsService
from app.services.unit_service import UnitService
from app.services.product_service import ProductService
from app.services.inventory_purchase_service import InventoryPurchaseService
from app.services.chicken_purchase_service import ChickenPurchaseService
from app.services.chicken_purchase_details_service import (
    ChickenPurchaseDetailsService,
)
from app.services.chicken_purchase_options_service import ChickenPurchaseOptionsService
from app.services.chicken_sale_service import ChickenSaleService
from app.services.chicken_sale_details_service import ChickenSaleDetailsService
from app.services.chicken_sale_options_service import ChickenSaleOptionsService
from app.services.sale_delivery_service import SaleDeliveryService
from app.services.sale_return_service import SaleReturnService
from app.services.transaction_refund_service import TransactionRefundService
from app.services.transaction_service import TransactionService
from app.services.inventory_service import InventoryService
from app.services.inventory_opening_setup_service import InventoryOpeningSetupService
from app.repositories.inventory_opening_setup_repository import (
    InventoryOpeningSetupRepository,
)
from app.services.transaction_settlement_service import TransactionSettlementService
from app.services.purchase_receipt_service import PurchaseReceiptService
from app.services.purchase_return_service import PurchaseReturnService
from app.services.purchase_supplier_refund_service import PurchaseSupplierRefundService
from app.services.purchase_replacement_service import PurchaseReplacementService
from app.services.chicken_movement_service import ChickenMovementService
from app.services.chicken_loss_service import ChickenLossService
from app.services.egg_collection_service import EggCollectionService
from app.services.egg_collection_options_service import EggCollectionOptionsService
from app.services.egg_loss_service import EggLossService
from app.services.egg_sale_service import EggSaleService
from app.services.expense_service import ExpenseService
from app.services.product_consumption_service import ProductConsumptionService
from app.services.notification_service import NotificationService
from app.services.reminder_service import ReminderService
from app.services.sales_report_service import SalesReportService
from app.services.receipt_history_service import ReceiptHistoryService
from app.services.profitability_report_service import ProfitabilityReportService
from app.services.ai_assistant_service import FarmAssistantService
from app.services.ai_provider_manager import (
    AIProviderManager,
    get_ai_provider_manager,
)
from app.services.data_deletion_service import DataDeletionService


def get_unit_of_work(
    session: AsyncSession = Depends(get_database_session),
) -> UnitOfWork:
    return UnitOfWork(session=session)


def get_auth_service(unit_of_work: UnitOfWork = Depends(get_unit_of_work)) -> AuthService:
    session = unit_of_work.session
    return AuthService(
        user_repository=UserRepository(session=session),
        refresh_token_repository=RefreshTokenRepository(session=session),
        user_session_repository=UserSessionRepository(session=session),
        unit_of_work=unit_of_work,
    )


def get_farm_repository(
    unit_of_work: UnitOfWork = Depends(get_unit_of_work),
) -> FarmRepository:
    return FarmRepository(session=unit_of_work.session)


def get_email_gateway_service(request: Request) -> FarmTrackEmailService:
    return request.app.state.email_gateway_service


def get_data_deletion_service(
    unit_of_work: UnitOfWork = Depends(get_unit_of_work),
    email_service: FarmTrackEmailService = Depends(get_email_gateway_service),
) -> DataDeletionService:
    session = unit_of_work.session
    return DataDeletionService(
        user_repository=UserRepository(session=session),
        farm_repository=FarmRepository(session=session),
        user_session_repository=UserSessionRepository(session=session),
        refresh_token_repository=RefreshTokenRepository(session=session),
        unit_of_work=unit_of_work,
        email_service=email_service,
    )

def get_farm_membership_service(
    unit_of_work: UnitOfWork = Depends(get_unit_of_work),
    email_service: FarmTrackEmailService = Depends(get_email_gateway_service),
) -> FarmMembershipService:
    session = unit_of_work.session
    return FarmMembershipService(
        membership_repository=FarmMembershipRepository(session),
        user_repository=UserRepository(session),
        unit_of_work=unit_of_work,
        notification_outbox_repository=NotificationOutboxRepository(session),
        email_service=email_service,
    )


def get_activity_service(
    unit_of_work: UnitOfWork = Depends(get_unit_of_work),
) -> ActivityService:
    return ActivityService(
        repository=ActivityRepository(session=unit_of_work.session),
        unit_of_work=unit_of_work,
        user_session_repository=UserSessionRepository(session=unit_of_work.session),
        egg_collection_repository=EggCollectionRepository(
            session=unit_of_work.session
        ),
    )


def get_block_service(
    unit_of_work: UnitOfWork = Depends(get_unit_of_work),
    activity_service: ActivityService = Depends(get_activity_service),
) -> BlockService:
    session = unit_of_work.session
    return BlockService(
        block_repository=BlockRepository(session=session),
        activity_service=activity_service,
        unit_of_work=unit_of_work,
    )


def get_contact_service(
    unit_of_work: UnitOfWork = Depends(get_unit_of_work),
    activity_service: ActivityService = Depends(get_activity_service),
) -> ContactService:
    session = unit_of_work.session
    return ContactService(
        contact_repository=ContactRepository(session=session),
        contact_role_repository=ContactRoleRepository(session=session),
        contact_role_product_repository=ContactRoleProductRepository(session=session),
        activity_service=activity_service,
        unit_of_work=unit_of_work,
    )


def get_contact_history_service(
    unit_of_work: UnitOfWork = Depends(get_unit_of_work),
) -> ContactHistoryService:
    session = unit_of_work.session
    return ContactHistoryService(
        contact_repository=ContactRepository(session=session),
        transaction_repository=TransactionRepository(session=session),
        transaction_refund_repository=TransactionRefundRepository(session=session),
        sale_return_repository=SaleReturnRepository(session=session),
        supplier_refund_repository=PurchaseSupplierRefundRepository(
            session=session
        ),
        purchase_return_repository=PurchaseReturnRepository(session=session),
        purchase_replacement_repository=PurchaseReplacementRepository(
            session=session
        ),
        unit_of_work=unit_of_work,
    )


def get_account_ledger_service(
    unit_of_work: UnitOfWork = Depends(get_unit_of_work),
) -> AccountLedgerService:
    return AccountLedgerService(
        transaction_repository=TransactionRepository(session=unit_of_work.session),
        unit_of_work=unit_of_work,
    )


def get_farm_service(
    unit_of_work: UnitOfWork = Depends(get_unit_of_work),
    farm_repository: FarmRepository = Depends(get_farm_repository),
    activity_service: ActivityService = Depends(get_activity_service),
) -> "FarmService":
    session = unit_of_work.session
    from app.services.farm_service import FarmService
    return FarmService(
        farm_repository=farm_repository,
        farm_settings_repository=FarmSettingsRepository(session=session),
        activity_service=activity_service,
        unit_of_work=unit_of_work,
        product_repository=ProductRepository(session=session),
        block_repository=BlockRepository(session=session),
)


def get_security_settings_service(
    unit_of_work: UnitOfWork = Depends(get_unit_of_work),
) -> SecuritySettingsService:
    repository = AppSecuritySettingsRepository(unit_of_work.session)
    return SecuritySettingsService(
        repository=repository,
        unit_of_work=unit_of_work,
    )


def get_unit_service(
    unit_of_work: UnitOfWork = Depends(get_unit_of_work),
) -> UnitService:
    return UnitService(
        repository=UnitRepository(session=unit_of_work.session),
        unit_of_work=unit_of_work,
    )


def get_product_service(
    unit_of_work: UnitOfWork = Depends(get_unit_of_work),
) -> ProductService:
    return ProductService(
        repository=ProductRepository(session=unit_of_work.session),
        unit_of_work=unit_of_work,
    )


def get_inventory_service(
    unit_of_work: UnitOfWork = Depends(get_unit_of_work),
    activity_service: ActivityService = Depends(get_activity_service),
) -> InventoryService:
    return InventoryService(
        movement_repository=InventoryMovementRepository(
            session=unit_of_work.session
        ),
        product_repository=ProductRepository(session=unit_of_work.session),
        product_unit_repository=ProductUnitRepository(
            session=unit_of_work.session
        ),
        unit_of_work=unit_of_work,
        activity_service=activity_service,
    )


def get_transaction_settlement_service(
    unit_of_work: UnitOfWork = Depends(get_unit_of_work),
    activity_service: ActivityService = Depends(get_activity_service),
    inventory_service: InventoryService = Depends(get_inventory_service),
) -> TransactionSettlementService:
    session = unit_of_work.session
    return TransactionSettlementService(
        transaction_repository=TransactionRepository(session=session),
        settlement_repository=TransactionSettlementRepository(session=session),
        payment_repository=TransactionPaymentRepository(session=session),
        refund_repository=TransactionRefundRepository(session=session),
        supplier_refund_repository=PurchaseSupplierRefundRepository(
            session=session
        ),
        sale_return_repository=SaleReturnRepository(session=session),
        purchase_return_repository=PurchaseReturnRepository(session=session),
        replacement_repository=PurchaseReplacementRepository(session=session),
        product_repository=ProductRepository(session=session),
        product_unit_repository=ProductUnitRepository(session=session),
        movement_repository=InventoryMovementRepository(session=session),
        chicken_batch_repository=ChickenBatchRepository(session=session),
        chicken_batch_name_counter_repository=ChickenBatchNameCounterRepository(
            session=session
        ),
        block_repository=BlockRepository(session=session),
        batch_block_repository=BatchBlockRepository(session=session),
        inventory_service=inventory_service,
        unit_of_work=unit_of_work,
        activity_service=activity_service,
        farm_repository=FarmRepository(session=session),
    )


def get_transaction_service(
    unit_of_work: UnitOfWork = Depends(get_unit_of_work),
    activity_service: ActivityService = Depends(get_activity_service),
    inventory_service: InventoryService = Depends(get_inventory_service),
) -> TransactionService:
    return TransactionService(
        transaction_repository=TransactionRepository(session=unit_of_work.session),
        transaction_item_repository=TransactionItemRepository(
            session=unit_of_work.session
        ),
        transaction_payment_repository=TransactionPaymentRepository(
            session=unit_of_work.session
        ),
        contact_repository=ContactRepository(session=unit_of_work.session),
        product_repository=ProductRepository(session=unit_of_work.session),
        product_unit_repository=ProductUnitRepository(session=unit_of_work.session),
        unit_of_work=unit_of_work,
        activity_service=activity_service,
        sale_return_repository=SaleReturnRepository(session=unit_of_work.session),
        transaction_refund_repository=TransactionRefundRepository(
            session=unit_of_work.session
        ),
        farm_settings_repository=FarmSettingsRepository(session=unit_of_work.session),
        transaction_reference_counter_repository=(
            TransactionReferenceCounterRepository(session=unit_of_work.session)
        ),
        purchase_supplier_refund_repository=PurchaseSupplierRefundRepository(
            session=unit_of_work.session
        ),
        notification_outbox_repository=NotificationOutboxRepository(
            session=unit_of_work.session
        ),
        inventory_service=inventory_service,
        purchase_return_repository=PurchaseReturnRepository(
            session=unit_of_work.session
        ),
        purchase_replacement_repository=PurchaseReplacementRepository(
            session=unit_of_work.session
        ),
        expense_repository=ExpenseRepository(session=unit_of_work.session),
        expense_payment_repository=ExpensePaymentRepository(
            session=unit_of_work.session
        ),
        expense_category_repository=ExpenseCategoryRepository(
            session=unit_of_work.session
        ),
    )


def get_product_repository(
    unit_of_work: UnitOfWork = Depends(get_unit_of_work),
) -> ProductRepository:
    return ProductRepository(session=unit_of_work.session)


def get_product_unit_repository(
    unit_of_work: UnitOfWork = Depends(get_unit_of_work),
) -> ProductUnitRepository:
    return ProductUnitRepository(session=unit_of_work.session)


def get_chicken_purchase_service(
    product_repository: ProductRepository = Depends(get_product_repository),
    transaction_service: TransactionService = Depends(get_transaction_service),
    unit_of_work: UnitOfWork = Depends(get_unit_of_work),
) -> ChickenPurchaseService:
    return ChickenPurchaseService(
        product_repository=product_repository,
        transaction_service=transaction_service,
        farm_repository=FarmRepository(session=unit_of_work.session),
    )


def get_inventory_purchase_service(
    product_repository: ProductRepository = Depends(get_product_repository),
    transaction_service: TransactionService = Depends(get_transaction_service),
) -> InventoryPurchaseService:
    return InventoryPurchaseService(
        product_repository=product_repository,
        transaction_service=transaction_service,
    )


def get_chicken_purchase_details_service(
    unit_of_work: UnitOfWork = Depends(get_unit_of_work),
) -> ChickenPurchaseDetailsService:
    session = unit_of_work.session
    return ChickenPurchaseDetailsService(
        transaction_repository=TransactionRepository(session=session),
        contact_repository=ContactRepository(session=session),
        receipt_repository=PurchaseReceiptRepository(session=session),
        receipt_item_repository=PurchaseReceiptItemRepository(session=session),
        purchase_return_repository=PurchaseReturnRepository(session=session),
        purchase_replacement_repository=PurchaseReplacementRepository(
            session=session
        ),
        supplier_refund_repository=PurchaseSupplierRefundRepository(
            session=session
        ),
        unit_of_work=unit_of_work,
    )


def get_chicken_sale_details_service(
    unit_of_work: UnitOfWork = Depends(get_unit_of_work),
) -> ChickenSaleDetailsService:
    session = unit_of_work.session
    return ChickenSaleDetailsService(
        transaction_repository=TransactionRepository(session=session),
        contact_repository=ContactRepository(session=session),
        sale_delivery_repository=SaleDeliveryRepository(session=session),
        sale_return_repository=SaleReturnRepository(session=session),
        transaction_refund_repository=TransactionRefundRepository(session=session),
        unit_of_work=unit_of_work,
    )


def get_chicken_purchase_options_service(
    unit_of_work: UnitOfWork = Depends(get_unit_of_work),
) -> ChickenPurchaseOptionsService:
    session = unit_of_work.session
    return ChickenPurchaseOptionsService(
        product_repository=ProductRepository(session=session),
        contact_repository=ContactRepository(session=session),
        block_repository=BlockRepository(session=session),
        chicken_batch_repository=ChickenBatchRepository(session=session),
        batch_block_repository=BatchBlockRepository(session=session),
        unit_of_work=unit_of_work,
    )


def get_chicken_sale_options_service(
    unit_of_work: UnitOfWork = Depends(get_unit_of_work),
) -> ChickenSaleOptionsService:
    session = unit_of_work.session
    return ChickenSaleOptionsService(
        product_repository=ProductRepository(session=session),
        block_repository=BlockRepository(session=session),
        chicken_batch_repository=ChickenBatchRepository(session=session),
        batch_block_repository=BatchBlockRepository(session=session),
        unit_of_work=unit_of_work,
    )


def get_purchase_receipt_service(
    unit_of_work: UnitOfWork = Depends(get_unit_of_work),
    activity_service: ActivityService = Depends(get_activity_service),
    inventory_service: InventoryService = Depends(get_inventory_service),
) -> PurchaseReceiptService:
    session = unit_of_work.session
    return PurchaseReceiptService(
        transaction_repository=TransactionRepository(session=session),
        product_repository=ProductRepository(session=session),
        receipt_repository=PurchaseReceiptRepository(session=session),
        receipt_item_repository=PurchaseReceiptItemRepository(session=session),
        receipt_item_block_allocation_repository=(
            PurchaseReceiptItemBlockAllocationRepository(session=session)
        ),
        chicken_batch_repository=ChickenBatchRepository(session=session),
        chicken_transaction_item_repository=ChickenTransactionItemRepository(
            session=session
        ),
        block_repository=BlockRepository(session=session),
        batch_block_repository=BatchBlockRepository(session=session),
        unit_of_work=unit_of_work,
        activity_service=activity_service,
        chicken_batch_name_counter_repository=(
            ChickenBatchNameCounterRepository(session=session)
        ),
        inventory_service=inventory_service,
        farm_repository=FarmRepository(session=session),
    )


def get_sale_delivery_service(
    unit_of_work: UnitOfWork = Depends(get_unit_of_work),
    activity_service: ActivityService = Depends(get_activity_service),
    inventory_service: InventoryService = Depends(get_inventory_service),
) -> SaleDeliveryService:
    session = unit_of_work.session
    return SaleDeliveryService(
        transaction_repository=TransactionRepository(session=session),
        product_repository=ProductRepository(session=session),
        batch_repository=ChickenBatchRepository(session=session),
        block_repository=BlockRepository(session=session),
        batch_block_repository=BatchBlockRepository(session=session),
        sale_delivery_repository=SaleDeliveryRepository(session=session),
        sale_return_repository=SaleReturnRepository(session=session),
        unit_of_work=unit_of_work,
        activity_service=activity_service,
        inventory_service=inventory_service,
    )


def get_chicken_sale_service(
    product_repository: ProductRepository = Depends(get_product_repository),
    transaction_service: TransactionService = Depends(get_transaction_service),
    sale_delivery_service: SaleDeliveryService = Depends(get_sale_delivery_service),
    unit_of_work: UnitOfWork = Depends(get_unit_of_work),
) -> ChickenSaleService:
    return ChickenSaleService(
        product_repository=product_repository,
        transaction_service=transaction_service,
        sale_delivery_service=sale_delivery_service,
        unit_of_work=unit_of_work,
    )


def get_purchase_return_service(
    unit_of_work: UnitOfWork = Depends(get_unit_of_work),
    activity_service: ActivityService = Depends(get_activity_service),
    inventory_service: InventoryService = Depends(get_inventory_service),
) -> PurchaseReturnService:
    session = unit_of_work.session
    return PurchaseReturnService(
        transaction_repository=TransactionRepository(session=session),
        product_repository=ProductRepository(session=session),
        chicken_transaction_item_repository=ChickenTransactionItemRepository(
            session=session
        ),
        receipt_item_repository=PurchaseReceiptItemRepository(session=session),
        purchase_return_repository=PurchaseReturnRepository(session=session),
        supplier_refund_repository=PurchaseSupplierRefundRepository(session=session),
        replacement_repository=PurchaseReplacementRepository(session=session),
        payment_repository=TransactionPaymentRepository(session=session),
        block_repository=BlockRepository(session=session),
        batch_block_repository=BatchBlockRepository(session=session),
        unit_of_work=unit_of_work,
        activity_service=activity_service,
        inventory_service=inventory_service,
    )


def get_purchase_supplier_refund_service(
    unit_of_work: UnitOfWork = Depends(get_unit_of_work),
    activity_service: ActivityService = Depends(get_activity_service),
) -> PurchaseSupplierRefundService:
    session = unit_of_work.session
    return PurchaseSupplierRefundService(
        transaction_repository=TransactionRepository(session=session),
        payment_repository=TransactionPaymentRepository(session=session),
        purchase_return_repository=PurchaseReturnRepository(session=session),
        supplier_refund_repository=PurchaseSupplierRefundRepository(session=session),
        replacement_repository=PurchaseReplacementRepository(session=session),
        unit_of_work=unit_of_work,
        activity_service=activity_service,
    )


def get_purchase_replacement_service(
    unit_of_work: UnitOfWork = Depends(get_unit_of_work),
    activity_service: ActivityService = Depends(get_activity_service),
    inventory_service: InventoryService = Depends(get_inventory_service),
) -> PurchaseReplacementService:
    session = unit_of_work.session
    return PurchaseReplacementService(
        transaction_repository=TransactionRepository(session=session),
        chicken_batch_repository=ChickenBatchRepository(session=session),
        block_repository=BlockRepository(session=session),
        batch_block_repository=BatchBlockRepository(session=session),
        purchase_return_repository=PurchaseReturnRepository(session=session),
        purchase_supplier_refund_repository=PurchaseSupplierRefundRepository(
            session=session
        ),
        purchase_replacement_repository=PurchaseReplacementRepository(session=session),
        transaction_payment_repository=TransactionPaymentRepository(session=session),
        unit_of_work=unit_of_work,
        activity_service=activity_service,
        inventory_service=inventory_service,
    )


def get_chicken_movement_service(
    unit_of_work: UnitOfWork = Depends(get_unit_of_work),
    activity_service: ActivityService = Depends(get_activity_service),
) -> ChickenMovementService:
    session = unit_of_work.session
    return ChickenMovementService(
        movement_repository=ChickenMovementRepository(session=session),
        chicken_batch_repository=ChickenBatchRepository(session=session),
        block_repository=BlockRepository(session=session),
        batch_block_repository=BatchBlockRepository(session=session),
        unit_of_work=unit_of_work,
        activity_service=activity_service,
        notification_outbox_repository=NotificationOutboxRepository(session=session),
    )


def get_chicken_loss_service(
    unit_of_work: UnitOfWork = Depends(get_unit_of_work),
    activity_service: ActivityService = Depends(get_activity_service),
    inventory_service: InventoryService = Depends(get_inventory_service),
) -> ChickenLossService:
    session = unit_of_work.session
    return ChickenLossService(
        loss_repository=ChickenLossRepository(session=session),
        chicken_batch_repository=ChickenBatchRepository(session=session),
        batch_block_repository=BatchBlockRepository(session=session),
        unit_of_work=unit_of_work,
        activity_service=activity_service,
        block_repository=BlockRepository(session=session),
        chicken_transaction_item_repository=ChickenTransactionItemRepository(
            session=session
        ),
        inventory_service=inventory_service,
    )


def get_egg_collection_service(
    unit_of_work: UnitOfWork = Depends(get_unit_of_work),
    activity_service: ActivityService = Depends(get_activity_service),
    inventory_service: InventoryService = Depends(get_inventory_service),
) -> EggCollectionService:
    session = unit_of_work.session
    return EggCollectionService(
        collection_repository=EggCollectionRepository(session=session),
        product_repository=ProductRepository(session=session),
        product_unit_repository=ProductUnitRepository(session=session),
        block_repository=BlockRepository(session=session),
        unit_of_work=unit_of_work,
        activity_service=activity_service,
        inventory_service=inventory_service,
        farm_repository=FarmRepository(session=session),
    )


def get_inventory_opening_setup_service(
    unit_of_work: UnitOfWork = Depends(get_unit_of_work),
    activity_service: ActivityService = Depends(get_activity_service),
    inventory_service: InventoryService = Depends(get_inventory_service),
) -> InventoryOpeningSetupService:
    session = unit_of_work.session
    return InventoryOpeningSetupService(
        farm_repository=FarmRepository(session=session),
        setup_repository=InventoryOpeningSetupRepository(session=session),
        batch_repository=ChickenBatchRepository(session=session),
        batch_block_repository=BatchBlockRepository(session=session),
        block_repository=BlockRepository(session=session),
        collection_repository=EggCollectionRepository(session=session),
        product_repository=ProductRepository(session=session),
        product_unit_repository=ProductUnitRepository(session=session),
        inventory_service=inventory_service,
        activity_service=activity_service,
        unit_of_work=unit_of_work,
    )


def get_egg_collection_options_service(
    unit_of_work: UnitOfWork = Depends(get_unit_of_work),
) -> EggCollectionOptionsService:
    session = unit_of_work.session
    return EggCollectionOptionsService(
        product_repository=ProductRepository(session=session),
        block_repository=BlockRepository(session=session),
        collection_repository=EggCollectionRepository(session=session),
        loss_repository=EggLossRepository(session=session),
        inventory_movement_repository=InventoryMovementRepository(session=session),
        transaction_item_repository=TransactionItemRepository(session=session),
        unit_of_work=unit_of_work,
    )


def get_egg_loss_service(
    unit_of_work: UnitOfWork = Depends(get_unit_of_work),
    activity_service: ActivityService = Depends(get_activity_service),
    inventory_service: InventoryService = Depends(get_inventory_service),
) -> EggLossService:
    session = unit_of_work.session
    return EggLossService(
        loss_repository=EggLossRepository(session=session),
        collection_repository=EggCollectionRepository(session=session),
        product_repository=ProductRepository(session=session),
        product_unit_repository=ProductUnitRepository(session=session),
        transaction_item_repository=TransactionItemRepository(session=session),
        inventory_movement_repository=InventoryMovementRepository(session=session),
        unit_of_work=unit_of_work,
        activity_service=activity_service,
        inventory_service=inventory_service,
    )


def get_egg_sale_service(
    unit_of_work: UnitOfWork = Depends(get_unit_of_work),
    transaction_service: TransactionService = Depends(get_transaction_service),
) -> EggSaleService:
    session = unit_of_work.session
    return EggSaleService(
        product_repository=ProductRepository(session=session),
        product_unit_repository=ProductUnitRepository(session=session),
        collection_repository=EggCollectionRepository(session=session),
        loss_repository=EggLossRepository(session=session),
        inventory_movement_repository=InventoryMovementRepository(session=session),
        transaction_item_repository=TransactionItemRepository(session=session),
        transaction_service=transaction_service,
        unit_of_work=unit_of_work,
    )


def get_product_consumption_service(
    unit_of_work: UnitOfWork = Depends(get_unit_of_work),
    activity_service: ActivityService = Depends(get_activity_service),
    inventory_service: InventoryService = Depends(get_inventory_service),
) -> ProductConsumptionService:
    session = unit_of_work.session
    return ProductConsumptionService(
        consumption_repository=ProductConsumptionRepository(session=session),
        product_repository=ProductRepository(session=session),
        product_unit_repository=ProductUnitRepository(session=session),
        block_repository=BlockRepository(session=session),
        chicken_batch_repository=ChickenBatchRepository(session=session),
        batch_block_repository=BatchBlockRepository(session=session),
        unit_of_work=unit_of_work,
        activity_service=activity_service,
        inventory_service=inventory_service,
    )


def get_expense_service(
    unit_of_work: UnitOfWork = Depends(get_unit_of_work),
    activity_service: ActivityService = Depends(get_activity_service),
) -> ExpenseService:
    session = unit_of_work.session
    return ExpenseService(
        expense_repository=ExpenseRepository(session=session),
        contact_repository=ContactRepository(session=session),
        unit_of_work=unit_of_work,
        activity_service=activity_service,
        category_repository=ExpenseCategoryRepository(session=session),
        payment_repository=ExpensePaymentRepository(session=session),
        block_repository=BlockRepository(session=session),
    )


def get_notification_service(
    unit_of_work: UnitOfWork = Depends(get_unit_of_work),
) -> NotificationService:
    return NotificationService(
        repository=NotificationRepository(unit_of_work.session),
        unit_of_work=unit_of_work,
    )


def get_reminder_service(
    unit_of_work: UnitOfWork = Depends(get_unit_of_work),
) -> ReminderService:
    session = unit_of_work.session
    return ReminderService(
        repository=ReminderRepository(session),
        unit_of_work=unit_of_work,
        farm_settings_repository=FarmSettingsRepository(session),
    )


def get_sales_report_service(
    unit_of_work: UnitOfWork = Depends(get_unit_of_work),
) -> SalesReportService:
    return SalesReportService(
        transaction_repository=TransactionRepository(session=unit_of_work.session),
        unit_of_work=unit_of_work,
    )


def get_receipt_history_service(
    unit_of_work: UnitOfWork = Depends(get_unit_of_work),
) -> ReceiptHistoryService:
    return ReceiptHistoryService(
        transaction_repository=TransactionRepository(session=unit_of_work.session),
        unit_of_work=unit_of_work,
    )


def get_profitability_report_service(
    unit_of_work: UnitOfWork = Depends(get_unit_of_work),
    activity_service: ActivityService = Depends(get_activity_service),
) -> ProfitabilityReportService:
    return ProfitabilityReportService(
        session=unit_of_work.session,
        unit_of_work=unit_of_work,
        activity_service=activity_service,
    )


def get_sale_return_service(
    unit_of_work: UnitOfWork = Depends(get_unit_of_work),
    activity_service: ActivityService = Depends(get_activity_service),
    inventory_service: InventoryService = Depends(get_inventory_service),
) -> SaleReturnService:
    session = unit_of_work.session
    return SaleReturnService(
        transaction_repository=TransactionRepository(session=session),
        product_repository=ProductRepository(session=session),
        sale_delivery_repository=SaleDeliveryRepository(session=session),
        sale_return_repository=SaleReturnRepository(session=session),
        transaction_payment_repository=TransactionPaymentRepository(session=session),
        transaction_refund_repository=TransactionRefundRepository(session=session),
        contact_repository=ContactRepository(session=session),
        chicken_batch_repository=ChickenBatchRepository(session=session),
        block_repository=BlockRepository(session=session),
        batch_block_repository=BatchBlockRepository(session=session),
        unit_of_work=unit_of_work,
        activity_service=activity_service,
        inventory_service=inventory_service,
        notification_outbox_repository=NotificationOutboxRepository(session=session),
    )


def get_transaction_refund_service(
    unit_of_work: UnitOfWork = Depends(get_unit_of_work),
    activity_service: ActivityService = Depends(get_activity_service),
) -> TransactionRefundService:
    session = unit_of_work.session
    return TransactionRefundService(
        transaction_repository=TransactionRepository(session=session),
        transaction_payment_repository=TransactionPaymentRepository(session=session),
        transaction_refund_repository=TransactionRefundRepository(session=session),
        sale_return_repository=SaleReturnRepository(session=session),
        unit_of_work=unit_of_work,
        activity_service=activity_service,
    )


def get_farm_assistant_service(
    profitability_service: ProfitabilityReportService = Depends(
        get_profitability_report_service
    ),
    account_ledger_service: AccountLedgerService = Depends(
        get_account_ledger_service
    ),
    inventory_service: InventoryService = Depends(get_inventory_service),
    sales_report_service: SalesReportService = Depends(get_sales_report_service),
    purchase_history_service: ReceiptHistoryService = Depends(
        get_receipt_history_service
    ),
    transaction_refund_service: TransactionRefundService = Depends(
        get_transaction_refund_service
    ),
    sale_return_service: SaleReturnService = Depends(get_sale_return_service),
    sale_delivery_service: SaleDeliveryService = Depends(get_sale_delivery_service),
    chicken_purchase_details_service: ChickenPurchaseDetailsService = Depends(
        get_chicken_purchase_details_service
    ),
    purchase_return_service: PurchaseReturnService = Depends(
        get_purchase_return_service
    ),
    purchase_replacement_service: PurchaseReplacementService = Depends(
        get_purchase_replacement_service
    ),
    purchase_supplier_refund_service: PurchaseSupplierRefundService = Depends(
        get_purchase_supplier_refund_service
    ),
    expense_service: ExpenseService = Depends(get_expense_service),
    block_service: BlockService = Depends(get_block_service),
    product_service: ProductService = Depends(get_product_service),
    chicken_loss_service: ChickenLossService = Depends(get_chicken_loss_service),
    chicken_movement_service: ChickenMovementService = Depends(
        get_chicken_movement_service
    ),
    egg_collection_service: EggCollectionService = Depends(
        get_egg_collection_service
    ),
    egg_loss_service: EggLossService = Depends(get_egg_loss_service),
    product_consumption_service: ProductConsumptionService = Depends(
        get_product_consumption_service
    ),
    provider_manager: AIProviderManager = Depends(get_ai_provider_manager),
    unit_of_work: UnitOfWork = Depends(get_unit_of_work),
) -> FarmAssistantService:
    return FarmAssistantService(
        profitability_service,
        account_ledger_service=account_ledger_service,
        inventory_service=inventory_service,
        sales_report_service=sales_report_service,
        purchase_history_service=purchase_history_service,
        transaction_repository=TransactionRepository(
            session=unit_of_work.session
        ),
        sale_delivery_service=sale_delivery_service,
        chicken_purchase_details_service=chicken_purchase_details_service,
        transaction_refund_service=transaction_refund_service,
        purchase_return_service=purchase_return_service,
        purchase_replacement_service=purchase_replacement_service,
        purchase_supplier_refund_service=purchase_supplier_refund_service,
        sale_return_service=sale_return_service,
        expense_service=expense_service,
        block_service=block_service,
        product_service=product_service,
        chicken_loss_service=chicken_loss_service,
        chicken_movement_service=chicken_movement_service,
        egg_collection_service=egg_collection_service,
        egg_loss_service=egg_loss_service,
        product_consumption_service=product_consumption_service,
        provider_manager=provider_manager,
        conversation_repository=AssistantConversationRepository(
            unit_of_work.session
        ),
        unit_of_work=unit_of_work,
    )
