from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class AppRoute:
    path: str
    label: str
    purpose: str
    entry_points: tuple[str, ...]


APP_ROUTE_CATALOG = (
    AppRoute(
        path="/",
        label="Home tab",
        purpose="Farm dashboard reached after authentication and farm-state routing; the root entry redirects signed-out, blocked, recovery, and setup states elsewhere.",
        entry_points=(
            "App launch when signed in with a ready farm",
            "Home tab",
        ),
    ),
    AppRoute(
        path="/flock",
        label="Chickens tab (Flock screen)",
        purpose="Review flock batches, block assignments, stock, and chicken actions.",
        entry_points=(
            "Chickens tab",
            "Home > Poultry summary",
            "Inventory > View flock",
            "Product inventory > Manage flock & housing",
            "In-app chicken-movement notification",
        ),
    ),
    AppRoute(
        path="/eggs",
        label="Eggs tab",
        purpose="Review egg production, available eggs, and egg actions.",
        entry_points=(
            "Eggs tab",
            "Home > Egg summary",
        ),
    ),
    AppRoute(
        path="/sales",
        label="Sales tab",
        purpose="Review recent sales, balances, and outgoing deliveries.",
        entry_points=(
            "Sales tab",
            "Home > Open sales report",
        ),
    ),
    AppRoute(
        path="/account",
        label="More tab",
        purpose="Search and open farm tools, settings, and account features.",
        entry_points=(
            "More tab",
        ),
    ),
    AppRoute(
        path="/blocks",
        label="Blocks",
        purpose="Manage farm housing blocks and their capacity.",
        entry_points=(
            "More > Farm setup > Blocks",
            "Chickens > Manage blocks",
            "Block creation or deletion completion",
        ),
    ),
    AppRoute(
        path="/blocks/new",
        label="Create block",
        purpose="Create a housing block with its name and capacity.",
        entry_points=(
            "Blocks > Add block or Add first block",
            "Chickens > Add a block",
        ),
    ),
    AppRoute(
        path="/blocks/:blockId",
        label="Block details",
        purpose="Review a block's capacity, assigned birds, and block-specific actions.",
        entry_points=(
            "Blocks list",
            "Chickens tab block card",
            "Activity details > Open housing area",
        ),
    ),
    AppRoute(
        path="/blocks/:blockId/edit",
        label="Edit block",
        purpose="Update the selected block's details and capacity.",
        entry_points=(
            "Block details",
        ),
    ),
    AppRoute(
        path="/login",
        label="Sign in",
        purpose="Authenticate to a FarmTrack account.",
        entry_points=(
            "Startup redirect when signed out",
            "App redirect after sign-out",
        ),
    ),
    AppRoute(
        path="/restore-account",
        label="Restore account",
        purpose="Restore an account scheduled for deletion.",
        entry_points=(
            "Sign in > Restore scheduled account deletion",
        ),
    ),
    AppRoute(
        path="/account-details",
        label="Account & access",
        purpose="Manage account security, password, app lock, sign-in sessions, and account recovery/deletion.",
        entry_points=(
            "More > Account & security",
            "App redirect for a scheduled account deletion",
            "Farm setup > Review and restore a farm",
            "App root > Open account recovery",
        ),
    ),
    AppRoute(
        path="/activities",
        label="Activities",
        purpose="Search and review changes recorded in the farm.",
        entry_points=(
            "More > Insights & records > Activities",
            "Home > View all activity",
            "Chickens > View all flock activity",
            "Eggs > View all egg activity",
            "Reports > Farm activity > View all",
        ),
    ),
    AppRoute(
        path="/activities/:activityId",
        label="Activity details",
        purpose="Review an individual farm activity and its related record.",
        entry_points=(
            "Activities list",
            "Home, Chickens, Eggs, and Reports > Select an activity row",
        ),
    ),
    AppRoute(
        path="/assistant",
        label="FarmMate assistant",
        purpose="Ask read-only questions about farm records and how to use FarmTrack.",
        entry_points=(
            "More > Insights & records > FarmMate",
            "Floating FarmMate button",
        ),
    ),
    AppRoute(
        path="/chicken-loss",
        label="Record chicken loss",
        purpose="Record a loss from the flock and review affected stock.",
        entry_points=(
            "More > Farm operations > Chicken losses",
            "Home > Log loss",
            "Chickens > Record loss",
        ),
    ),
    AppRoute(
        path="/chicken-loss/review",
        label="Review chicken loss",
        purpose="Review the selected chicken loss before recording it.",
        entry_points=(
            "Chicken loss form > Review losses",
        ),
    ),
    AppRoute(
        path="/chicken-movement",
        label="Move chickens",
        purpose="Move available chickens from a source block to another block.",
        entry_points=(
            "More > Farm operations > Chicken movement",
            "Chickens > Move birds",
            "Block details > Move chickens before deleting",
        ),
    ),
    AppRoute(
        path="/chicken-purchase",
        label="Record chicken purchase",
        purpose="Record an incoming chicken purchase and its arrival details.",
        entry_points=(
            "Chickens > Purchase birds",
            "Inventory > Purchase or Record purchase",
            "More > Purchases > Buy chickens",
            "Product inventory > Record chicken purchase",
            "Chicken loss form > Record a purchase",
            "Shared payment message routed by payment-message import",
        ),
    ),
    AppRoute(
        path="/chicken-sale",
        label="Record chicken sale",
        purpose="Record a chicken sale; delivery is tracked separately.",
        entry_points=(
            "Chickens > Sell chickens",
            "Home > Record sale > Sell chickens",
            "More > Sales > Record sale > Sell chickens",
            "Sales tab > Record sale > Sell chickens",
        ),
    ),
    AppRoute(
        path="/contacts",
        label="Contacts",
        purpose="Search customer and supplier records and their account balances.",
        entry_points=(
            "More > Farm setup > Contacts",
            "Contact save or delete completion",
        ),
    ),
    AppRoute(
        path="/contacts/new",
        label="Create contact",
        purpose="Create a customer or supplier contact.",
        entry_points=(
            "Contacts > Add contact or Add first contact",
        ),
    ),
    AppRoute(
        path="/contacts/:contactId",
        label="Contact details",
        purpose="Review contact information, role, and related ledger activity.",
        entry_points=(
            "Contacts list > Select a contact",
            "Contact edit completion",
            "Activity details > Open contact",
        ),
    ),
    AppRoute(
        path="/contacts/:contactId/edit",
        label="Edit contact",
        purpose="Update the selected customer or supplier record.",
        entry_points=(
            "Contact details",
        ),
    ),
    AppRoute(
        path="/device-blocked",
        label="Device blocked",
        purpose="Explain that access is blocked for the current device or account.",
        entry_points=(
            "Authentication/session guard redirect",
        ),
    ),
    AppRoute(
        path="/egg-collection",
        label="Record egg collection",
        purpose="Record eggs collected by product and block.",
        entry_points=(
            "More > Farm operations > Egg collection",
            "Home > Collect eggs",
            "Eggs > Collect eggs or Record egg collection",
            "Inventory > Collect eggs",
            "Product inventory > Record egg collection",
            "Egg sale > Record egg collection",
        ),
    ),
    AppRoute(
        path="/egg-loss",
        label="Record egg loss",
        purpose="Record eggs lost from available production stock.",
        entry_points=(
            "Eggs > Record loss",
        ),
    ),
    AppRoute(
        path="/egg-sale",
        label="Record egg sale",
        purpose="Record an egg sale and its payment details.",
        entry_points=(
            "Eggs > Sell eggs",
            "Home > Record sale > Sell eggs",
            "More > Sales > Record sale > Sell eggs",
            "Sales tab > Record sale > Sell eggs",
        ),
    ),
    AppRoute(
        path="/expenses",
        label="Expenses",
        purpose="Review expenses or start recording a farm expense.",
        entry_points=(
            "More > Farm operations > Expenses",
            "Home > Add expense",
        ),
    ),
    AppRoute(
        path="/expenses/:expenseId",
        label="Expense details",
        purpose="Review an expense, payment state, and linked records.",
        entry_points=(
            "Expenses list",
            "Reports > Expenses > Select an expense",
        ),
    ),
    AppRoute(
        path="/farm-setup",
        label="Farm setup",
        purpose="Complete initial or additional farm setup and review setup tasks.",
        entry_points=(
            "App redirect when the farm is empty",
            "Home > Set up farm",
            "Account & access > Set up your farm",
            "Farm selector > Add another farm",
            "Setup-flow return from product, block, and opening-stock screens",
        ),
    ),
    AppRoute(
        path="/farm-team",
        label="Team & invitations",
        purpose="Manage farm members, invitations, and membership roles.",
        entry_points=(
            "More > Farm setup > Team & invitations",
            "Farm setup > Check invitations",
        ),
    ),
    AppRoute(
        path="/inventory",
        label="Inventory",
        purpose="Review current product stock and stock movements.",
        entry_points=(
            "More > Farm operations > Inventory",
            "Home > Feed, equipment & other stock",
            "Product consumption > Go to inventory",
            "Inventory purchase completion",
        ),
    ),
    AppRoute(
        path="/inventory/consumption",
        label="Product consumption",
        purpose="Record feed, medicine, or other product consumption and allocations.",
        entry_points=(
            "More > Farm operations > Product consumption",
            "Inventory > Record supply use",
        ),
    ),
    AppRoute(
        path="/inventory/opening-stock",
        label="Opening stock",
        purpose="Set initial product stock quantities for the farm.",
        entry_points=(
            "More > Farm operations > Opening stock",
            "Inventory > Opening flock, Opening stock, or Set up product",
            "Farm setup > Record opening balance",
            "Opening stock > Set up egg product or Set up chicken product",
        ),
    ),
    AppRoute(
        path="/inventory/purchase",
        label="Inventory purchase",
        purpose="Record an incoming supply purchase and its supplier/payment details.",
        entry_points=(
            "Inventory > Purchase supplies",
            "More > Purchases > Buy other stock",
            "Product inventory > Record purchase",
        ),
    ),
    AppRoute(
        path="/notifications",
        label="Notifications",
        purpose="Review in-app notices and open their related records.",
        entry_points=(
            "More > Insights & records > Notifications",
            "Home > Unread farm updates",
            "Farm page header > Notifications",
        ),
    ),
    AppRoute(
        path="/products",
        label="Products",
        purpose="Manage the farm's product catalogue.",
        entry_points=(
            "More > Farm setup > Products",
            "Eggs > View egg products or Manage egg products",
            "Inventory > Products",
            "Chicken or egg sale form > Manage products",
            "Product deletion completion",
        ),
    ),
    AppRoute(
        path="/products/new",
        label="Create product",
        purpose="Create a product and configure its type and units.",
        entry_points=(
            "Products > Add a product",
            "Eggs > Add an egg product",
            "Inventory > Add or set up a product",
            "Farm setup > Add product",
            "Opening stock > Set up egg product or Set up chicken product",
        ),
    ),
    AppRoute(
        path="/products/:productId",
        label="Product details",
        purpose="Review an individual product and its configuration.",
        entry_points=(
            "Products list > Select a product",
            "Product edit completion",
            "Activity details > Open product",
        ),
    ),
    AppRoute(
        path="/products/:productId/edit",
        label="Edit product",
        purpose="Update an existing product's details and configuration.",
        entry_points=(
            "Product details > Edit product",
            "Farm setup > Edit product",
        ),
    ),
    AppRoute(
        path="/products/:productId/inventory",
        label="Product inventory",
        purpose="Review stock balance and inventory activity for one product.",
        entry_points=(
            "Product details > Stock & movement history",
            "Eggs > View product stock details",
            "Inventory > Product stock row",
            "Farm setup > Record an opening balance",
            "Reports > Product stock link",
            "Activity details > Open product stock",
        ),
    ),
    AppRoute(
        path="/purchases",
        label="Purchases",
        purpose="Review purchases and start purchase workflows.",
        entry_points=(
            "More > Farm operations > Purchases",
        ),
    ),
    AppRoute(
        path="/purchases/:purchaseId",
        label="Purchase details",
        purpose="Review a purchase, its payments, and receipt/arrival actions.",
        entry_points=(
            "Purchases list",
            "Notifications > Purchase update",
            "Expense details > Related purchase",
            "Reminder details > Related purchase",
            "Contacts > Purchase transaction",
            "Activity details > Open purchase",
        ),
    ),
    AppRoute(
        path="/purchases/:purchaseId/receive",
        label="Receive chicken purchase",
        purpose="Record the arrival of chickens associated with a purchase.",
        entry_points=(
            "Purchase details > Record receipt",
            "Chicken purchase success > Receive chickens",
        ),
    ),
    AppRoute(
        path="/receipts",
        label="Receipts",
        purpose="Find receipts for sales, purchases, and payments.",
        entry_points=(
            "More > Farm operations > Receipts",
        ),
    ),
    AppRoute(
        path="/reminders",
        label="Reminders",
        purpose="Review and manage farm reminders.",
        entry_points=(
            "Home > View reminders",
            "FarmMate assistant > Reminder link",
        ),
    ),
    AppRoute(
        path="/reminders/:reminderId",
        label="Reminder details",
        purpose="Review a reminder and its related action or record.",
        entry_points=(
            "Reminders list",
            "Home reminder card",
            "In-app notification",
        ),
    ),
    AppRoute(
        path="/reports",
        label="Reports overview",
        purpose="Browse farm reports covering sales, production, stock, and financial performance.",
        entry_points=(
            "More > Insights & records > Reports",
            "Home > Financial reports",
            "Home > Open profitability report or Review missing records",
        ),
    ),
    AppRoute(
        path="/reports/:report",
        label="Farm report",
        purpose="Review a report selected by report type and applicable date range.",
        entry_points=(
            "Reports overview > Select a report or report card",
            "Product inventory > Review production records",
            "Profitability report > Select a linked report",
        ),
    ),
    AppRoute(
        path="/reports/stock-costing",
        label="Stock costing report",
        purpose="Review stock valuation and costing details.",
        entry_points=(
            "Home > Add missing stock costs",
            "Profitability report > Enter estimated cost",
        ),
    ),
    AppRoute(
        path="/sales/new",
        label="New sale",
        purpose="Choose whether to start an egg or chicken sale.",
        entry_points=(
            "More > Sales",
            "Sales tab > Record sale",
            "Home > Record sale",
        ),
    ),
    AppRoute(
        path="/sales/:saleId",
        label="Sale details",
        purpose="Review a sale, outstanding balance, and delivery status/actions.",
        entry_points=(
            "Sales list",
            "Sale form completion",
            "Delivery form completion",
            "Notifications > Sale update",
            "Reminders > Related sale",
            "Contacts > Sale transaction",
            "Activity details > Open sale",
            "Reports > Select a sale",
            "Profitability report > Open sale",
        ),
    ),
    AppRoute(
        path="/sales/:saleId/deliver",
        label="Record chicken delivery",
        purpose="Record birds delivered against a chicken sale.",
        entry_points=(
            "Sale details > Record chicken delivery",
            "Home > Record delivery for a pending sale",
            "Chickens > Record delivery",
        ),
    ),
    AppRoute(
        path="/sales/:saleId/deliver-eggs",
        label="Record egg delivery",
        purpose="Record eggs delivered against an egg sale.",
        entry_points=(
            "Egg sale details > Record egg delivery",
            "Home > Record delivery for a pending egg sale",
        ),
    ),
    AppRoute(
        path="/sessions/:sessionId/activity",
        label="Sign-in activity",
        purpose="Review activity associated with one signed-in device/session.",
        entry_points=(
            "Account & access > Session activity",
        ),
    ),
    AppRoute(
        path="/setup/block",
        label="Setup block",
        purpose="Create a housing block as one step in farm setup.",
        entry_points=(
            "Farm setup > Create housing block",
        ),
    ),
    AppRoute(
        path="/settings",
        label="Farm profile & settings",
        purpose="View or edit farm identity, contact, capacity, appearance, and regional defaults.",
        entry_points=(
            "More > Farm setup > Farm profile",
            "More > Farm setup > Theme & appearance",
            "More > Farm setup > Currency & time zone",
            "More > Farm setup > Farm capacity & status",
        ),
    ),
    AppRoute(
        path="/settings/expense-categories",
        label="Expense categories",
        purpose="Create or manage categories used to organize farm expenses.",
        entry_points=(
            "More > Farm setup > Expense categories",
            "Expenses > Categories",
        ),
    ),
    AppRoute(
        path="/transactions/:transactionId/receipt",
        label="Transaction receipt",
        purpose="View or share the receipt for a transaction.",
        entry_points=(
            "Receipts > Open a receipt",
            "Sale or purchase details > Generate receipt",
            "Sale or purchase details > Generate payment receipt",
        ),
    ),
    AppRoute(
        path="/transactions/:transactionId/returns",
        label="Returns and refunds",
        purpose="Record or review returned goods, refunds, or replacement adjustments.",
        entry_points=(
            "Sale or purchase details > Record a product return",
            "In-app return notification",
        ),
    ),
    AppRoute(
        path="/transactions/:transactionId/settlements",
        label="Settle transaction balance",
        purpose="Record a payment against an outstanding sale or purchase balance.",
        entry_points=(
            "Sale or purchase details > Settle balance",
            "Home > Outstanding balance action",
            "Reminder details > Settle balance",
            "Inventory purchase > Record payment",
        ),
    ),
    AppRoute(
        path="/units",
        label="Units and conversions",
        purpose="Configure measurement units and conversions used by products.",
        entry_points=(
            "More > Farm setup > Units",
            "Product form unit links",
        ),
    ),
)

_ROUTES_BY_PATH = {route.path: route for route in APP_ROUTE_CATALOG}
_DYNAMIC_SEGMENT = re.compile(r":[A-Za-z][A-Za-z0-9_]*")


def resolve_app_route(path: str) -> AppRoute | None:
    normalized = path
    if normalized.startswith("/(tabs)"):
        normalized = normalized[len("/(tabs)"):] or "/"
    if normalized.startswith("/(auth)"):
        normalized = normalized[len("/(auth)"):] or "/"

    route = _ROUTES_BY_PATH.get(normalized)
    if route is not None:
        return route

    for template, candidate in _ROUTES_BY_PATH.items():
        if ":" not in template:
            continue
        pattern = "^" + _DYNAMIC_SEGMENT.sub(r"[^/]+", re.escape(template)) + "$"
        if re.fullmatch(pattern, normalized):
            return candidate
    return None


def describe_app_route(route: AppRoute) -> str:
    entry_points = "; ".join(route.entry_points)
    return (
        f"Route pattern: {route.path}. Screen: {route.label}. "
        f"Purpose: {route.purpose} "
        f"Known entry points: {entry_points}."
    )
