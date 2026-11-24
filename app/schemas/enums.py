from enum import StrEnum


class UserRole(StrEnum):
    USER = "USER"
    SUPER_ADMIN = "SUPER_ADMIN"


class ContactRoleEnum(StrEnum):
    CUSTOMER = "customer"
    SUPPLIER = "supplier"


class ThemeMode(StrEnum):
    LIGHT = "light"
    DARK = "dark"
    SYSTEM = "system"


class FarmRole(StrEnum):
    OWNER = "owner"
    MANAGER = "manager"
    WORKER = "worker"


class FarmMembershipStatus(StrEnum):
    INVITED = "invited"
    ACTIVE = "active"
    REVOKED = "revoked"


class FarmInvitationEmailStatus(StrEnum):
    NOT_CONFIGURED = "not_configured"
    QUEUED = "queued"
    SENT = "sent"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ProductType(StrEnum):
    EGGS = "eggs"
    CHICKENS = "chickens"
    FEED = "feed"
    MEDICATION = "medication"
    EQUIPMENT = "equipment"
    OTHER = "other"

class ChickenType(StrEnum):
    LAYERS = "layers"
    BROILER = "broiler"
    KIENYEJI = "kienyeji"
    BREEDER = "breeder"
    OTHER = "other"

class ChickenBatchStatus(StrEnum):
    ACTIVE = "active"
    COMPLETED = "completed"
    CANCELED = "canceled"


class ChickenLossReason(StrEnum):
    DISEASE = "disease"
    NATURAL_DEATH = "natural_death"
    PREDATOR = "predator"
    INJURY = "injury"
    ACCIDENT = "accident"
    CULLING = "culling"
    MISSING = "missing"
    OTHER = "other"


class EggLossReason(StrEnum):
    BROKEN = "broken"
    SPOILED = "spoiled"
    CONTAMINATED = "contaminated"
    DAMAGED = "damaged"
    DISCARDED = "discarded"
    OTHER = "other"


class ExpenseCategory(StrEnum):
    FEED = "feed"
    MEDICATION = "medication"
    VETERINARY = "veterinary"
    LABOR = "labor"
    UTILITIES = "utilities"
    TRANSPORT = "transport"
    REPAIRS = "repairs"
    RENT = "rent"
    EQUIPMENT = "equipment"
    PACKAGING = "packaging"
    OTHER = "other"


class NotificationCategory(StrEnum):
    ALERT = "alert"
    TRANSACTION = "transaction"
    REMINDER = "reminder"
    FARM = "farm"
    SECURITY = "security"


