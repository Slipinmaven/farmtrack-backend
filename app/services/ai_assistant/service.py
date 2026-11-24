from datetime import date
from typing import ClassVar
from uuid import UUID

from app.core.exceptions import ResourceNotFoundError
from app.services.ai_assistant.chat import FarmAssistantChatMixin
from app.services.ai_assistant.context import FarmAssistantContextMixin
from app.services.ai_assistant.contracts import (
    AccountLedgerReader, AssistantConversationStore, AssistantProvider, ChickenLossReader,
    ChickenMovementReader, ChickenPurchaseDetailsReader, Committer, EggCollectionReader,
    EggLossReader, ExpenseReader, FarmOperationsBlockReader, FarmOperationsProductReader,
    InventoryBalanceReader, ProductConsumptionReader, ProfitabilityReportReader,
    PurchaseHistoryReader, PurchaseReplacementReader, PurchaseReturnReader,
    PurchaseSupplierRefundReader, SaleDeliveryReader, SaleReturnReader, SalesReportReader,
    TransactionRefundReader, TransactionRepositoryReader,
)
from app.services.ai_assistant.conversations import FarmAssistantConversationMixin
from app.services.ai_assistant.gemini import GeminiClient
from app.services.ai_assistant.navigation import APP_DESTINATIONS
from app.services.ai_assistant.operations import FarmAssistantOperationsMixin
from app.services.ai_assistant.service_context import AssistantServiceContext
from app.services.ai_assistant.transactions import FarmAssistantTransactionMixin


class FarmAssistantService(
    FarmAssistantChatMixin,
    FarmAssistantTransactionMixin,
    FarmAssistantOperationsMixin,
    FarmAssistantContextMixin,
    FarmAssistantConversationMixin,
    AssistantServiceContext,
):
    APP_DESTINATIONS: ClassVar[dict[str, dict[str, str]]] = APP_DESTINATIONS

    def __init__(
        self,
        profitability_service: ProfitabilityReportReader,
        *,
        account_ledger_service: AccountLedgerReader | None = None,
        inventory_service: InventoryBalanceReader | None = None,
        sales_report_service: SalesReportReader | None = None,
        purchase_history_service: PurchaseHistoryReader | None = None,
        transaction_repository: TransactionRepositoryReader | None = None,
        sale_delivery_service: SaleDeliveryReader | None = None,
        chicken_purchase_details_service: ChickenPurchaseDetailsReader | None = None,
        transaction_refund_service: TransactionRefundReader | None = None,
        purchase_return_service: PurchaseReturnReader | None = None,
        purchase_replacement_service: PurchaseReplacementReader | None = None,
        purchase_supplier_refund_service: PurchaseSupplierRefundReader | None = None,
        sale_return_service: SaleReturnReader | None = None,
        expense_service: ExpenseReader | None = None,
        block_service: FarmOperationsBlockReader | None = None,
        product_service: FarmOperationsProductReader | None = None,
        chicken_loss_service: ChickenLossReader | None = None,
        chicken_movement_service: ChickenMovementReader | None = None,
        egg_collection_service: EggCollectionReader | None = None,
        egg_loss_service: EggLossReader | None = None,
        product_consumption_service: ProductConsumptionReader | None = None,
        provider_manager: AssistantProvider | None = None,
        conversation_repository: AssistantConversationStore,
        unit_of_work: Committer,
        gemini_client: AssistantProvider | None = None,
    ) -> None:
        self.profitability_service = profitability_service
        self.account_ledger_service = account_ledger_service
        self.inventory_service = inventory_service
        self.sales_report_service = sales_report_service
        self.purchase_history_service = purchase_history_service
        self.transaction_repository = transaction_repository
        self.sale_delivery_service = sale_delivery_service
        self.chicken_purchase_details_service = chicken_purchase_details_service
        self.transaction_refund_service = transaction_refund_service
        self.purchase_return_service = purchase_return_service
        self.purchase_replacement_service = purchase_replacement_service
        self.purchase_supplier_refund_service = purchase_supplier_refund_service
        self.sale_return_service = sale_return_service
        self.expense_service = expense_service
        self.block_service = block_service
        self.product_service = product_service
        self.chicken_loss_service = chicken_loss_service
        self.chicken_movement_service = chicken_movement_service
        self.egg_collection_service = egg_collection_service
        self.egg_loss_service = egg_loss_service
        self.product_consumption_service = product_consumption_service
        self.conversation_repository = conversation_repository
        self.unit_of_work = unit_of_work
        self.provider_manager = (
            provider_manager or gemini_client or GeminiClient()
        )

    async def answer_profitability_question(
        self,
        *,
        farm_id: UUID,
        user_id: UUID,
        question: str,
        from_date: date,
        to_date: date,
        conversation_id: UUID | None = None,
    ) -> tuple[UUID, str]:
        conversation = None
        if conversation_id is not None:
            conversation = await self.conversation_repository.get_for_user(
                conversation_id=conversation_id,
                farm_id=farm_id,
                user_id=user_id,
            )
            if conversation is None:
                raise ResourceNotFoundError("Assistant conversation not found.")
            previous_messages = await self.conversation_repository.list_messages(
                conversation.id
            )
            conversation_history = [
                {"role": message.role, "content": message.content}
                for message in previous_messages[-GeminiClient.max_history_messages :]
            ]
        else:
            conversation_history = []

        report = await self.profitability_service.build_report(
            farm_id,
            from_date=from_date,
            to_date=to_date,
        )
        answer = await self.provider_manager.answer(
            question=question,
            report_context=self._safe_report_context(report),
            conversation_history=conversation_history,
        )
        if conversation is None:
            conversation = await self.conversation_repository.create(
                farm_id=farm_id,
                user_id=user_id,
                title=question,
            )
        await self.conversation_repository.add_exchange(
            conversation=conversation,
            question=question,
            answer=answer,
            from_date=from_date,
            to_date=to_date,
        )
        await self.unit_of_work.commit()
        return conversation.id, answer
