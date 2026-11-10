from fastapi import APIRouter

from app.api.v1.endpoints import auth
from app.api.v1.endpoints import activities
from app.api.v1.endpoints import blocks
from app.api.v1.endpoints import contacts
from app.api.v1.endpoints import farm 
from app.api.v1.endpoints import security_settings
from app.api.v1.endpoints import units
from app.api.v1.endpoints import products
from app.api.v1.endpoints import purchase_receipts
from app.api.v1.endpoints import chicken_purchase
from app.api.v1.endpoints import chicken_sale
from app.api.v1.endpoints import sale_deliveries
from app.api.v1.endpoints import sale_returns
from app.api.v1.endpoints import transaction_payments
from app.api.v1.endpoints import transaction_refunds
from app.api.v1.endpoints import purchase_returns
from app.api.v1.endpoints import purchase_supplier_refunds
from app.api.v1.endpoints import purchase_replacements
from app.api.v1.endpoints import chicken_movements
from app.api.v1.endpoints import chicken_losses
from app.api.v1.endpoints import egg_collections
from app.api.v1.endpoints import egg_losses
from app.api.v1.endpoints import egg_sales
from app.api.v1.endpoints import product_consumptions
from app.api.v1.endpoints import expenses
from app.api.v1.endpoints import notifications
from app.api.v1.endpoints import reminders
from app.api.v1.endpoints import sales
from app.api.v1.endpoints import inventory
from app.api.v1.endpoints import inventory_opening_setup
from app.api.v1.endpoints import transaction_settlements
from app.api.v1.endpoints import profitability_reports
from app.api.v1.endpoints import receipt_history
from app.api.v1.endpoints import app_releases

router = APIRouter()
router.include_router(auth.router)
router.include_router(activities.router)
router.include_router(blocks.router)
router.include_router(contacts.router)
router.include_router(farm.router)
router.include_router(security_settings.router)
router.include_router(units.router)
router.include_router(products.router)
router.include_router(purchase_receipts.router)
router.include_router(chicken_purchase.router)
router.include_router(chicken_sale.router)
router.include_router(sale_deliveries.router)
router.include_router(sale_returns.router)
router.include_router(transaction_payments.router)
router.include_router(transaction_refunds.router)
router.include_router(purchase_returns.router)
router.include_router(purchase_supplier_refunds.router)
router.include_router(purchase_replacements.router)
router.include_router(chicken_movements.router)
router.include_router(chicken_losses.router)
router.include_router(egg_collections.router)
router.include_router(egg_losses.router)
router.include_router(egg_sales.router)
router.include_router(product_consumptions.router)
router.include_router(expenses.router)
router.include_router(notifications.router)
router.include_router(reminders.router)
router.include_router(sales.router)
router.include_router(inventory.router)
router.include_router(inventory_opening_setup.router)
router.include_router(transaction_settlements.router)
router.include_router(profitability_reports.router)
router.include_router(receipt_history.router)
router.include_router(app_releases.router)