class NotificationPriority(StrEnum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    CRITICAL = "critical"


class NotificationEventType(StrEnum):
    PURCHASE_RECORDED = "purchase.recorded"
    SALE_RECORDED = "sale.recorded"
    PAYMENT_RECORDED = "payment.recorded"
    CHICKEN_RETURN_RECORDED = "chicken_return.recorded"
    CHICKEN_MOVEMENT_RECORDED = "chicken_movement.recorded"
    REMINDER_DUE = "reminder.due"


class ReminderStatus(StrEnum):
    PENDING = "PENDING"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class TransactionType(StrEnum):
    SALE = "sale"
    PURCHASE = "purchase"


class TransactionStatus(StrEnum):
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class SaleReturnType(StrEnum):
    UNDELIVERED_CANCELLED = "undelivered_cancelled"
    DELIVERED_RETURN = "delivered_return"


class PaymentMethod(StrEnum):
    CASH = "cash"
    MPESA = "mpesa"
    BANK_TRANSFER = "bank_transfer"
    CARD = "card"
    OTHER = "other"


class ActivityType(StrEnum):
    FARM_CREATED = "farm_created"
    FARM_UPDATED = "farm_updated"
    FARM_DELETED = "farm_deleted"
    FARM_SETTINGS_UPDATED = "farm_settings_updated"
    BLOCK_CREATED = "block_created"
    BLOCK_UPDATED = "block_updated"
    BLOCK_DELETED = "block_deleted"
    CONTACT_CREATED = "contact_created"
    CONTACT_UPDATED = "contact_updated"
    CONTACT_DELETED = "contact_deleted"
    CONTACT_ROLE_CREATED = "contact_role_created"
    CONTACT_ROLE_UPDATED = "contact_role_updated"
    CONTACT_ROLE_DELETED = "contact_role_deleted"
    CONTACT_ROLE_PRODUCT_ADDED = "contact_role_product_added"
    CONTACT_ROLE_PRODUCT_REMOVED = "contact_role_product_removed"
    TRANSACTION_CREATED = "transaction_created"
    TRANSACTION_PAYMENT_RECORDED = "transaction_payment_recorded"
    PURCHASE_RECEIPT_CREATED = "purchase_receipt_created"
    PURCHASE_RETURN_CREATED = "purchase_return_created"
    PURCHASE_SUPPLIER_REFUND_RECORDED = "purchase_supplier_refund_recorded"
    PURCHASE_REPLACEMENT_RECEIVED = "purchase_replacement_received"
    CHICKEN_MOVEMENT_CREATED = "chicken_movement_created"
    CHICKEN_LOSS_RECORDED = "chicken_loss_recorded"
    EGG_COLLECTION_RECORDED = "egg_collection_recorded"
    EGG_LOSS_RECORDED = "egg_loss_recorded"
    PRODUCT_CONSUMPTION_RECORDED = "product_consumption_recorded"
    EXPENSE_RECORDED = "expense_recorded"
    NOTIFICATION_CREATED = "notification_created"
    SALE_DELIVERY_CREATED = "sale_delivery_created"
    SALE_RETURN_CREATED = "sale_return_created"
    TRANSACTION_REFUND_CREATED = "transaction_refund_created"
    INVENTORY_ADJUSTED = "inventory_adjusted"
    TRANSACTION_SETTLEMENT_RECORDED = "transaction_settlement_recorded"
    INVENTORY_OPENING_STOCK_RECORDED = "inventory_opening_stock_recorded"


class ActivityEntityType(StrEnum):
    FARM = "farm"
    BLOCK = "block"
    CONTACT = "contact"
    CONTACT_ROLE = "contact_role"
    CONTACT_ROLE_PRODUCT = "contact_role_product"
    TRANSACTION = "transaction"
    TRANSACTION_PAYMENT = "transaction_payment"
    PURCHASE_RECEIPT = "purchase_receipt"
    PURCHASE_RETURN = "purchase_return"
    PURCHASE_SUPPLIER_REFUND = "purchase_supplier_refund"
    PURCHASE_REPLACEMENT = "purchase_replacement"
    CHICKEN_MOVEMENT = "chicken_movement"
    CHICKEN_LOSS = "chicken_loss"
    EGG_COLLECTION = "egg_collection"
    EGG_LOSS = "egg_loss"
    PRODUCT_CONSUMPTION = "product_consumption"
    EXPENSE = "expense"
    SALE_DELIVERY = "sale_delivery"
    SALE_RETURN = "sale_return"
    TRANSACTION_REFUND = "transaction_refund"
    INVENTORY_MOVEMENT = "inventory_movement"
    TRANSACTION_SETTLEMENT = "transaction_settlement"
    INVENTORY_OPENING_SETUP = "inventory_opening_setup"


class ActivityCategory(StrEnum):
    FARM = "farm"
    HOUSING = "housing"
    CONTACTS = "contacts"
    SALES = "sales"
    PURCHASES = "purchases"
    FLOCK = "flock"
    EGGS = "eggs"
    INVENTORY = "inventory"
    EXPENSES = "expenses"
    UPDATES = "updates"


class InventoryMovementType(StrEnum):
    OPENING_BALANCE = "opening_balance"
    RECEIPT = "receipt"
    SALE = "sale"
    CONSUMPTION = "consumption"
    LOSS = "loss"
    CUSTOMER_RETURN = "customer_return"
    SUPPLIER_RETURN = "supplier_return"
    SETTLEMENT_RECEIVED = "settlement_received"
    SETTLEMENT_ISSUED = "settlement_issued"
    ADJUSTMENT = "adjustment"
    VALUATION = "valuation"


class AgeUnit(StrEnum):
    DAYS = "days"
    WEEKS = "weeks"
    MONTHS = "months"
    YEARS = "years"