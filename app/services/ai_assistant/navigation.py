APP_DESTINATIONS: dict[str, dict[str, str]] = {
    "farm_dashboard": {
        "label": "Farm dashboard",
        "href": "/(tabs)",
        "steps": (
            "Open Home for a current overview, date-based sales highlights, "
            "items needing attention, and shortcuts into farm operations."
        ),
    },
    "account": {
        "label": "More",
        "href": "/(tabs)/account",
        "steps": (
            "Open More to find farm tools and setup options. Use its search "
            "to find a page by name, or choose a group such as Farm "
            "operations or Farm setup."
        ),
    },
    "farm_setup": {
        "label": "Farm setup",
        "href": "/farm-setup",
        "steps": (
            "Open farm setup to review the setup checklist. Add your "
            "blocks, products, units, and opening stock so later sales "
            "and stock reports use the right farm records."
        ),
    },
    "settings": {
        "label": "Settings",
        "href": "/settings",
        "steps": (
            "Open More and choose Settings. Update the farm preferences "
            "you need, then select Save changes."
        ),
    },
    "theme_settings": {
        "label": "Theme settings",
        "href": "/settings",
        "steps": (
            "Open More and choose Settings. In the appearance section, "
            "choose a theme preset, select Light, Dark, or System under "
            "Theme mode, preview it if you like, then select Save changes "
            "to keep it."
        ),
    },
    "farm_team": {
        "label": "Team and invitations",
        "href": "/farm-team",
        "steps": (
            "Open More, then Team & invitations. Owners can invite members "
            "and manage their roles; managers can manage worker access. "
            "Members can review their farm role and invitation status."
        ),
    },
    "sales": {
        "label": "Sales",
        "href": "/sales",
        "steps": (
            "Open Sales to review recent sales, balances, and any pending "
            "outgoing deliveries. Select a sale to open its details."
        ),
    },
    "record_sale": {
        "label": "Record a sale",
        "href": "/sales/new",
        "steps": (
            "Open Sales and choose New sale, then choose Sell eggs or Sell "
            "chickens. On the form, select the customer if known, add the "
            "items with quantity and unit price, optionally record the "
            "payment, review the total, and save."
        ),
    },
    "chicken_sale": {
        "label": "Record a chicken sale",
        "href": "/chicken-sale",
        "steps": (
            "Entry routes: when flock stock exists, from the Chickens tab "
            "choose Sell chickens; "
            "from Home or the Sales tab, choose Record sale/New sale and "
            "then choose Sell chickens. The direct chicken sale form is "
            "available at the link below. Choose a customer or continue as "
            "a walk-in, set the sale date (time is optional), add one or "
            "more chicken product/type, quantity and unit-price lines, "
            "optionally add a discount and payment, review, then select "
            "Record sale order. If a balance or overpayment will be left "
            "on account, a customer is required. Delivery is recorded "
            "separately from sale details after saving. If already on the "
            "sale form, guide the current stage instead of sending the user "
            "back to its starting page."
        ),
        "detailed_steps": (
            "1. Buyer and date: search and select a customer, or choose "
            "Continue without a customer for a walk-in sale. A customer is "
            "needed if recording an unpaid balance or overpayment on an "
            "account. Set the sale date and optionally include its time. "
            "2. Chickens and price: for each line choose an active chicken "
            "product and type, enter a whole-number quantity greater than "
            "zero and a price per chicken with up to two decimal places. "
            "Add lines as needed and check the available-stock message. "
            "An order can exceed current stock; the undelivered balance "
            "can be fulfilled later in parts. 3. Discount and payment: "
            "discount is optional and can be a fixed amount or percentage; "
            "it cannot exceed the subtotal or 100 percent. Turn on Record "
            "payment now only if recording payment, then add one or more "
            "positive payment amounts and select Cash, M-Pesa, Bank, Card, "
            "or Other. References and a follow-up reminder for a balance "
            "are optional. Review any customer credit shown for "
            "overpayment. 4. Review the customer/walk-in, date/time, items, "
            "quantities, prices, discount, payments, total and balance, "
            "then select Record sale order. If payment exceeds the total, "
            "confirm that the difference should be customer credit. The "
            "sale is not recorded until the final action. After saving, "
            "open the sale details and use Record delivery to record "
            "delivered birds; the sale can remain partly or wholly "
            "undelivered."
        ),
    },
    "chicken_movement": {
        "label": "Move chickens between blocks",
        "href": "/chicken-movement",
        "steps": (
            "Entry routes: from the Chickens tab, choose Move birds when "
            "there is stock in multiple blocks and a destination has "
            "available capacity; or open an occupied block and choose Move chickens (this "
            "preselects it as the source). On the movement screen choose "
            "the source block, batches and quantities, destination block "
            "and date; add an optional reason/notes, review the move, then "
            "confirm. The destination must have capacity and source stock "
            "must still be available. If already on the movement form, "
            "guide the current stage."
        ),
        "detailed_steps": (
            "1. Source: choose the block the birds are currently in; when "
            "the user opened the form from a block, that block may already "
            "be selected. 2. Batches: choose one or more batches in that "
            "source block, then enter a whole-number quantity of at least "
            "one per batch, no greater than the available stock. 3. "
            "Destination: choose a different block. The combined quantity "
            "must fit its remaining maximum capacity. Choose a movement "
            "date that is today or earlier and not before a selected "
            "batch's hatch date. A reason and additional notes are "
            "optional. 4. Select Review movement; check the source, "
            "destination, batches, quantities, date and optional notes. "
            "Select Confirm move and accept the confirmation dialog only "
            "if the summary is correct. The app refreshes stock and "
            "capacity before confirming, so if either changed, update the "
            "selection and review again."
        ),
    },
    "contacts": {
        "label": "Contacts",
        "href": "/contacts",
        "steps": (
            "Open Contacts to search existing customers and suppliers or "
            "add a new contact. Open a contact to review their account "
            "activity and balance."
        ),
    },
    "create_contact": {
        "label": "Add a contact",
        "href": "/contacts/new",
        "steps": (
            "Enter the person's or business's name and choose the roles "
            "they have, such as customer or supplier. Add contact details "
            "if available and save; then select the contact when recording "
            "their sale, purchase, or payment."
        ),
    },
    "settlements": {
        "label": "Accounts and settlements",
        "href": "/sales",
        "steps": (
            "Open Sales and find the sale or contact account with the "
            "outstanding balance. Open it, choose the settlement action, "
            "enter the amount and payment method, review the direction "
            "(who is paying whom), then confirm. The ledger will reflect "
            "the settlement."
        ),
    },
    "sale_adjustments": {
        "label": "Sale returns and refunds",
        "href": "/sales",
        "steps": (
            "Open Sales, find the relevant sale, and open its details. "
            "Use the sale's return/refund actions to record returned items "
            "or money refunded against that sale; these are distinct from "
            "a payment settlement. Review the sale balance and linked "
            "records afterward."
        ),
        "detailed_steps": (
            "First identify the exact sale and review its items, payments, "
            "existing returns, refunds, and balance. Record a return when "
            "items were physically returned; record a refund when money "
            "was returned. Do not treat an outstanding balance settlement "
            "as a refund. Check quantities, amount, date, and any reason "
            "shown by the form before confirming. The change remains "
            "linked to the original sale."
        ),
    },
    "purchase_adjustments": {
        "label": "Purchase returns, refunds, and replacements",
        "href": "/purchases",
        "steps": (
            "Open Purchases and select the original supplier purchase. "
            "Its detail page is the place to review or record a purchase "
            "return, supplier refund, or replacement. These are different "
            "from paying or settling the supplier balance; keep the action "
            "linked to the correct purchase."
        ),
        "detailed_steps": (
            "Open the exact purchase and review its items, payments, "
            "receipts/arrivals, returns, replacements, supplier refunds, "
            "and balance. Choose a purchase return for goods sent back, a "
            "supplier refund for money received back, or a replacement for "
            "replacement goods. Use a settlement only to record a payment "
            "toward the supplier account. Before confirming, check the "
            "purchase and affected quantities or amount, date, method, and "
            "reason shown by the selected form."
        ),
    },
    "inventory": {
        "label": "Inventory",
        "href": "/inventory",
        "steps": (
            "Open More, then Inventory. Search or filter for a product to "
            "review its available quantity and unit. Use Purchase to add "
            "stock or Consumption to record stock used. Use Products to "
            "change the catalog and Units to review the measures used by "
            "products."
        ),
    },
    "inventory_purchase": {
        "label": "Record an inventory purchase",
        "href": "/inventory/purchase",
        "steps": (
            "Choose the products and units, enter quantities and unit "
            "prices, select or add the supplier, then enter the purchase "
            "date. Record any amount paid and payment method, review the "
            "total and balance, then select Save purchase."
        ),
    },
    "opening_stock": {
        "label": "Set opening stock",
        "href": "/inventory/opening-stock",
        "steps": (
            "Choose whether you are setting up chickens or eggs, add the "
            "products and opening quantities by block, and enter unit "
            "costs when known. Review the quantities and costs carefully "
            "before saving because this establishes the starting stock "
            "used by later inventory and costing reports."
        ),
    },
    "feed_consumption": {
        "label": "Record feed consumption",
        "href": "/inventory/consumption",
        "steps": (
            "Choose the feed product and unit, enter the quantity used, "
            "and allocate it to the relevant block or flock. Set the use "
            "date, add an optional note, review the allocations, then "
            "select Record consumption."
        ),
        "detailed_steps": (
            "Product consumption records use of an inventory product "
            "(such as feed or medication), reducing its stock and "
            "attributing the use to the selected block, flock, or batches "
            "where the form supports it. It is not for selling stock, "
            "recording egg collection, or recording chicken losses. Select "
            "the product and configured unit, enter a positive quantity "
            "that is in stock, allocate the amount to the applicable "
            "location, choose the date, and optionally add notes. Check "
            "the allocation totals and remaining stock before recording."
        ),
    },
    "blocks": {
        "label": "Blocks",
        "href": "/(tabs)/blocks",
        "steps": (
            "Open Blocks to review housing capacity and assigned birds. "
            "A block is a housing/location record used to assign birds, "
            "attribute feed or product consumption, and identify egg "
            "collection sources. Choose a block to inspect its occupancy "
            "or details. Before moving birds, check both the source and "
            "destination counts and capacities."
        ),
    },
    "create_block": {
        "label": "Add a block",
        "href": "/(tabs)/blocks/new",
        "steps": (
            "Enter a unique block name and its capacity details, then "
            "review and save. Use the block afterward when assigning "
            "birds, recording egg collections, or allocating feed use."
        ),
    },
    "flock": {
        "label": "Flock",
        "href": "/(tabs)/flock",
        "steps": (
            "Open Chickens to review birds by block or batch, recent flock "
            "activity, and pending outgoing deliveries. Use the available "
            "actions there to record a movement or loss, or open a sale "
            "when you are ready to sell."
        ),
    },
    "chicken_purchase": {
        "label": "Buy chickens",
        "href": "/chicken-purchase",
        "steps": (
            "Entry routes: from Home, tap the Chickens tab and choose "
            "Purchase birds; from the Chickens tab, choose Purchase birds; "
            "from More > Purchases, choose Buy chickens; from More > "
            "Inventory, find Chickens and choose Purchase; from a chicken "
            "product's inventory page, choose Record chicken purchase. "
            "When there are no active chickens, the chicken-loss empty "
            "state also offers Record a purchase. "
            "On the form, enter the purchase date, optionally choose or add "
            "a supplier, add one or more chicken product/type/unit lines "
            "with whole-number quantities and prices, optionally record "
            "payment, then review the total and balance before Record "
            "purchase. Batch and housing are not part of this form: after "
            "saving, use the separate arrival receipt to record received "
            "quantities and allocate birds to batches and blocks. If the "
            "user is already on the purchase form, say so and guide the "
            "current step instead of sending them back to the form."
        ),
        "detailed_steps": (
            "1. Purchase details: choose a purchase date that is not in "
            "the future. Supplier is optional; select an existing supplier "
            "or add one (only the name is required; phone and email are "
            "optional). Purchase notes are optional. 2. Purchase items: "
            "add at least one active chicken product, choose its chicken "
            "type (Layers, Broiler, Kienyeji, Breeders, or Other), select "
            "one or more units supported by that product, then enter a "
            "whole-number quantity above zero and a price per unit with up "
            "to two decimal places (enter 0 for free chickens). Add another "
            "purchase line for a different product; item notes and a "
            "discount are optional. 3. Payment: leave Record payment now "
            "off if no payment is being made yet. If paying, enter the "
            "amount or choose Fully paid, select Cash, M-Pesa, Bank "
            "transfer, Card, or Other, and add an optional reference. "
            "Additional payments can be recorded separately; M-Pesa "
            "payments also have a date/time and Android may offer SMS "
            "payment import. 4. Review purchase: check the supplier, date, "
            "items, quantities, prices, discount, total, payments, and "
            "remaining balance or supplier credit. Review any settlement "
            "reminder if configured, then select Record purchase. The "
            "purchase is not recorded until the user confirms this final "
            "button. 5. Receiving chickens is a separate action after "
            "purchase: choose the arrival date, enter the quantity received "
            "for each purchase line, choose an existing batch or create a "
            "batch (including its name and age when applicable), allocate "
            "received birds across housing blocks, check allocations equal "
            "the received quantity, add optional arrival notes, then select "
            "Record arrival. This records incoming stock, not an outgoing "
            "customer delivery."
        ),
    },
    "record_chicken_loss": {
        "label": "Record chicken losses",
        "href": "/chicken-loss",
        "steps": (
            "Entry routes: from Home, choose Log loss; or, when flock stock "
            "exists, from the Chickens tab choose Record loss. Select the loss date and "
            "affected block/batch stock, then choose Review losses. On "
            "the review screen set each quantity and reason, optionally "
            "add notes, check the total and entries, then select Record "
            "losses. Losses reduce flock inventory, so check the affected "
            "block and batch carefully. If already on either loss screen, "
            "guide the current stage."
        ),
        "detailed_steps": (
            "1. Choose the date the loss happened. 2. Find the affected "
            "block or batch using search, expand the correct block, and "
            "select each affected batch. The quantity starts at one; use "
            "the controls to enter the number lost, never more than the "
            "available stock in that batch and block. 3. Select Review "
            "losses. For every entry check the block, batch and quantity, "
            "set a reason (Disease, Natural death, Predator, Injury, "
            "Accident, Culling, Missing, or Other), and add an optional "
            "note. Remove any incorrect entry and recheck the date and "
            "total. 4. Select Record losses only after reviewing; this "
            "immediately removes those birds from flock inventory. If the "
            "reason concerns possible disease, choose the closest observed "
            "recording reason and consult a qualified veterinarian for "
            "diagnosis or treatment."
        ),
    },
    "eggs": {
        "label": "Eggs",
        "href": "/(tabs)/eggs",
        "steps": (
            "Open Eggs to review collected, available-to-sell and on-hand "
            "stock by product, plus recent activity. With no egg products, "
            "the primary action is Add egg product. Otherwise the primary "
            "action is Sell eggs when there is sellable stock, or Collect "
            "eggs when there is not; the secondary action is Collect eggs "
            "or View products, respectively. Record loss appears only "
            "when a product has on-hand stock, and Manage opens Products. "
            "More > Egg collection, Home > Collect eggs, Inventory > "
            "Record egg collection, product inventory > Record egg "
            "collection, and the no-stock egg-sale prompt also open "
            "collection. Sales > New sale > Sell eggs opens egg sale. "
            "Egg collection requires an active egg product with units and "
            "an active source block; use Add egg product if setup is "
            "needed."
        ),
    },
    "egg_collection": {
        "label": "Record egg collection",
        "href": "/egg-collection",
        "steps": (
            "Entry routes: Eggs > Collect eggs (when there is no sellable "
            "stock, or from its secondary action), Home > Collect eggs, "
            "More > Egg collection, Inventory > Record egg collection, "
            "product inventory > Record egg collection, or the prompt on "
            "Egg sale when no eggs are available to sell. Select an active "
            "egg product and one or more source blocks; enter a quantity "
            "for each configured unit in each block, set collection date "
            "and time, and optionally add notes. Review the block entries "
            "and combined total, then select Record collection. If already "
            "on the form, guide the current stage."
        ),
        "detailed_steps": (
            "1. Choose the active egg product; its registered units (for "
            "example trays or pieces) are the units you can enter. 2. "
            "Select every active source block included in this collection. "
            "3. For each selected block, enter at least one quantity "
            "greater than zero in a configured unit. You can add different "
            "units in the same block, but each unit can be used only once "
            "per block. Quantities allow up to three decimal places. 4. "
            "Choose the collection date and time; neither may be in the "
            "future. Notes are optional. Select Review collection, then "
            "check each block, unit, quantity, date/time and combined "
            "base-unit total. Select Record collection only when the "
            "review is correct. The app records collection stock for the "
            "egg product; it does not create or assign chicken batches."
        ),
    },
    "egg_loss": {
        "label": "Record egg loss",
        "href": "/egg-loss",
        "steps": (
            "Entry route: Eggs > Record loss; this action appears when at "
            "least one egg product has on-hand stock. Choose the product, "
            "enter the quantity and unit, choose a reason and loss date, "
            "and optionally add notes. Review the available-after-loss "
            "summary before selecting Record loss. Egg loss is recorded "
            "against combined farm stock for the product, not a particular "
            "block. If already on the form, guide the current stage."
        ),
        "detailed_steps": (
            "1. Choose the egg product with available collected stock. 2. "
            "Enter one or more loss quantities using configured units; "
            "each unit can be used once, quantities must be positive with "
            "up to three decimal places, and their combined base-unit "
            "equivalent cannot exceed available stock. 3. Choose the main "
            "reason: Broken, Spoiled, Contaminated, Damaged, Discarded, "
            "or Other. 4. Set the loss date (not in the future) and add "
            "optional notes. Select Review loss, then check the product, "
            "quantities, reason, date and remaining available stock. "
            "Select Record loss only after reviewing. The loss is deducted "
            "from combined farm stock for that product; the record is not "
            "attributed to a block."
        ),
    },
    "egg_sale": {
        "label": "Record egg sale",
        "href": "/egg-sale",
        "steps": (
            "Entry routes: Eggs > Sell eggs when sellable stock is "
            "available, or Sales > New sale > Sell eggs. Select egg "
            "products and sale units, enter quantities and prices, then "
            "set the sale date and optionally choose a customer. Record "
            "payment now or leave the balance due; review and confirm the "
            "sale. A named customer is required to track a balance due or "
            "customer credit. If already on the form, guide the current "
            "stage."
        ),
        "detailed_steps": (
            "The form has three setup steps and a final review. 1. Items "
            "and price: select one or more egg products, add sale lines "
            "using configured units, enter positive quantities (up to "
            "three decimal places) and a positive unit price (up to two "
            "decimal places). Check that requested quantities do not "
            "exceed available stock; reserved order quantities are not "
            "available to sell. 2. Customer and date: choose a valid sale "
            "date; selecting a customer is optional for a walk-in sale, "
            "but required if a balance due or overpayment credit will be "
            "tracked on account. 3. Payment: choose Received to record "
            "one or more payments, or Not yet to leave the full balance "
            "due. Enter valid positive payment amounts and select the "
            "method; M-Pesa references and a follow-up reminder are "
            "optional where applicable. Review the items, quantities, "
            "prices, customer, date, total, payments and balance/credit. "
            "Use the final Confirm sale action (its label reflects paid, "
            "balance-due or customer-credit status) only when correct. "
            "After saving, open the sale from Sales to review its balance."
        ),
    },
    "deliveries": {
        "label": "Pending deliveries",
        "href": "/sales",
        "steps": (
            "Open Sales and review pending deliveries to see which sold "
            "items still need to go to customers. Open a sale to inspect "
            "its remaining quantities and continue delivery tracking."
        ),
    },
    "receipts": {
        "label": "Receipts",
        "href": "/receipts",
        "steps": (
            "Open Receipts to search sales, purchases, and payment "
            "receipts. Filter by transaction or receipt type, select the "
            "matching record, then open or share its receipt."
        ),
    },
    "reports": {
        "label": "Reports",
        "href": "/reports",
        "steps": (
            "Open Reports and choose the analysis that matches the "
            "question: Sales for recorded sales and product performance; "
            "Expenses for costs and categories; Eggs for production; "
            "Flock for bird counts; Inventory for quantities; or "
            "Profitability for income, costs and net profit. Set the "
            "period when prompted and check any completeness or costing "
            "notes before drawing conclusions."
        ),
        "detailed_steps": (
            "Use Sales for transactions, customers, units sold, sales "
            "totals and product rankings. Use Expenses for recorded costs "
            "by category and payment status. Use Eggs for production, "
            "losses and related egg activity; use Flock for bird counts "
            "and flock activity. Use Inventory for current quantities, "
            "not historical stock. Use Profitability to compare recorded "
            "income and costs and assess net profit; inspect completeness "
            "warnings because incomplete costing or missing records can "
            "make profit indeterminate. Use Stock costing for the value "
            "of stock on a specific as-of date. Reports describe recorded "
            "data and do not change transactions."
        ),
    },
    "stock_costing": {
        "label": "Stock costing",
        "href": "/reports/stock-costing",
        "steps": (
            "Open Stock costing and choose an as-of date. Review the "
            "valued stock and any unvalued quantities; an unvalued item "
            "means the report may not have enough cost history to give a "
            "complete stock value."
        ),
    },
    "expenses": {
        "label": "Expenses",
        "href": "/expenses",
        "steps": (
            "Open More > Expenses to review and filter recorded costs or "
            "add an expense. Expenses track farm operating costs with a "
            "category, amount and date; optional details can include a "
            "contact, block, receipt reference, notes and payment. "
            "Use Expenses reports for category totals and payment status; "
            "use Profitability when the question is overall income, costs "
            "or net profit."
        ),
        "detailed_steps": (
            "Choose a meaningful expense category, name/description, "
            "amount and expense date. A contact, block, receipt reference "
            "and notes are optional when relevant. If recording payment "
            "now, enter the amount and payment method; otherwise the "
            "remaining balance stays due. Review amount paid and balance "
            "before saving. Categories classify costs for filtering and "
            "expense reporting; changing a category does not itself record "
            "an expense or payment."
        ),
    },
    "expense_categories": {
        "label": "Expense categories",
        "href": "/settings/expense-categories",
        "steps": (
            "Open More, Settings, then Expense categories to organize the "
            "types of costs available when recording farm expenses. Use "
            "categories to classify and compare costs in the Expenses "
            "report; they are not product or unit categories."
        ),
    },
    "purchases": {
        "label": "Purchases",
        "href": "/purchases",
        "steps": (
            "Open Purchases to review supplier transactions. Select a "
            "purchase to see its items, payments, receipts, and current "
            "balance; use the relevant receive, return, or settlement "
            "action when available."
        ),
        "detailed_steps": (
            "Purchases includes supplier transactions for chickens and "
            "inventory products. Open a purchase to trace its items, "
            "payments, receipts/arrivals, returns, replacements, supplier "
            "refunds, settlements and balance. Receiving stock is separate "
            "from recording the purchase: a chicken arrival allocates "
            "received birds to batches and blocks. Use a purchase return "
            "for goods sent back, a supplier refund for money returned, a "
            "replacement for goods supplied instead, and a settlement for "
            "a payment toward the supplier account."
        ),
    },
    "products": {
        "label": "Products",
        "href": "/products",
        "steps": (
            "Open More, then Products to search the farm's product "
            "catalog. Open a product to review or edit its details and "
            "inventory; use Add product to create a product before "
            "recording it in a sale or purchase. Products define the "
            "catalog item and its type, configured units, and whether it "
            "can be sold or purchased."
        ),
        "detailed_steps": (
            "Use Products to manage the farm's catalog, not to record "
            "stock movements. Choose a product type based on its role "
            "(eggs, chickens, feed, medication, equipment or other), "
            "configure the units used for that product, and enable sale "
            "or purchase eligibility as appropriate. For a new item, add "
            "the product first, then set opening stock or record a "
            "purchase/collection through its separate workflow."
        ),
    },
    "create_product": {
        "label": "Add a product",
        "href": "/products/new",
        "steps": (
            "Enter the product name and type, configure its units and "
            "whether it can be sold or purchased, then review and save. "
            "Afterward, add starting quantities if needed before using it "
            "in a transaction."
        ),
        "detailed_steps": (
            "Select the product type that matches how the farm uses the "
            "item, set an unambiguous name, attach configured units, and "
            "enable sale or purchase only when that workflow applies. "
            "Units define how quantities are entered and converted to "
            "the product's base unit. Creating a product does not create "
            "stock; use opening stock or the appropriate purchase or egg "
            "collection form afterward."
        ),
    },
    "units": {
        "label": "Units and conversions",
        "href": "/units",
        "steps": (
            "Open More > Units to add or review measures used by "
            "products. A unit is a name and abbreviation; product unit "
            "setup identifies its base unit and conversion factor. Those "
            "conversions affect recorded quantities, stock and reports. "
            "There is no separate unit-category feature; expense "
            "categories are a different concept."
        ),
        "detailed_steps": (
            "Units are measures such as pieces, trays, kilograms or bags. "
            "Products configure which units they accept and how each "
            "converts to that product's base unit; the base unit is the "
            "canonical quantity for stock calculations. For example, "
            "when a product uses a tray containing a configured number "
            "of pieces, the conversion determines the stock equivalent. "
            "Use the same correct conversion consistently in purchases, "
            "sales, consumption and stock records. The app has a shared "
            "unit library but no separate unit-category entity. Expense "
            "categories classify costs and do not group units."
        ),
    },
    "activities": {
        "label": "Farm activity",
        "href": "/activities",
        "steps": (
            "Open Activities to review a timeline across the farm. Search "
            "or filter by category and date to trace sales, purchases, "
            "flock, egg, inventory, and expense actions."
        ),
    },
    "notifications": {
        "label": "Notifications",
        "href": "/notifications",
        "steps": (
            "Open Notifications to review updates and alerts. Select an "
            "item to follow it into the related farm record when a link is "
            "available."
        ),
    },
    "reminders": {
        "label": "Reminders",
        "href": "/reminders",
        "steps": (
            "Open Reminders to review pending, completed, or cancelled "
            "tasks. Select a reminder to view its details and update its "
            "status."
        ),
    },
}
