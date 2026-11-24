import json
import re
from datetime import date, datetime, time, timezone
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr, ValidationError

from app.api.v1.endpoints.ai_assistant import router
from app.core.config import settings
from app.core.exception_handlers import register_exception_handlers
from app.core.exceptions import AppError
from app.dependencies.auth import get_current_user, require_super_admin
from app.dependencies.farm import get_owned_farm
from app.models.farm import Farm
from app.presentation.dependencies.services import get_farm_assistant_service
from app.schemas.account_ledger import (
    AccountLedgerAccount,
    AccountLedgerComponent,
    AccountLedgerEvent,
    AccountLedgerResponse,
)
from app.schemas.enums import ProductType
from app.schemas.ai_assistant import (
    AssistantChatRequest,
    AssistantConversationRenameRequest,
    ProfitabilityQuestionRequest,
)
from app.schemas.inventory import InventoryProductBalance
from app.schemas.profitability_report import ProfitabilityReportResponse
from app.schemas.sales_report import SalesReportFilters
from app.services.ai_assistant_service import (
    CHAT_TOOLS,
    DateRangeToolArguments,
    ExpenseHistoryToolArguments,
    FarmAssistantService,
    FarmOperationsSummaryToolArguments,
    GeminiClient,
    SalesReportToolArguments,
    build_system_instruction,
    resolve_sales_report_period,
    resolve_tool_date_range,
)
from app.services.ai_provider_errors import AIProviderFailure
from app.services.assistant_route_catalog import (
    APP_ROUTE_CATALOG,
    describe_app_route,
    resolve_app_route,
)


def test_app_navigation_destinations_cover_every_tool_option():
    navigation_tool = next(
        tool for tool in CHAT_TOOLS if tool["name"] == "get_app_navigation"
    )
    destinations = navigation_tool["parameters"]["properties"]["destination"][
        "enum"
    ]

    assert set(destinations) == set(FarmAssistantService.APP_DESTINATIONS)
    assert all(
        destination["href"].startswith("/")
        and destination["steps"].strip()
        and destination["label"].strip()
        for destination in FarmAssistantService.APP_DESTINATIONS.values()
    )


def test_history_and_expense_tools_are_registered():
    registered_tools = {tool["name"] for tool in CHAT_TOOLS}

    assert {
        "get_purchase_history",
        "get_sales_history",
        "get_transaction_details",
        "get_current_farm",
        "get_expense_summary",
        "get_expense_history",
    }.issubset(registered_tools)


def test_route_catalog_covers_every_mobile_screen_route():
    app_root = Path(__file__).resolve().parents[2] / "mobile" / "src" / "app"
    mobile_route_sources: dict[str, set[str]] = {}
    for file_path in app_root.rglob("*.tsx"):
        relative = file_path.relative_to(app_root).with_suffix("")
        parts = list(relative.parts)
        if parts[-1] == "_layout":
            continue
        if parts[-1] == "index":
            parts.pop()
        parts = [part for part in parts if not (part.startswith("(") and part.endswith(")"))]
        parts = [
            f":{part[1:-1]}" if part.startswith("[") and part.endswith("]") else part
            for part in parts
        ]
        route_path = "/" + "/".join(parts) if parts else "/"
        mobile_route_sources.setdefault(route_path, set()).add(relative.as_posix())

    catalog_routes = {route.path for route in APP_ROUTE_CATALOG}

    assert catalog_routes == set(mobile_route_sources)
    assert len(APP_ROUTE_CATALOG) == len(catalog_routes)
    assert mobile_route_sources["/"] == {"index", "(tabs)/index"}
    assert all(
        len(sources) == 1
        for route_path, sources in mobile_route_sources.items()
        if route_path != "/"
    )
    assert all(
        route.label.strip() and route.purpose.strip() and route.entry_points
        for route in APP_ROUTE_CATALOG
    )
    assert all(
        entry_point.strip() and len(entry_point) > 1
        for route in APP_ROUTE_CATALOG
        for entry_point in route.entry_points
    )


def test_mobile_navigation_targets_resolve_in_route_catalog():
    mobile_src = Path(__file__).resolve().parents[2] / "mobile" / "src"
    target_pattern = re.compile(
        r"""(?:router\.(?:push|replace|navigate)\s*\(\s*|"""
        r"""\b(?:pathname|href|route)\s*[:=]\s*)["'`]([^"'`]+)["'`]"""
    )
    targets = []

    for file_path in mobile_src.rglob("*"):
        if file_path.suffix not in {".ts", ".tsx"}:
            continue
        source = file_path.read_text(encoding="utf-8")
        for match in target_pattern.finditer(source):
            target = match.group(1).split("?", 1)[0].split("#", 1)[0]
            target = re.sub(r"\$\{[^}]+\}", ":dynamic", target)
            target = re.sub(r"\[([^]/]+)\]", r":\1", target)
            if target.startswith("/"):
                targets.append((file_path, target))

    assert targets
    unresolved = [
        f"{file_path.relative_to(mobile_src)}: {target}"
        for file_path, target in targets
        if resolve_app_route(target) is None
    ]

    assert not unresolved, "\n".join(unresolved)


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("/", "/"),
        ("/(tabs)/flock", "/flock"),
        ("/(tabs)/blocks", "/blocks"),
        ("/(auth)/login", "/login"),
        ("/blocks/4c021e6d-28e1-4cca-9324-9a1560ce5191", "/blocks/:blockId"),
        (
            "/transactions/4c021e6d-28e1-4cca-9324-9a1560ce5191/returns",
            "/transactions/:transactionId/returns",
        ),
        (
            "/products/4c021e6d-28e1-4cca-9324-9a1560ce5191/inventory",
            "/products/:productId/inventory",
        ),
    ],
)
def test_route_catalog_resolves_route_groups_and_dynamic_segments(path, expected):
    route = resolve_app_route(path)

    assert route is not None
    assert route.path == expected


@pytest.mark.asyncio
async def test_route_catalog_tool_returns_purpose_and_known_entry_points():
    result, scopes = await execute_chat_tool(
        tool_name="get_app_route_catalog",
        arguments={},
        farm=SimpleNamespace(id=uuid4()),
        question="What routes are available?",
    )

    assert scopes == []
    assert len(result["routes"]) == len(APP_ROUTE_CATALOG)
    units = next(route for route in result["routes"] if route["path"] == "/units")
    assert units["label"] == "Units and conversions"
    assert "Configure measurement units" in units["purpose"]
    assert "Product form unit links" in units["entry_points"]


def test_assistant_conversation_title_is_trimmed_and_rejects_blank_values():
    assert AssistantConversationRenameRequest(title="  Flock review  ").title == (
        "Flock review"
    )
    with pytest.raises(ValidationError):
        AssistantConversationRenameRequest(title="   ")


def test_assistant_chat_source_route_is_limited_to_internal_paths():
    assert AssistantChatRequest(
        question="Where do I buy chickens?",
        source_route="/(tabs)/flock",
    ).source_route == "/(tabs)/flock"
    with pytest.raises(ValidationError):
        AssistantChatRequest(
            question="Where do I buy chickens?",
            source_route="https://example.com",
        )


@pytest.mark.parametrize(
    ("source_route", "expected_context"),
    [
        ("/flock", "Chickens tab (Flock screen)"),
        ("/(tabs)/flock", "Chickens tab (Flock screen)"),
        ("/account", "More tab"),
        ("/(tabs)/account", "More tab"),
        ("/units", "Units and conversions"),
        ("/blocks", "Blocks"),
        ("/(tabs)/blocks", "Blocks"),
        ("/sales", "Sales tab"),
        ("/(tabs)/sales", "Sales tab"),
    ],
)
def test_source_route_context_names_the_current_tab_or_nested_page(
    source_route,
    expected_context,
):
    contextual_question = FarmAssistantService._add_source_route_context(
        "What tab am I in?",
        source_route,
    )
    route = resolve_app_route(source_route)
    assert route is not None

    assert contextual_question.startswith(
        f"[FarmTrack app context: Route pattern: {route.path}. "
    )
    assert expected_context in contextual_question


def create_profitability_report(**overrides):
    values = {
        "farm_id": uuid4(),
        "from_date": date(2026, 1, 1),
        "to_date": date(2026, 1, 31),
        "complete": True,
        "incompleteness_reasons": [],
        "gross_sales": Decimal("1000.00"),
        "sales_credits": Decimal("50.00"),
        "net_revenue": Decimal("950.00"),
        "cost_of_goods_sold": Decimal("400.00"),
        "product_consumption_cost": Decimal("20.00"),
        "egg_production_cost_allocated": Decimal("30.00"),
        "egg_production_zero_cost_confirmed": False,
        "egg_production_zero_cost_confirmation_available": False,
        "unallocated_consumption_expense": Decimal("0"),
        "operating_expenses": Decimal("100.00"),
        "inventory_losses": Decimal("10.00"),
        "net_profit": Decimal("440.00"),
        "closing_stock_as_of": date(2026, 1, 31),
        "closing_stock": [],
        "product_performance": [],
        "egg_stock_reconciliation": [],
        "reserved_egg_sales": [],
        "unvalued_period_movement_count": 0,
        "missing_inventory_record_count": 0,
        "closing_stock_valued_cost": Decimal("200.00"),
        "closing_stock_unvalued_quantity": Decimal("0"),
        "untracked_chicken_quantity": Decimal("0"),
        "untracked_egg_quantity": Decimal("0"),
        "overrepresented_egg_quantity": Decimal("0"),
        "customer_cash_refunds_excluded": Decimal("0"),
        "supplier_cash_refunds_excluded": Decimal("0"),
        "supplier_return_credits_excluded": Decimal("0"),
    }
    values.update(overrides)
    return ProfitabilityReportResponse(**values)


async def execute_chat_tool(
    *,
    tool_name: str,
    arguments: dict[str, Any],
    farm: Any,
    question: str,
    **service_dependencies: Any,
) -> tuple[dict[str, Any], list[str]]:
    class FakeConversationRepository:
        async def create(self, **kwargs: Any):
            return SimpleNamespace(id=uuid4(), title=kwargs["title"])

        async def add_exchange(self, **kwargs: Any) -> None:
            pass

    class FakeUnitOfWork:
        async def commit(self) -> None:
            pass

    class FakeLedgerService:
        async def get_ledger(self, *args: Any, **kwargs: Any):
            raise AssertionError("This tool does not read the account ledger.")

    class FakeProvider:
        tool_result: dict[str, Any]

        async def answer(
            self,
            *,
            question: str,
            report_context: dict[str, Any],
            conversation_history: list[dict[str, str]] | None = None,
        ) -> str:
            raise AssertionError("The legacy answer flow is not used.")

        async def answer_with_tools(
            self,
            *,
            question: str,
            conversation_history: list[dict[str, str]],
            execute_tool: Any,
        ) -> tuple[str, bool]:
            self.tool_result = await execute_tool(tool_name, arguments)
            return "Tool result received.", False

    provider = FakeProvider()
    assistant = FarmAssistantService(
        cast(Any, SimpleNamespace()),
        account_ledger_service=FakeLedgerService(),
        provider_manager=provider,
        conversation_repository=cast(Any, FakeConversationRepository()),
        unit_of_work=cast(Any, FakeUnitOfWork()),
        **service_dependencies,
    )
    result = await assistant.answer_chat_question(
        farm_id=farm.id,
        user_id=uuid4(),
        question=question,
        farm=farm,
    )
    return provider.tool_result, result[3]


@pytest.mark.asyncio
async def test_purchase_and_sales_history_tools_return_paginated_safe_records():
    farm_id = uuid4()
    farm = SimpleNamespace(id=farm_id)
    purchase_payment = SimpleNamespace(
        payment_date=date(2026, 1, 5),
        amount=Decimal("10"),
        payment_method=SimpleNamespace(value="cash"),
        reference_number="private purchase reference",
    )
    purchase = SimpleNamespace(
        id=uuid4(),
        status=SimpleNamespace(value="completed"),
        transaction_date=date(2026, 1, 5),
        contact_name="Supplier",
        product_names=["Layer feed"],
        line_items=[
            SimpleNamespace(
                product_name="Eggs",
                quantity=Decimal("100"),
                unit_name="piece",
            )
        ],
        transaction_total=Decimal("20"),
        payments=[purchase_payment],
        reference_number="private transaction reference",
    )

    class FakePurchaseHistoryService:
        async def get_history(
            self,
            received_farm_id,
            filters,
            *,
            offset: int,
            limit: int,
        ):
            assert received_farm_id == farm_id
            assert filters.transaction_type == "purchase"
            assert filters.receipt_kind == "transaction"
            assert filters.status == "all"
            assert filters.search == "feed"
            assert filters.from_date is None
            assert filters.to_date is None
            assert (offset, limit) == (10, 5)
            return SimpleNamespace(
                items=[purchase],
                total_count=12,
                completed_total=Decimal("20"),
                offset=offset,
                limit=limit,
            )

    purchase_result, purchase_scopes = await execute_chat_tool(
        tool_name="get_purchase_history",
        arguments={"search": "feed", "offset": 10, "limit": 5},
        farm=farm,
        question="Find a purchase of feed",
        purchase_history_service=FakePurchaseHistoryService(),
    )
    assert purchase_scopes == ["purchase_history"]
    assert purchase_result["has_more"]
    assert purchase_result["purchases"][0]["supplier_name"] == "Supplier"
    assert purchase_result["purchases"][0]["payments"][0]["amount"] == "10"
    assert purchase_result["purchases"][0]["line_items"] == [
        {"product_name": "Eggs", "quantity": "100", "unit": "piece"}
    ]
    assert purchase_result["purchases"][0]["href"] == f"/purchases/{purchase.id}"
    assert "private transaction reference" not in json.dumps(purchase_result)
    assert "private purchase reference" not in json.dumps(purchase_result)

    sale = SimpleNamespace(
        id=uuid4(),
        transaction_date=date(2026, 1, 6),
        transaction_time=time(12, 0),
        customer_name="Customer",
        products_sold=[
            SimpleNamespace(
                name="Eggs",
                quantity=Decimal("2"),
                unit_name="tray",
            )
        ],
        transaction_total=Decimal("30"),
        amount_paid=Decimal("20"),
        balance_due=Decimal("10"),
        reference_number="private sale reference",
    )

    class FakeSalesReportService:
        async def get_report(
            self,
            received_farm_id,
            filters,
            *,
            offset: int,
            limit: int,
        ):
            assert received_farm_id == farm_id
            assert filters.status == "completed"
            assert (offset, limit) == (2, 4)
            return SimpleNamespace(
                items=[sale],
                total_count=8,
                offset=offset,
                limit=limit,
            )

    sales_result, sales_scopes = await execute_chat_tool(
        tool_name="get_sales_history",
        arguments={"offset": 2, "limit": 4},
        farm=farm,
        question="Find my recent sales",
        sales_report_service=FakeSalesReportService(),
    )
    assert sales_scopes == ["sales_history"]
    assert sales_result["has_more"]
    assert sales_result["sales"][0]["products"][0]["name"] == "Eggs"
    assert "private sale reference" not in json.dumps(sales_result)


@pytest.mark.asyncio
async def test_expense_tools_use_category_filters_and_omit_private_fields():
    farm = SimpleNamespace(id=uuid4(), name="Green Valley Farm")
    category = SimpleNamespace(
        key="feed",
        name="Feed",
        expense_count=2,
        total_amount=Decimal("50"),
        amount_paid=Decimal("30"),
        balance_due=Decimal("20"),
    )
    expense = SimpleNamespace(
        id=uuid4(),
        name="Layer feed",
        category_name="Feed",
        expense_date=date(2026, 1, 12),
        amount=Decimal("50"),
        amount_paid=Decimal("30"),
        balance_due=Decimal("20"),
        purchase_transaction_id=uuid4(),
        payment_status=SimpleNamespace(value="partial"),
        block_name="North",
        contact_name="Private supplier",
        receipt_reference="private receipt",
        notes="private note",
    )

    class FakeExpenseService:
        async def get_expense_summary(self, received_farm, *, from_date, to_date):
            assert received_farm is farm
            assert from_date <= to_date
            return SimpleNamespace(categories=[category])

        async def list_expenses(
            self,
            received_farm,
            *,
            category: str | None,
            from_date: date | None,
            to_date: date | None,
            search: str | None,
            payment_status: str | None,
            exclude_cancelled: bool,
            exclude_purchase_linked: bool,
            offset: int,
            limit: int,
        ):
            assert received_farm is farm
            assert category == "feed"
            assert from_date is None
            assert to_date is None
            assert search == "layer"
            assert payment_status is None
            assert exclude_cancelled
            assert not exclude_purchase_linked
            assert (offset, limit) == (3, 5)
            return SimpleNamespace(
                items=[expense],
                total_count=9,
                offset=offset,
                limit=limit,
            )

    expense_service = FakeExpenseService()
    summary, summary_scopes = await execute_chat_tool(
        tool_name="get_expense_summary",
        arguments={"category": "feed"},
        farm=farm,
        question="How much have I spent on feed this month?",
        expense_service=expense_service,
    )
    assert summary_scopes == ["expense_summary"]
    assert summary["total_amount"] == "50"
    assert summary["categories"][0]["name"] == "Feed"
    assert summary["farm_name"] == "Green Valley Farm"
    assert "cancelled records excluded" in summary["calculation_basis"]

    history, history_scopes = await execute_chat_tool(
        tool_name="get_expense_history",
        arguments={"category": "feed", "search": "layer", "offset": 3, "limit": 5},
        farm=farm,
        question="Find the feed purchase expense",
        expense_service=expense_service,
    )
    assert history_scopes == ["expense_history"]
    assert history["has_more"]
    assert history["expenses"][0]["block_name"] == "North"
    assert history["expenses"][0]["name"] == "Layer feed"
    assert history["expenses"][0]["category"] == "Feed"
    assert history["expenses"][0]["date"] == "2026-01-12"
    assert history["expenses"][0]["amount"] == "50"
    assert history["expenses"][0]["href"] == f"/expenses/{expense.id}"
    assert history["farm_name"] == "Green Valley Farm"
    assert history["record_scope"] == "active expenses"
    assert history["expenses"][0]["is_purchase_linked"]
    serialized_history = json.dumps(history)
    assert "Private supplier" not in serialized_history
    assert "private receipt" not in serialized_history
    assert "private note" not in serialized_history


@pytest.mark.asyncio
async def test_current_farm_tool_returns_the_exact_selected_farm_name():
    result, scopes = await execute_chat_tool(
        tool_name="get_current_farm",
        arguments={},
        farm=SimpleNamespace(id=uuid4(), name="Green Valley Farm"),
        question="Which farm are you reading from?",
    )

    assert result == {"farm_name": "Green Valley Farm"}
    assert scopes == ["farm_context"]


def test_assistant_only_links_to_tool_verified_destinations():
    hrefs = FarmAssistantService._collect_assistant_hrefs(
        {
            "href": "/expenses/550e8400-e29b-41d4-a716-446655440000",
            "nested": [
                {"href": "/purchases/550e8400-e29b-41d4-a716-446655440001"}
            ],
        }
    )

    answer = FarmAssistantService._remove_unverified_assistant_links(
        "See [this expense](/expenses/550e8400-e29b-41d4-a716-446655440000) "
        "and [a different record](/expenses/550e8400-e29b-41d4-a716-446655440002).",
        hrefs,
    )

    assert answer == (
        "See [this expense](/expenses/550e8400-e29b-41d4-a716-446655440000) "
        "and a different record."
    )
    assert FarmAssistantService._collect_assistant_hrefs(
        {"href": "//example.com/private"}
    ) == set()


def test_expense_detail_follow_up_reuses_the_previous_report_period():
    period = (date(2026, 11, 1), date(2026, 11, 12))

    assert FarmAssistantService._resolve_expense_history_dates(
        ExpenseHistoryToolArguments(),
        "Which expense?",
        period,
    ) == period
    assert FarmAssistantService._resolve_expense_history_dates(
        ExpenseHistoryToolArguments(),
        "Find the expense from 2026-11-13",
        period,
    ) == (
        date(2026, 11, 13),
        date(2026, 11, 13),
    )


@pytest.mark.asyncio
async def test_expense_count_question_queries_all_history():
    farm = SimpleNamespace(id=uuid4(), name="Green Valley Farm")

    class FakeExpenseService:
        async def get_expense_summary(self, received_farm, *, from_date, to_date):
            assert received_farm is farm
            assert from_date is None
            assert to_date is None
            return SimpleNamespace(
                categories=[
                    SimpleNamespace(
                        key="feed",
                        name="Feed",
                        expense_count=4,
                        total_amount=Decimal("100"),
                        amount_paid=Decimal("75"),
                        balance_due=Decimal("25"),
                    )
                ]
            )

    result, _ = await execute_chat_tool(
        tool_name="get_expense_summary",
        arguments={},
        farm=farm,
        question="How many expenses do I have?",
        expense_service=FakeExpenseService(),
    )

    assert result["period"] == {"from_date": None, "to_date": None}
    assert result["expense_count"] == 4
    assert result["total_amount"] == "100"
    assert result["record_scope"] == "active expenses"


def test_relative_assistant_periods_use_local_date_and_allow_full_ledger():
    empty_range = DateRangeToolArguments()
    today = date(2026, 11, 11)

    assert resolve_tool_date_range(
        empty_range,
        "What sale did I make yesterday?",
        default_period="recent",
        today=today,
    ) == (date(2026, 11, 10), date(2026, 11, 10))
    assert resolve_tool_date_range(
        empty_range,
        "Show sales last week",
        default_period="recent",
        today=today,
    ) == (date(2026, 11, 2), date(2026, 11, 8))
    assert resolve_tool_date_range(
        empty_range,
        "Why am I at a loss?",
        default_period="month_to_date",
        today=today,
    ) == (date(2026, 11, 1), today)
    assert resolve_tool_date_range(
        empty_range,
        "How did that supplier balance come about?",
        default_period="full_history",
        today=today,
    ) == (None, None)


def test_system_instruction_includes_current_farm_local_datetime():
    instruction = build_system_instruction()
    prefix = f"Current local date and time in {settings.timezone}: "
    timestamp = instruction.split(prefix, maxsplit=1)[1].removesuffix(".")

    parsed = datetime.fromisoformat(timestamp)
    assert parsed.tzinfo is not None
    assert parsed.date() == datetime.now(ZoneInfo(settings.timezone)).date()


def test_system_instruction_restricts_assistant_to_farmtrack_topics():
    instruction = build_system_instruction().casefold()

    assert "strictly stay within farmtrack help" in instruction
    assert "human health or medical questions" in instruction
    assert "symptoms, diagnosis, or treatment of malaria" in instruction
    assert "do not provide the requested facts" in instruction
    assert "smallest relevant read capability and scope" in instruction
    assert "do not dump available history" in instruction
    assert "recommendations unless the user asks" in instruction
    assert "give one uncompleted step at a time" in instruction
    assert "server-normalized navigation hint" in instruction


def test_sales_assistant_resolves_relative_hours_and_clock_times():
    local_timezone = ZoneInfo(settings.timezone)
    now = datetime(2026, 11, 11, 14, 47, tzinfo=local_timezone)
    empty_period = SalesReportToolArguments()

    assert resolve_sales_report_period(
        empty_period,
        "Who did I sell chicken to in the previous hour?",
        now=now,
    ) == (
        date(2026, 11, 11),
        date(2026, 11, 11),
        time(13, 47),
        time(14, 47),
    )
    assert resolve_sales_report_period(
        empty_period,
        "Who did I sell chicken to at 1pm today?",
        now=now,
    ) == (
        date(2026, 11, 11),
        date(2026, 11, 11),
        time(13, 0),
        time(14, 0),
    )
    assert resolve_sales_report_period(
        empty_period,
        "Who did I sell chicken to an hour ago?",
        now=now,
    ) == (
        date(2026, 11, 11),
        date(2026, 11, 11),
        time(13, 47),
        time(14, 47),
    )
    with pytest.raises(ValidationError):
        SalesReportToolArguments(from_time=time(13, 0))
    with pytest.raises(ValidationError):
        SalesReportFilters(
            from_time=time(13, 0),
            to_time=time(14, 0),
        )


def test_profitability_question_validates_text_and_period():
    request = ProfitabilityQuestionRequest(
        question="  Explain net profit for 2026-01-31  ",
        from_date=date(2026, 1, 1),
        to_date=date(2026, 12, 31),
    )

    assert request.question == "Explain net profit for 2026-01-31"

    with pytest.raises(ValidationError):
        ProfitabilityQuestionRequest(
            question="Explain",
            from_date=date(2025, 1, 1),
            to_date=date(2026, 1, 3),
        )
    with pytest.raises(ValidationError):
        ProfitabilityQuestionRequest(
            question=" ",
            from_date=date(2026, 1, 1),
            to_date=date(2026, 1, 1),
        )
    with pytest.raises(ValidationError):
        ProfitabilityQuestionRequest(
            question="What did jane@example.com buy?",
            from_date=date(2026, 1, 1),
            to_date=date(2026, 1, 1),
        )
    with pytest.raises(ValidationError):
        ProfitabilityQuestionRequest(
            question="What was the result for +254 712 345 678?",
            from_date=date(2026, 1, 1),
            to_date=date(2026, 1, 1),
        )
    with pytest.raises(ValidationError):
        ProfitabilityQuestionRequest.model_validate(
            {
                "question": "Explain",
                "from_date": date(2026, 1, 1),
                "to_date": date(2026, 1, 1),
                "farm_id": str(uuid4()),
            }
        )


@pytest.mark.asyncio
async def test_chat_balance_tool_sends_only_sanitized_account_summary():
    farm_id = uuid4()
    user_id = uuid4()
    contact_id = uuid4()
    safe_data: dict[str, Any] | None = None
    safe_ledger: dict[str, Any] | None = None
    safe_inventory: dict[str, Any] | None = None
    ledger_account_id = uuid4()
    private_event = AccountLedgerEvent(
        id="event-private-id",
        transaction_id=uuid4(),
        transaction_type="sale",
        contact_id=ledger_account_id,
        contact_name="Jane Doe",
        event_type="settlement",
        event_date=date(2026, 1, 31),
        reference_number="REF-PRIVATE",
        description="Private note should not reach the model",
        amount=Decimal("-25.00"),
        running_balance=Decimal("-25.00"),
        payment_reference="PAYMENT-PRIVATE",
        components=[
            AccountLedgerComponent(
                kind="cash",
                label="M-Pesa",
                amount=Decimal("25.00"),
                reference_number="COMPONENT-PRIVATE",
            )
        ],
    )
    ledger = AccountLedgerResponse(
        events=[],
        accounts=[
            AccountLedgerAccount(
                contact_id=contact_id,
                contact_name="Jane Doe jane@example.com 07123456789",
                roles=["customer"],
                balance=Decimal("-25.00"),
                last_activity=date(2026, 1, 31),
            ),
            AccountLedgerAccount(
                contact_id=ledger_account_id,
                contact_name="Jane Doe",
                roles=["customer"],
                balance=Decimal("-25.00"),
                last_activity=date(2026, 1, 31),
            ),
        ],
        opening_balance=None,
        closing_balance=None,
    )
    contact_ledger = AccountLedgerResponse(
        events=[private_event],
        accounts=ledger.accounts,
        opening_balance=Decimal("0.00"),
        closing_balance=Decimal("-25.00"),
    )

    class FakeLedgerService:
        async def get_ledger(
            self,
            farm_id: UUID,
            *,
            contact_id: UUID | None = None,
            from_date: date | None = None,
            to_date: date | None = None,
        ) -> AccountLedgerResponse:
            assert farm_id == farm_id_expected
            if contact_id is None:
                assert from_date is None
                assert to_date is None
                return ledger
            assert contact_id == ledger_account_id
            assert from_date == date(2026, 1, 1)
            assert to_date == date(2026, 1, 31)
            return contact_ledger

    class FakeInventoryService:
        async def get_balances(
            self,
            farm_id: UUID,
        ) -> list[InventoryProductBalance]:
            assert farm_id == farm_id_expected
            return [
                InventoryProductBalance(
                    product_id=uuid4(),
                    product_name="Layer Feed",
                    product_type=ProductType.FEED,
                    quantity=Decimal("12.500"),
                    unit_name="kilogram",
                    unit_abbreviation="kg",
                ),
                InventoryProductBalance(
                    product_id=uuid4(),
                    product_name="Water",
                    product_type=ProductType.OTHER,
                    quantity=Decimal("4.000"),
                    unit_name="litre",
                    unit_abbreviation="L",
                ),
            ]

    farm_id_expected = farm_id
    user_id_expected = user_id

    class FakeConversationRepository:
        conversation = SimpleNamespace(id=uuid4(), title="")

        async def create(
            self,
            *,
            farm_id: UUID,
            user_id: UUID,
            title: str,
        ) -> Any:
            assert farm_id == farm_id_expected
            assert user_id == user_id_expected
            self.conversation.title = title
            return self.conversation

        async def get_for_user(
            self,
            *,
            conversation_id: UUID,
            farm_id: UUID,
            user_id: UUID,
        ) -> Any:
            raise AssertionError("This test creates a new conversation.")

        async def list_for_user(
            self,
            *,
            farm_id: UUID,
            user_id: UUID,
            limit: int,
            offset: int,
        ) -> list[Any]:
            raise AssertionError("Conversation listing is not used in this test.")

        async def list_messages(self, conversation_id: UUID) -> list[Any]:
            raise AssertionError("Existing messages are not used in this test.")

        async def add_exchange(
            self,
            *,
            conversation: Any,
            question: str,
            answer: str,
            from_date: date | None = None,
            to_date: date | None = None,
        ) -> None:
            assert from_date == date(2026, 1, 1)
            assert to_date == date(2026, 1, 31)

        async def delete(self, conversation: Any) -> None:
            raise AssertionError("Conversation deletion is not used in this test.")

    class FakeProfitabilityService:
        async def build_report(
            self,
            farm_id: UUID,
            *,
            from_date: date,
            to_date: date,
        ) -> ProfitabilityReportResponse:
            raise AssertionError("Profitability is not used for a balance lookup.")

    class FakeUnitOfWork:
        async def commit(self) -> None:
            pass

    class FakeGeminiClient:
        async def answer(
            self,
            *,
            question: str,
            report_context: dict[str, Any],
            conversation_history: list[dict[str, str]] | None = None,
        ) -> str:
            raise AssertionError("The legacy answer flow is not used.")

        async def answer_with_tools(
            self,
            *,
            question: str,
            conversation_history: list[dict[str, str]],
            execute_tool: Any,
        ) -> tuple[str, bool]:
            nonlocal safe_data, safe_ledger, safe_inventory
            safe_data = await execute_tool("get_contact_balances", {})
            safe_ledger = await execute_tool(
                "get_contact_ledger",
                {
                    "contact_name": "Jane Doe",
                    "from_date": "2026-01-01",
                    "to_date": "2026-01-31",
                },
            )
            safe_inventory = await execute_tool(
                "get_inventory_balances",
                {"product_name": "Layer Feed"},
            )
            return "Jane has a customer credit of 25.00.", False

    assistant = FarmAssistantService(
        FakeProfitabilityService(),
        account_ledger_service=FakeLedgerService(),
        inventory_service=FakeInventoryService(),
        conversation_repository=FakeConversationRepository(),
        unit_of_work=FakeUnitOfWork(),
        gemini_client=FakeGeminiClient(),
    )

    (
        conversation_id,
        answer,
        needs_clarification,
        scopes,
        from_date,
        to_date,
        _,
    ) = await assistant.answer_chat_question(
        farm_id=farm_id,
        user_id=user_id,
        question="Who has a credit?",
    )

    assert conversation_id
    assert answer == "Jane has a customer credit of 25.00."
    assert not needs_clarification
    assert scopes == [
        "contact_balances",
        "contact_ledger",
        "inventory_balances",
    ]
    assert from_date == date(2026, 1, 1)
    assert to_date == date(2026, 1, 31)
    assert safe_data is not None
    serialized = json.dumps(safe_data)
    assert "Jane Doe [redacted] [redacted]" in serialized
    assert "customer_credit" in serialized
    assert "contact_id" not in serialized
    assert str(contact_id) not in serialized
    assert "jane@example.com" not in serialized
    assert "07123456789" not in serialized
    assert safe_ledger is not None
    serialized_ledger = json.dumps(safe_ledger)
    assert "Jane Doe" in serialized_ledger
    assert "customer_credit" in serialized_ledger
    assert "settlement" in serialized_ledger
    assert "running_balance" in serialized_ledger
    assert "contact_id" not in serialized_ledger
    assert "transaction_id" not in serialized_ledger
    assert "event-private-id" not in serialized_ledger
    assert "REF-PRIVATE" not in serialized_ledger
    assert "Private note" not in serialized_ledger
    assert "PAYMENT-PRIVATE" not in serialized_ledger
    assert "COMPONENT-PRIVATE" not in serialized_ledger
    assert safe_inventory == {
        "match_status": "matched",
        "product_count": 1,
        "products_truncated": False,
        "items": [
            {
                "product_name": "Layer Feed",
                "product_type": "feed",
                "quantity": "12.500",
                "unit_name": "kilogram",
                "unit_abbreviation": "kg",
            }
        ],
    }


@pytest.mark.asyncio
async def test_farm_operations_summary_aggregates_safe_data_and_respects_block_scope(
    monkeypatch,
):
    fixed_today = date(2026, 1, 31)
    monkeypatch.setattr(
        "app.services.ai_assistant.date_ranges.current_farm_datetime",
        lambda: datetime(2026, 1, 31, 12, 0, tzinfo=ZoneInfo(settings.timezone)),
    )
    farm_id = uuid4()
    expected_farm_id = farm_id
    user_id = uuid4()
    block_id = uuid4()
    product_id = uuid4()
    private_id = str(uuid4())
    expected_farm = Farm(
        id=farm_id,
        owner_id=user_id,
        name="Test farm",
        is_active=True,
    )
    north_block = SimpleNamespace(
        id=block_id,
        name="North House",
        occupied_chickens=18,
        capacity=20,
        is_active=True,
    )
    product = SimpleNamespace(
        id=product_id,
        name="Table Eggs",
        product_type=SimpleNamespace(value="egg"),
        product_units=[
            SimpleNamespace(
                is_base_unit=True,
                unit_name="egg",
                unit_abbreviation="egg",
            )
        ],
    )
    other_block_id = uuid4()
    expected_product_id = product_id

    class FakeBlockService:
        async def list_blocks(
            self,
            farm: Farm,
            search: str | None = None,
            is_active: bool | None = None,
            limit: int | None = None,
            offset: int = 0,
        ) -> list[Any]:
            assert farm is expected_farm
            if search is not None:
                assert search == "north house"
            assert limit is None
            return [north_block]

    class FakeProductService:
        async def list_products(
            self,
            farm: Farm,
            search: str | None = None,
        ) -> list[Any]:
            assert farm is expected_farm
            return [product]

    class FakeChickenLossService:
        async def list_losses(
            self,
            farm: Farm,
            *,
            batch_id: UUID | None = None,
            block_id: UUID | None = None,
            reason: str | None = None,
            from_date: date | None = None,
            to_date: date | None = None,
        ) -> list[Any]:
            assert farm is expected_farm
            assert block_id in (None, north_block.id)
            assert from_date == date(2026, 1, 1)
            assert to_date == date(2026, 1, 31)
            return [
                SimpleNamespace(
                    id=private_id,
                    reason=SimpleNamespace(value="disease"),
                    quantity=2,
                    notes="Private loss note",
                ),
                SimpleNamespace(
                    id=private_id,
                    reason=SimpleNamespace(value="disease"),
                    quantity=1,
                    notes="Private loss note",
                ),
            ]

    class FakeChickenMovementService:
        async def list_movements(
            self,
            farm: Farm,
            *,
            batch_id: UUID | None = None,
            from_block_id: UUID | None = None,
            to_block_id: UUID | None = None,
            from_date: date | None = None,
            to_date: date | None = None,
        ) -> list[Any]:
            assert farm is expected_farm
            return [
                SimpleNamespace(
                    id=private_id,
                    from_block_id=other_block_id,
                    to_block_id=block_id,
                    quantity=4,
                    notes="Private movement note",
                ),
                SimpleNamespace(
                    id=private_id,
                    from_block_id=block_id,
                    to_block_id=other_block_id,
                    quantity=6,
                    notes="Private movement note",
                ),
                SimpleNamespace(
                    id=private_id,
                    from_block_id=other_block_id,
                    to_block_id=uuid4(),
                    quantity=9,
                    notes="Unrelated movement",
                ),
            ]

    class FakeEggCollectionService:
        async def list_collections(
            self,
            farm: Farm,
            *,
            product_id: UUID | None = None,
            block_id: UUID | None = None,
            from_datetime: datetime | None = None,
            to_datetime: datetime | None = None,
        ) -> list[Any]:
            assert farm is expected_farm
            assert block_id in (None, north_block.id)
            assert from_datetime is not None and from_datetime.tzinfo is not None
            assert to_datetime is not None and to_datetime.tzinfo is not None
            return [
                SimpleNamespace(
                    id=private_id,
                    product_id=expected_product_id,
                    entry_type="collection",
                    quantity_in_base_unit=Decimal("12.500"),
                    notes="Private collection note",
                ),
                SimpleNamespace(
                    id=private_id,
                    product_id=expected_product_id,
                    entry_type="opening_stock",
                    quantity_in_base_unit=Decimal("50"),
                    notes="Opening stock",
                ),
            ]

    class FakeEggLossService:
        async def list_losses(
            self,
            farm: Farm,
            *,
            product_id: UUID | None = None,
            reason: Any = None,
            from_date: date | None = None,
            to_date: date | None = None,
        ) -> list[Any]:
            assert farm is expected_farm
            return [
                SimpleNamespace(
                    id=private_id,
                    product_id=expected_product_id,
                    quantity_in_base_unit=Decimal("1.500"),
                    notes="Private egg loss note",
                )
            ]

    class FakeProductConsumptionService:
        async def list_consumptions(
            self,
            farm: Farm,
            *,
            product_id: UUID | None = None,
            block_id: UUID | None = None,
            batch_id: UUID | None = None,
            from_date: date | None = None,
            to_date: date | None = None,
        ) -> list[Any]:
            assert farm is expected_farm
            return [
                SimpleNamespace(
                    id=private_id,
                    product_id=expected_product_id,
                    quantity_in_base_unit=Decimal("4.250"),
                    notes="Private consumption note",
                )
            ]

    class FakeProfitabilityService:
        async def build_report(
            self,
            farm_id: UUID,
            *,
            from_date: date,
            to_date: date,
        ) -> ProfitabilityReportResponse:
            raise AssertionError("Profitability is not used in this test.")

    class FakeSalesReportService:
        total_count = 1

        async def get_report(
            self,
            farm_id: UUID,
            filters: Any,
            offset: int,
            limit: int,
            include_daily: bool = False,
        ) -> Any:
            assert farm_id == expected_farm_id
            assert filters.from_date == date(2026, 1, 30)
            assert filters.to_date == date(2026, 1, 30)
            assert offset == 0
            assert limit == 100
            return SimpleNamespace(
                items=[
                    SimpleNamespace(
                        id=uuid4(),
                        transaction_date=date(2026, 1, 30),
                        transaction_time=time(13, 30),
                        customer_name="Sample Customer",
                        products_sold=[
                            SimpleNamespace(
                                name="Table Eggs",
                                quantity=Decimal("3"),
                                unit_name="egg",
                            )
                        ],
                        transaction_total=Decimal("12.00"),
                        amount_paid=Decimal("10.00"),
                        balance_due=Decimal("2.00"),
                    )
                ],
                total_count=self.total_count,
                summary=SimpleNamespace(
                    transaction_count=1,
                    sales_total=Decimal("12.00"),
                    amount_received=Decimal("10.00"),
                    balance_due=Decimal("2.00"),
                ),
            )

        async def get_pending_deliveries(
            self,
            farm_id: UUID,
            *,
            limit: int,
        ) -> list[Any]:
            assert limit == 101
            return [
                SimpleNamespace(
                    id=uuid4(),
                    transaction_date=date(2026, 1, 30),
                    items=[
                        SimpleNamespace(
                            product_name="Broilers",
                            quantity_remaining=Decimal("2"),
                            unit_name="chickens",
                        )
                    ],
                )
            ]

    class FakeConversationRepository:
        async def create(
            self,
            *,
            farm_id: UUID,
            user_id: UUID,
            title: str,
        ) -> Any:
            return SimpleNamespace(id=uuid4(), title=title)

        async def get_for_user(self, **kwargs: Any) -> Any:
            raise AssertionError("Conversation storage is not used in this test.")

        async def list_for_user(self, **kwargs: Any) -> Any:
            raise AssertionError("Conversation storage is not used in this test.")

        async def list_messages(self, conversation_id: UUID) -> Any:
            raise AssertionError("Conversation storage is not used in this test.")

        async def add_exchange(
            self,
            *,
            conversation: Any,
            question: str,
            answer: str,
            from_date: date | None = None,
            to_date: date | None = None,
        ) -> None:
            if from_date is not None or to_date is not None:
                assert from_date is not None
                assert to_date is not None

        async def delete(self, conversation: Any) -> None:
            raise AssertionError("Conversation storage is not used in this test.")

    class FakeUnitOfWork:
        async def commit(self) -> None:
            pass

    class FakeLedgerService:
        async def get_ledger(
            self,
            farm_id: UUID,
            *,
            contact_id: UUID | None = None,
            from_date: date | None = None,
            to_date: date | None = None,
        ) -> AccountLedgerResponse:
            raise AssertionError("The contact ledger is not used in this test.")

    class FakeProvider:
        tool_arguments: dict[str, Any]
        tool_result: dict[str, Any] | None = None
        tool_name = "get_farm_operations_summary"
        last_question = ""

        async def answer(
            self,
            *,
            question: str,
            report_context: dict[str, Any],
            conversation_history: list[dict[str, str]] | None = None,
        ) -> str:
            raise AssertionError("The legacy answer flow is not used.")

        async def answer_with_tools(
            self,
            *,
            question: str,
            conversation_history: list[dict[str, str]],
            execute_tool: Any,
        ) -> tuple[str, bool]:
            self.last_question = question
            self.tool_result = await execute_tool(
                self.tool_name,
                self.tool_arguments,
            )
            return "Here is the operations summary.", False

    provider = FakeProvider()
    sales_report_service = FakeSalesReportService()
    assistant = FarmAssistantService(
        FakeProfitabilityService(),
        account_ledger_service=FakeLedgerService(),
        sales_report_service=sales_report_service,
        block_service=FakeBlockService(),
        product_service=FakeProductService(),
        chicken_loss_service=FakeChickenLossService(),
        chicken_movement_service=FakeChickenMovementService(),
        egg_collection_service=FakeEggCollectionService(),
        egg_loss_service=FakeEggLossService(),
        product_consumption_service=FakeProductConsumptionService(),
        provider_manager=provider,
        conversation_repository=FakeConversationRepository(),
        unit_of_work=FakeUnitOfWork(),
    )

    period = FarmOperationsSummaryToolArguments(
        from_date=date(2026, 1, 1),
        to_date=date(2026, 1, 31),
    )
    farm_summary = await assistant._farm_operations_summary(expected_farm, period)
    assert farm_summary["egg_collections"]["record_count"] == 1
    assert farm_summary["egg_collections"]["product_count"] == 1
    assert not farm_summary["egg_collections"]["products_truncated"]
    assert farm_summary["egg_collections"]["by_product"] == [
        {
            "product_name": "Table Eggs",
            "product_type": "egg",
            "quantity": "12.500",
            "unit_name": "egg",
            "unit_abbreviation": "egg",
        }
    ]
    assert farm_summary["egg_losses"]["by_product"][0]["quantity"] == "1.500"
    assert farm_summary["chicken_losses"]["chickens_lost"] == 3
    assert farm_summary["chicken_movements"] == {
        "movement_count": 3,
        "chickens_moved": 19,
    }
    assert farm_summary["product_consumption"]["by_product"][0]["quantity"] == "4.250"

    block_period = FarmOperationsSummaryToolArguments(
        from_date=date(2026, 1, 1),
        to_date=date(2026, 1, 31),
        block_name="north house",
    )
    provider.tool_arguments = block_period.model_dump(mode="json")
    (
        conversation_id,
        answer,
        needs_clarification,
        data_scopes,
        from_date,
        to_date,
        _,
    ) = await assistant.answer_chat_question(
        farm_id=farm_id,
        user_id=user_id,
        question="Summarize North House operations for January.",
        farm=expected_farm,
    )
    block_summary = provider.tool_result
    assert conversation_id
    assert answer == "Here is the operations summary."
    assert not needs_clarification
    assert data_scopes == ["farm_operations_summary"]
    assert from_date == date(2026, 1, 1)
    assert to_date == date(2026, 1, 31)
    assert block_summary is not None
    assert block_summary["scope"] == {
        "type": "block",
        "block_name": "North House",
    }
    assert block_summary["chicken_movements"] == {
        "movement_count": 2,
        "chickens_moved_in": 4,
        "chickens_moved_out": 6,
    }
    assert block_summary["egg_losses"]["attribution"] == "not_available_for_block"
    serialized = json.dumps(block_summary)
    assert private_id not in serialized
    assert "Private" not in serialized
    assert "notes" not in serialized
    assert "batch_id" not in serialized

    provider.tool_name = "get_sales_report"
    provider.tool_arguments = {}
    (
        _,
        _,
        _,
        sales_scopes,
        sales_from_date,
        sales_to_date,
        _,
    ) = await assistant.answer_chat_question(
        farm_id=farm_id,
        user_id=user_id,
        question="What sale did I make yesterday?",
        farm=expected_farm,
    )
    assert sales_scopes == ["sales_report"]
    assert sales_from_date == date(2026, 1, 30)
    assert sales_to_date == date(2026, 1, 30)
    assert provider.tool_result is not None
    assert provider.tool_result["product_ranking_complete"]
    assert provider.tool_result["transactions"][0]["customer_name"] == (
        "Sample Customer"
    )
    assert provider.tool_result["transactions"][0]["time"] == "13:30:00"
    assert provider.tool_result["transactions"][0]["products"][0]["name"] == (
        "Table Eggs"
    )
    sales_report_service.total_count = 101
    await assistant.answer_chat_question(
        farm_id=farm_id,
        user_id=user_id,
        question="What was my best-selling product yesterday?",
        farm=expected_farm,
    )
    assert provider.tool_result is not None
    assert not provider.tool_result["product_ranking_complete"]
    assert provider.tool_result["product_ranking"] == []

    provider.tool_name = "get_farm_block_status"
    provider.tool_arguments = {}
    (
        _,
        _,
        _,
        block_scopes,
        block_from_date,
        block_to_date,
        _,
    ) = await assistant.answer_chat_question(
        farm_id=farm_id,
        user_id=user_id,
        question="Which blocks are full?",
        farm=expected_farm,
    )
    assert block_scopes == ["block_status"]
    assert block_from_date is None
    assert block_to_date is None
    assert provider.tool_result is not None
    assert provider.tool_result["assigned_chicken_count"] == 18
    assert provider.tool_result["blocks"][0]["nearly_full"]

    provider.tool_name = "get_pending_deliveries"
    provider.tool_arguments = {}
    await assistant.answer_chat_question(
        farm_id=farm_id,
        user_id=user_id,
        question="How many deliveries do I have pending?",
        farm=expected_farm,
    )
    assert provider.tool_result is not None
    assert provider.tool_result["delivery_count"] == 1
    assert provider.tool_result["deliveries"][0]["items"][0][
        "quantity_remaining"
    ] == "2"

    provider.tool_name = "get_app_navigation"
    provider.tool_arguments = {"destination": "theme_settings"}
    (
        _,
        _,
        _,
        navigation_scopes,
        _,
        _,
        _,
    ) = await assistant.answer_chat_question(
        farm_id=farm_id,
        user_id=user_id,
        question="Where can I change the theme?",
        farm=expected_farm,
    )
    assert navigation_scopes == []
    assert provider.tool_result == {
        "destination": "theme_settings",
        "label": "Theme settings",
        "href": "/settings",
        "steps": (
            "Open More and choose Settings. In the appearance section, "
            "choose a theme preset, select Light, Dark, or System under "
            "Theme mode, preview it if you like, then select Save changes "
            "to keep it."
        ),
    }
    provider.tool_arguments = {"destination": "chicken_sale"}
    await assistant.answer_chat_question(
        farm_id=farm_id,
        user_id=user_id,
        question="How do I record a chicken sale?",
        farm=expected_farm,
    )
    assert provider.tool_result is not None
    assert provider.tool_result["destination"] == "chicken_sale"
    assert provider.tool_result["label"] == "Record a chicken sale"
    assert provider.tool_result["href"] == "/chicken-sale"
    assert "Sell chickens" in provider.tool_result["steps"]
    assert "delivery" in provider.tool_result["steps"].casefold()
    assert "Record delivery" in provider.tool_result["detailed_steps"]
    assert "Record sale order" in provider.tool_result["detailed_steps"]
    provider.tool_arguments = {"destination": "chicken_purchase"}
    (
        _,
        _,
        _,
        _,
        _,
        _,
        suggested_replies,
    ) = await assistant.answer_chat_question(
        farm_id=farm_id,
        user_id=user_id,
        question="How do I buy chickens?",
        source_route="/(tabs)/flock",
        farm=expected_farm,
    )
    route = resolve_app_route("/(tabs)/flock")
    assert route is not None
    assert provider.last_question == (
        f"[FarmTrack app context: {describe_app_route(route)}]\n"
        "How do I buy chickens?"
    )
    assert provider.tool_result is not None
    assert "Purchase birds" in provider.tool_result["steps"]
    assert "More > Purchases" in provider.tool_result["steps"]
    assert "detailed_steps" in provider.tool_result
    assert "Record arrival" in provider.tool_result["detailed_steps"]
    assert suggested_replies == [
        {
            "label": "Guide me step by step",
            "question": "Guide me step by step through the chicken purchase form.",
        },
        {
            "label": "Explain recording an arrival",
            "question": (
                "How do I record the chicken arrival after saving a purchase?"
            ),
        },
    ]

    provider.tool_arguments = {"destination": "eggs"}
    (
        _,
        _,
        _,
        _,
        _,
        _,
        eggs_suggested_replies,
    ) = await assistant.answer_chat_question(
        farm_id=farm_id,
        user_id=user_id,
        question="What can I do on the Eggs page?",
        source_route="/(tabs)/eggs",
        farm=expected_farm,
    )
    route = resolve_app_route("/(tabs)/eggs")
    assert route is not None
    assert provider.last_question == (
        f"[FarmTrack app context: {describe_app_route(route)}]\n"
        "What can I do on the Eggs page?"
    )
    assert provider.tool_result is not None
    assert "Sell eggs when there is sellable stock" in provider.tool_result["steps"]
    assert "on-hand stock" in provider.tool_result["steps"]
    assert eggs_suggested_replies == [
        {
            "label": "Record egg collection",
            "question": "How do I record an egg collection?",
        },
        {"label": "Sell eggs", "question": "How do I record an egg sale?"},
        {"label": "Record egg loss", "question": "How do I record an egg loss?"},
    ]

    workflow_expectations = [
        (
            "chicken_sale",
            "How do I sell chickens?",
            "Record sale order",
            "Record delivery",
            "Sales tab",
        ),
        (
            "record_chicken_loss",
            "How do I record chicken losses?",
            "Review losses",
            "Natural death",
            "Log loss",
        ),
        (
            "chicken_movement",
            "How do I move birds between blocks?",
            "source block",
            "Confirm move",
            "Move birds",
        ),
        (
            "egg_collection",
            "How do I collect eggs?",
            "source block",
            "collection date and time",
            "Home > Collect eggs",
        ),
        (
            "egg_loss",
            "How do I record an egg loss?",
            "available-after-loss",
            "Broken, Spoiled, Contaminated",
            "Eggs > Record loss",
        ),
        (
            "egg_sale",
            "How do I sell eggs?",
            "sellable stock",
            "three setup steps",
            "Sales > New sale > Sell eggs",
        ),
    ]
    for destination, question, overview_action, detail_action, route_action in (
        workflow_expectations
    ):
        provider.tool_arguments = {"destination": destination}
        (
            _,
            _,
            _,
            _,
            _,
            _,
            workflow_suggested_replies,
        ) = await assistant.answer_chat_question(
            farm_id=farm_id,
            user_id=user_id,
            question=question,
            source_route="/(tabs)/flock",
            farm=expected_farm,
        )
        workflow = provider.tool_result
        assert workflow is not None
        assert overview_action.casefold() in workflow["steps"].casefold()
        assert detail_action in workflow["detailed_steps"]
        assert route_action in workflow["steps"]
        assert workflow_suggested_replies[0]["label"] == "Guide me step by step"
        assert len(workflow_suggested_replies) == 2

    provider.tool_arguments = {"destination": "egg_collection"}
    await assistant.answer_chat_question(
        farm_id=farm_id,
        user_id=user_id,
        question="Walk me through egg collection.",
        source_route="/egg-collection",
        farm=expected_farm,
    )
    route = resolve_app_route("/egg-collection")
    assert route is not None
    assert provider.last_question == (
        f"[FarmTrack app context: {describe_app_route(route)}]\n"
        "Walk me through egg collection."
    )

    provider.tool_arguments = {"destination": "chicken_sale"}
    (
        _,
        _,
        _,
        _,
        _,
        _,
        workflow_suggested_replies,
    ) = await assistant.answer_chat_question(
        farm_id=farm_id,
        user_id=user_id,
        question="How do I record the chicken delivery?",
        source_route="/transactions/123",
        farm=expected_farm,
    )
    assert workflow_suggested_replies == []

    with pytest.raises(ValidationError):
        FarmOperationsSummaryToolArguments(
            from_date=date(2025, 1, 1),
            to_date=date(2026, 1, 3),
        )
    with pytest.raises(ValidationError):
        FarmOperationsSummaryToolArguments(
            from_date=date(2026, 1, 1),
            to_date=date(2026, 1, 31),
            block_name=" ",
        )


@pytest.mark.asyncio
async def test_gemini_tool_response_uses_user_role_and_finishes_after_tool(monkeypatch):
    monkeypatch.setattr(settings, "gemini_api_key", SecretStr("test-api-key"))
    requests: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        requests.append(body)
        if len(requests) == 1:
            return httpx.Response(
                200,
                json={
                    "candidates": [
                        {
                            "finishReason": "STOP",
                            "content": {
                                "role": "model",
                                "parts": [
                                    {
                                        "functionCall": {
                                            "name": "get_contact_balances",
                                            "args": {},
                                        }
                                    }
                                ],
                            },
                        }
                    ]
                },
            )
        return httpx.Response(
            200,
            json={
                "candidates": [
                    {
                        "finishReason": "STOP",
                        "content": {
                            "parts": [{"text": "No outstanding balances."}]
                        },
                    }
                ]
            },
        )

    original_client = httpx.AsyncClient
    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(
        "app.services.ai_assistant_service.httpx.AsyncClient",
        lambda **kwargs: original_client(transport=transport, **kwargs),
    )

    async def execute_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        assert name == "get_contact_balances"
        assert arguments == {}
        return {"accounts": []}

    answer, needs_clarification = await GeminiClient().answer_with_tools(
        question="Who owes me?",
        conversation_history=[],
        execute_tool=execute_tool,
    )

    assert answer == "No outstanding balances."
    assert not needs_clarification
    assert len(requests) == 2
    assert requests[0]["toolConfig"]["functionCallingConfig"] == {
        "mode": "AUTO"
    }
    assert requests[0]["tools"][0]["functionDeclarations"]
    assert requests[0]["generationConfig"]["responseMimeType"] == "text/plain"
    tool_response = requests[1]["contents"][-1]
    assert tool_response["role"] == "user"
    assert tool_response["parts"][0]["functionResponse"] == {
        "name": "get_contact_balances",
        "response": {"accounts": []},
    }


@pytest.mark.asyncio
async def test_gemini_chat_rate_limit_is_classified_as_retryable_429(monkeypatch):
    monkeypatch.setattr(settings, "gemini_api_key", SecretStr("test-api-key"))

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            429,
            json={"error": {"message": "provider-internal-quota-detail"}},
        )

    original_client = httpx.AsyncClient
    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(
        "app.services.ai_assistant_service.httpx.AsyncClient",
        lambda **kwargs: original_client(transport=transport, **kwargs),
    )

    async def execute_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        raise AssertionError("A rate-limited request must not execute a tool.")

    with pytest.raises(AIProviderFailure) as error:
        await GeminiClient().answer_with_tools(
            question="Hello",
            conversation_history=[],
            execute_tool=execute_tool,
        )

    assert error.value.provider == "gemini"
    assert error.value.status_code == 429
    assert error.value.reason == "rate_limit"
    assert error.value.retryable
    assert error.value.cooldown_seconds == 60


@pytest.mark.asyncio
async def test_assistant_sends_only_allowlisted_aggregate_report_data():
    farm_id = uuid4()
    report = create_profitability_report(
        farm_id=farm_id,
        product_performance=[
            {
                "product_id": uuid4(),
                "product_name": "Supplier secret-name@example.com",
                "product_type": "feed",
                "unit_name": "kg",
                "unit_abbreviation": "kg",
                "quantity_sold": Decimal("1"),
                "sales_value": Decimal("10"),
                "sales_credits": Decimal("0"),
                "net_sales": Decimal("10"),
                "cost_of_goods_sold": Decimal("2"),
                "average_selling_price": Decimal("10"),
                "average_unit_cost": Decimal("2"),
                "gross_profit": Decimal("8"),
                "uncosted_quantity": Decimal("0"),
            }
        ],
    )

    class FakeProfitabilityService:
        async def build_report(
            self,
            farm_id: UUID,
            *,
            from_date: date,
            to_date: date,
        ) -> ProfitabilityReportResponse:
            assert farm_id == report.farm_id
            assert from_date == report.from_date
            assert to_date == report.to_date
            return report

    class FakeConversationRepository:
        conversation = SimpleNamespace(id=uuid4(), title="")
        exchange: dict[str, Any] | None = None
        expected_user_id = uuid4()

        async def get_for_user(
            self,
            *,
            conversation_id: UUID,
            farm_id: UUID,
            user_id: UUID,
        ) -> Any:
            assert farm_id == report.farm_id
            assert user_id == self.expected_user_id
            return None

        async def create(
            self,
            *,
            farm_id: UUID,
            user_id: UUID,
            title: str,
        ) -> Any:
            self.conversation.title = title[:120]
            assert farm_id == report.farm_id
            assert user_id == self.expected_user_id
            return self.conversation

        async def list_for_user(
            self,
            *,
            farm_id: UUID,
            user_id: UUID,
            limit: int,
            offset: int,
        ) -> list[Any]:
            raise AssertionError("Conversation listing is not used in this test.")

        async def list_messages(self, conversation_id: UUID) -> list[Any]:
            raise AssertionError("Existing messages are not used in this test.")

        async def add_exchange(
            self,
            *,
            conversation: Any,
            question: str,
            answer: str,
            from_date: date | None = None,
            to_date: date | None = None,
        ) -> None:
            self.exchange = {
                "conversation": conversation,
                "question": question,
                "answer": answer,
                "from_date": from_date,
                "to_date": to_date,
            }

        async def delete(self, conversation: Any) -> None:
            raise AssertionError("Conversation deletion is not used in this test.")

    class FakeUnitOfWork:
        committed = False

        async def commit(self) -> None:
            self.committed = True

    class FakeGeminiClient(GeminiClient):
        captured: tuple[str, dict[str, Any]] | None = None
        captured_history: list[dict[str, str]] | None = None

        async def answer(
            self,
            *,
            question: str,
            report_context: dict[str, Any],
            conversation_history: list[dict[str, str]] | None = None,
        ) -> str:
            self.captured = (question, report_context)
            self.captured_history = conversation_history
            return "Net profit was 440.00."

    gemini = FakeGeminiClient()
    conversation_repository = FakeConversationRepository()
    user_id = conversation_repository.expected_user_id
    unit_of_work = FakeUnitOfWork()
    assistant = FarmAssistantService(
        FakeProfitabilityService(),
        conversation_repository=conversation_repository,
        unit_of_work=unit_of_work,
        gemini_client=gemini,
    )

    conversation_id, answer = await assistant.answer_profitability_question(
        farm_id=farm_id,
        user_id=user_id,
        question="Explain net profit",
        from_date=report.from_date,
        to_date=report.to_date,
    )

    assert answer == "Net profit was 440.00."
    assert conversation_id == conversation_repository.conversation.id
    assert conversation_repository.exchange is not None
    assert conversation_repository.exchange["question"] == "Explain net profit"
    assert conversation_repository.exchange["answer"] == answer
    assert unit_of_work.committed
    captured = gemini.captured
    assert captured is not None
    question, context = captured
    assert question == "Explain net profit"
    assert context["net_profit"] == "440.00"
    assert "farm_id" not in context
    assert "product_performance" not in context
    assert "Supplier secret-name@example.com" not in str(context)
    assert gemini.captured_history == []


@pytest.mark.asyncio
async def test_gemini_request_keeps_key_out_of_url_and_sends_history_and_report_context(
    monkeypatch,
):
    monkeypatch.setattr(settings, "gemini_api_key", SecretStr("test-api-key"))
    monkeypatch.setattr(settings, "gemini_model", "gemini-3-flash-preview")
    captured = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(
            200,
            json={
                "candidates": [
                    {
                        "finishReason": "STOP",
                        "content": {
                            "parts": [
                                {"text": "The report is "},
                                {"text": "complete."},
                            ]
                        },
                    }
                ]
            },
        )

    original_client = httpx.AsyncClient
    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(
        "app.services.ai_assistant_service.httpx.AsyncClient",
        lambda **kwargs: original_client(transport=transport, **kwargs),
    )

    answer = await GeminiClient().answer(
        question="Summarize this report",
        report_context={"net_revenue": "950.00"},
        conversation_history=[
            {"role": "user", "content": "What were sales?"},
            {"role": "assistant", "content": "Net revenue was 950.00."},
        ],
    )

    assert answer == "The report is complete."
    assert len(captured) == 1
    request = captured[0]
    assert request.headers["x-goog-api-key"] == "test-api-key"
    assert "test-api-key" not in str(request.url)
    assert "net_revenue" in request.content.decode()
    assert "Authorization" not in request.headers
    generation_config = request.read()
    request_payload = json.loads(generation_config)
    assert request_payload["generationConfig"]["maxOutputTokens"] == 1024
    assert request_payload["generationConfig"]["thinkingConfig"] == {
        "thinkingLevel": "low"
    }
    assert [
        message["role"] for message in request_payload["contents"][:-1]
    ] == ["user", "model"]
    assert request_payload["contents"][-1]["role"] == "user"


@pytest.mark.asyncio
async def test_existing_conversation_history_is_sent_to_gemini_and_appended():
    expected_farm_id = uuid4()
    expected_user_id = uuid4()
    conversation_id_expected = uuid4()
    farm_id = expected_farm_id
    user_id = expected_user_id
    conversation_id = conversation_id_expected
    report = create_profitability_report(farm_id=farm_id)
    previous_messages = [
        SimpleNamespace(role="user", content="What were sales?"),
        SimpleNamespace(role="assistant", content="Net revenue was 950.00."),
    ]

    class FakeProfitabilityService:
        async def build_report(self, *args: Any, **kwargs: Any):
            return report

    class FakeConversationRepository:
        async def get_for_user(
            self,
            *,
            conversation_id: UUID,
            farm_id: UUID,
            user_id: UUID,
        ) -> Any:
            assert conversation_id == conversation_id_expected
            assert farm_id == expected_farm_id
            assert user_id == expected_user_id
            return SimpleNamespace(id=conversation_id)

        async def list_messages(self, conversation_id: UUID) -> Any:
            assert conversation_id == conversation_id_expected
            return previous_messages

        async def create(
            self,
            *,
            farm_id: UUID,
            user_id: UUID,
            title: str,
        ) -> Any:
            raise AssertionError("A new conversation is not used in this test.")

        async def list_for_user(
            self,
            *,
            farm_id: UUID,
            user_id: UUID,
            limit: int,
            offset: int,
        ) -> list[Any]:
            raise AssertionError("Conversation listing is not used in this test.")

        async def add_exchange(
            self,
            *,
            conversation: Any,
            question: str,
            answer: str,
            from_date: date | None = None,
            to_date: date | None = None,
        ) -> None:
            self.exchange = {
                "conversation": conversation,
                "question": question,
                "answer": answer,
                "from_date": from_date,
                "to_date": to_date,
            }

        async def delete(self, conversation: Any) -> None:
            raise AssertionError("Conversation deletion is not used in this test.")

    class FakeUnitOfWork:
        async def commit(self) -> None:
            pass

    class FakeGeminiClient:
        history: list[dict[str, str]] | None = None

        async def answer(
            self,
            *,
            question: str,
            report_context: dict[str, Any],
            conversation_history: list[dict[str, str]] | None = None,
        ) -> str:
            self.history = conversation_history
            return "Costs were 510.00."

        async def answer_with_tools(
            self,
            *,
            question: str,
            conversation_history: list[dict[str, str]],
            execute_tool: Any,
        ) -> tuple[str, bool]:
            raise AssertionError("The read-tool chat flow is not used.")

    gemini = FakeGeminiClient()
    assistant = FarmAssistantService(
        FakeProfitabilityService(),
        conversation_repository=FakeConversationRepository(),
        unit_of_work=FakeUnitOfWork(),
        gemini_client=gemini,
    )

    result_id, answer = await assistant.answer_profitability_question(
        farm_id=farm_id,
        user_id=user_id,
        question="And what were the costs?",
        from_date=report.from_date,
        to_date=report.to_date,
        conversation_id=conversation_id,
    )

    assert result_id == conversation_id
    assert answer == "Costs were 510.00."
    assert gemini.history == [
        {"role": "user", "content": "What were sales?"},
        {"role": "assistant", "content": "Net revenue was 950.00."},
    ]


@pytest.mark.asyncio
async def test_conversation_outside_user_and_farm_scope_is_not_accessible():
    class FakeConversationRepository:
        async def get_for_user(
            self,
            *,
            conversation_id: UUID,
            farm_id: UUID,
            user_id: UUID,
        ) -> Any:
            return None

        async def create(
            self,
            *,
            farm_id: UUID,
            user_id: UUID,
            title: str,
        ) -> Any:
            raise AssertionError("A conversation must not be created.")

        async def list_for_user(
            self,
            *,
            farm_id: UUID,
            user_id: UUID,
            limit: int,
            offset: int,
        ) -> list[Any]:
            raise AssertionError("Conversation listing is not used in this test.")

        async def list_messages(self, conversation_id: UUID) -> Any:
            raise AssertionError("Messages must not be read for an inaccessible conversation.")

        async def add_exchange(
            self,
            *,
            conversation: Any,
            question: str,
            answer: str,
            from_date: date | None = None,
            to_date: date | None = None,
        ) -> None:
            raise AssertionError("Messages must not be added.")

        async def delete(self, conversation: Any) -> None:
            raise AssertionError("An inaccessible conversation must not be deleted.")

    class FakeProfitabilityService:
        async def build_report(self, *args: Any, **kwargs: Any):
            raise AssertionError("A report must not be built for an inaccessible conversation.")

    class FakeUnitOfWork:
        async def commit(self) -> None:
            raise AssertionError("No changes should be committed.")

    class FakeGeminiClient:
        async def answer(
            self,
            *,
            question: str,
            report_context: dict[str, Any],
            conversation_history: list[dict[str, str]] | None = None,
        ) -> str:
            raise AssertionError("Gemini must not be called for an inaccessible conversation.")

        async def answer_with_tools(
            self,
            *,
            question: str,
            conversation_history: list[dict[str, str]],
            execute_tool: Any,
        ) -> tuple[str, bool]:
            raise AssertionError("Gemini must not be called for an inaccessible conversation.")

    assistant = FarmAssistantService(
        FakeProfitabilityService(),
        conversation_repository=FakeConversationRepository(),
        unit_of_work=FakeUnitOfWork(),
        gemini_client=FakeGeminiClient(),
    )
    scope = {
        "conversation_id": uuid4(),
        "farm_id": uuid4(),
        "user_id": uuid4(),
    }

    with pytest.raises(AppError) as read_error:
        await assistant.get_conversation(**scope)
    assert read_error.value.status_code == 404

    with pytest.raises(AppError) as delete_error:
        await assistant.delete_conversation(**scope)
    assert delete_error.value.status_code == 404

    with pytest.raises(AppError) as rename_error:
        await assistant.rename_conversation(**scope, title="Renamed chat")
    assert rename_error.value.status_code == 404

    with pytest.raises(AppError) as continue_error:
        await assistant.answer_profitability_question(
            farm_id=scope["farm_id"],
            user_id=scope["user_id"],
            conversation_id=scope["conversation_id"],
            question="Explain the report",
            from_date=date(2026, 1, 1),
            to_date=date(2026, 1, 31),
        )
    assert continue_error.value.status_code == 404


@pytest.mark.asyncio
async def test_rename_conversation_updates_title_and_commits():
    conversation = SimpleNamespace(title="Old title")
    expected_scope = {
        "conversation_id": uuid4(),
        "farm_id": uuid4(),
        "user_id": uuid4(),
    }

    class FakeConversationRepository:
        async def get_for_user(self, **kwargs: Any):
            assert kwargs == expected_scope
            return conversation

    class FakeProfitabilityService:
        pass

    class FakeUnitOfWork:
        committed = False

        async def commit(self) -> None:
            self.committed = True

    unit_of_work = FakeUnitOfWork()
    assistant = FarmAssistantService(
        cast(Any, FakeProfitabilityService()),
        conversation_repository=cast(Any, FakeConversationRepository()),
        unit_of_work=cast(Any, unit_of_work),
    )

    renamed = await assistant.rename_conversation(
        **expected_scope,
        title="New title",
    )

    assert renamed is conversation
    assert conversation.title == "New title"
    assert unit_of_work.committed


@pytest.mark.asyncio
async def test_gemini_truncated_response_is_rejected(monkeypatch):
    monkeypatch.setattr(settings, "gemini_api_key", SecretStr("test-api-key"))

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith(":generateContent")
        return httpx.Response(
            200,
            json={
                "candidates": [
                    {
                        "finishReason": "MAX_TOKENS",
                        "content": {"parts": [{"text": "This answer is incomplete"}]},
                    }
                ]
            },
        )

    original_client = httpx.AsyncClient
    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(
        "app.services.ai_assistant_service.httpx.AsyncClient",
        lambda **kwargs: original_client(transport=transport, **kwargs),
    )

    with pytest.raises(AIProviderFailure) as error:
        await GeminiClient().answer(
            question="Summarize this report",
            report_context={"net_revenue": "950.00"},
        )

    assert error.value.reason == "incomplete_response"
    assert error.value.retryable
    assert error.value.status_code == 502
    assert "This answer is incomplete" not in str(error.value)


@pytest.mark.asyncio
async def test_transaction_details_include_farm_scoped_sale_events():
    farm_id = uuid4()
    transaction_id = uuid4()
    item_id = uuid4()
    transaction = SimpleNamespace(
        id=transaction_id,
        transaction_type=SimpleNamespace(value="sale"),
        status=SimpleNamespace(value="completed"),
        transaction_date=date(2026, 2, 1),
        transaction_time=time(10, 30),
        discount_amount=Decimal("0"),
        items=[
            SimpleNamespace(
                id=item_id,
                product=SimpleNamespace(
                    name="Table eggs",
                    product_type=SimpleNamespace(value="eggs"),
                ),
                quantity=Decimal("2"),
                conversion_factor=Decimal("1"),
                unit=SimpleNamespace(name="tray", abbreviation="tray"),
                unit_price=Decimal("10"),
                total_amount=Decimal("20"),
            )
        ],
        payments=[],
        settlements=[],
    )

    class FakeTransactionRepository:
        async def get_sale_detail_by_id(self, received_farm_id, received_transaction_id):
            assert (received_farm_id, received_transaction_id) == (
                farm_id,
                transaction_id,
            )
            return transaction

        async def get_purchase_detail_by_id(
            self,
            received_farm_id,
            received_transaction_id,
        ):
            assert (received_farm_id, received_transaction_id) == (
                farm_id,
                transaction_id,
            )
            return transaction

    class FakeRefundService:
        async def list_refunds(self, received_farm_id, received_transaction_id):
            assert (received_farm_id, received_transaction_id) == (
                farm_id,
                transaction_id,
            )
            return [
                SimpleNamespace(
                    refund_date=date(2026, 2, 2),
                    refund_time=time(11, 0),
                    amount=Decimal("5"),
                    payment_method=SimpleNamespace(value="cash"),
                )
            ]

    class FakeReturnService:
        async def list_returns(self, received_farm_id, received_transaction_id):
            assert (received_farm_id, received_transaction_id) == (
                farm_id,
                transaction_id,
            )
            return [
                SimpleNamespace(
                    return_date=date(2026, 2, 3),
                    return_time=None,
                    return_type=SimpleNamespace(value="return"),
                    credit_total=Decimal("2"),
                    items=[
                        SimpleNamespace(
                            product_name="Table eggs",
                            quantity=Decimal("1"),
                            credit_amount=Decimal("2"),
                        )
                    ],
                )
            ]

    class FakeDeliveryService:
        async def list_deliveries(self, received_farm_id, received_transaction_id):
            assert (received_farm_id, received_transaction_id) == (
                farm_id,
                transaction_id,
            )
            return [
                SimpleNamespace(
                    delivered_date=date(2026, 2, 1),
                    delivered_time=time(12, 0),
                    items=[
                        SimpleNamespace(
                            transaction_item_id=item_id,
                            quantity_delivered=Decimal("2"),
                            remaining_quantity=Decimal("0"),
                        )
                    ],
                )
            ]

    assistant = FarmAssistantService(
        cast(Any, SimpleNamespace()),
        transaction_repository=cast(Any, FakeTransactionRepository()),
        transaction_refund_service=cast(Any, FakeRefundService()),
        sale_return_service=cast(Any, FakeReturnService()),
        sale_delivery_service=cast(Any, FakeDeliveryService()),
        conversation_repository=cast(Any, SimpleNamespace()),
        unit_of_work=cast(Any, SimpleNamespace()),
    )

    details = await assistant._read_transaction_details(
        farm=cast(Any, SimpleNamespace(id=farm_id)),
        transaction_id=transaction_id,
        transaction_type="sale",
    )

    assert details is not None
    assert details["transaction"]["transaction_id"] == str(transaction_id)
    assert details["transaction"]["items"][0]["product_name"] == "Table eggs"
    assert details["activity"]["refunds"][0]["amount"] == "5"
    assert details["activity"]["returns"][0]["credit_total"] == "2"
    assert details["activity"]["deliveries"][0]["items"][0][
        "quantity_remaining"
    ] == "0"
    assert (
        await assistant._read_transaction_details(
            farm=cast(Any, SimpleNamespace(id=farm_id)),
            transaction_id=transaction_id,
            transaction_type="purchase",
        )
        is None
    )


@pytest.mark.asyncio
async def test_transaction_details_link_purchase_returns_replacements_and_receipts():
    farm_id = uuid4()
    transaction_id = uuid4()
    item_id = uuid4()
    return_item_id = uuid4()
    transaction = SimpleNamespace(
        id=transaction_id,
        transaction_type=SimpleNamespace(value="purchase"),
        status=SimpleNamespace(value="completed"),
        transaction_date=date(2026, 2, 1),
        transaction_time=None,
        discount_amount=Decimal("0"),
        items=[
            SimpleNamespace(
                id=item_id,
                product=SimpleNamespace(
                    name="Layers",
                    product_type=SimpleNamespace(value="chickens"),
                ),
                quantity=Decimal("10"),
                conversion_factor=Decimal("1"),
                unit=SimpleNamespace(name="bird", abbreviation="bird"),
                unit_price=Decimal("5"),
                total_amount=Decimal("50"),
            )
        ],
        payments=[],
        settlements=[],
    )

    class FakeTransactionRepository:
        async def get_purchase_detail_by_id(self, received_farm_id, received_transaction_id):
            assert (received_farm_id, received_transaction_id) == (
                farm_id,
                transaction_id,
            )
            return transaction

    class FakePurchaseReturnService:
        async def list_returns(self, received_farm_id, received_transaction_id):
            assert (received_farm_id, received_transaction_id) == (
                farm_id,
                transaction_id,
            )
            return [
                SimpleNamespace(
                    return_date=date(2026, 2, 2),
                    return_time=None,
                    credit_total=Decimal("5"),
                    items=[
                        SimpleNamespace(
                            id=return_item_id,
                            product_name="Layers",
                            quantity_returned=Decimal("1"),
                            credit_amount=Decimal("5"),
                        )
                    ],
                )
            ]

    class FakePurchaseReplacementService:
        async def list_replacements(self, received_farm_id, received_transaction_id):
            assert (received_farm_id, received_transaction_id) == (
                farm_id,
                transaction_id,
            )
            return [
                SimpleNamespace(
                    replacement_date=date(2026, 2, 3),
                    replacement_time=None,
                    credit_applied_total=Decimal("5"),
                    items=[
                        SimpleNamespace(
                            purchase_return_item_id=return_item_id,
                            quantity_received=Decimal("1"),
                            replacement_quantity=Decimal("1"),
                            bonus_quantity=Decimal("0"),
                            credit_applied_amount=Decimal("5"),
                        )
                    ],
                )
            ]

    class FakeSupplierRefundService:
        async def list_refunds(self, received_farm_id, received_transaction_id):
            assert (received_farm_id, received_transaction_id) == (
                farm_id,
                transaction_id,
            )
            return [
                SimpleNamespace(
                    refund_date=date(2026, 2, 4),
                    refund_time=None,
                    purchase_return_item_id=return_item_id,
                    amount=Decimal("5"),
                    payment_method=SimpleNamespace(value="cash"),
                )
            ]

    class FakeChickenPurchaseDetailsService:
        async def get_details(self, received_farm_id, received_transaction_id):
            assert (received_farm_id, received_transaction_id) == (
                farm_id,
                transaction_id,
            )
            return SimpleNamespace(
                receipts=[
                    SimpleNamespace(
                        received_date=date(2026, 2, 1),
                        received_time=None,
                        items=[
                            SimpleNamespace(
                                transaction_item_id=item_id,
                                quantity_received=Decimal("10"),
                                remaining_quantity=Decimal("10"),
                                batch_name="Batch 1",
                                block_allocations=[
                                    SimpleNamespace(
                                        block_name="North",
                                        quantity=10,
                                    )
                                ],
                            )
                        ],
                    )
                ]
            )

    assistant = FarmAssistantService(
        cast(Any, SimpleNamespace()),
        transaction_repository=cast(Any, FakeTransactionRepository()),
        purchase_return_service=cast(Any, FakePurchaseReturnService()),
        purchase_replacement_service=cast(Any, FakePurchaseReplacementService()),
        purchase_supplier_refund_service=cast(Any, FakeSupplierRefundService()),
        chicken_purchase_details_service=cast(
            Any,
            FakeChickenPurchaseDetailsService(),
        ),
        conversation_repository=cast(Any, SimpleNamespace()),
        unit_of_work=cast(Any, SimpleNamespace()),
    )

    details = await assistant._read_transaction_details(
        farm=cast(Any, SimpleNamespace(id=farm_id)),
        transaction_id=transaction_id,
        transaction_type="purchase",
    )

    assert details is not None
    assert details["activity"]["returns"][0]["items"][0][
        "quantity_returned"
    ] == "1"
    assert details["activity"]["replacements"][0]["items"][0][
        "product_name"
    ] == "Layers"
    assert details["activity"]["supplier_refunds"][0]["amount"] == "5"
    assert details["activity"]["receipts"][0]["items"][0][
        "block_allocations"
    ][0]["block_name"] == "North"


@pytest.mark.asyncio
async def test_gemini_request_fails_closed_when_api_key_is_missing(monkeypatch):
    monkeypatch.setattr(settings, "gemini_api_key", None)

    with pytest.raises(AppError) as error:
        await GeminiClient().answer(
            question="Summarize this report",
            report_context={},
        )

    assert error.value.code == "AI_ASSISTANT_UNAVAILABLE"
    assert error.value.status_code == 503


@pytest.mark.asyncio
async def test_gemini_provider_error_does_not_expose_provider_response(monkeypatch):
    monkeypatch.setattr(settings, "gemini_api_key", SecretStr("test-api-key"))

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["x-goog-api-key"] == "test-api-key"
        return httpx.Response(
            403,
            json={"error": {"message": "provider-private-error-detail"}},
        )

    original_client = httpx.AsyncClient
    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(
        "app.services.ai_assistant_service.httpx.AsyncClient",
        lambda **kwargs: original_client(transport=transport, **kwargs),
    )

    with pytest.raises(AIProviderFailure) as error:
        await GeminiClient().answer(
            question="Summarize this report",
            report_context={},
        )

    assert error.value.status_code == 403
    assert not error.value.retryable
    assert "provider-private-error-detail" not in str(error.value)


def test_profitability_assistant_endpoint_requires_authentication():
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(router)

    with TestClient(app) as client:
        response = client.post(
            f"/farms/{uuid4()}/assistant/profitability",
            json={
                "question": "Explain net profit",
                "from_date": "2026-01-01",
                "to_date": "2026-01-31",
            },
        )

    assert response.status_code == 401


def test_chat_assistant_endpoint_requires_authentication():
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(router)

    with TestClient(app) as client:
        response = client.post(
            f"/farms/{uuid4()}/assistant/chat",
            json={"question": "Who owes me?"},
        )

    assert response.status_code == 401


def test_profitability_assistant_endpoint_uses_authorized_farm():
    farm_id = uuid4()
    user_id = uuid4()
    conversation_id = uuid4()
    farm = SimpleNamespace(id=farm_id)

    class FakeAssistantService:
        captured: dict[str, Any] | None = None

        async def answer_profitability_question(
            self,
            **kwargs: Any,
        ) -> tuple[UUID, str]:
            self.captured = kwargs
            return conversation_id, "Net profit was 440.00."

    assistant = FakeAssistantService()
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(router)
    app.dependency_overrides[get_owned_farm] = lambda: farm
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=user_id)
    app.dependency_overrides[require_super_admin] = lambda: SimpleNamespace(
        role="SUPER_ADMIN"
    )
    app.dependency_overrides[get_farm_assistant_service] = lambda: assistant

    with TestClient(app) as client:
        response = client.post(
            f"/farms/{farm_id}/assistant/profitability",
            json={
                "question": "Explain net profit",
                "from_date": "2026-01-01",
                "to_date": "2026-01-31",
            },
        )

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.json()["conversation_id"] == str(conversation_id)
    assert response.json()["answer"] == "Net profit was 440.00."
    captured = assistant.captured
    assert captured is not None
    assert captured["farm_id"] == farm_id
    assert captured["user_id"] == user_id
    assert captured["from_date"] == date(2026, 1, 1)


def test_chat_assistant_endpoint_returns_clarification_without_period():
    farm_id = uuid4()
    user_id = uuid4()
    conversation_id = uuid4()
    farm = SimpleNamespace(id=farm_id)

    class FakeAssistantService:
        captured: dict[str, Any] | None = None

        async def answer_chat_question(self, **kwargs: Any):
            self.captured = kwargs
            return (
                conversation_id,
                "Which contact do you mean?",
                True,
                [],
                None,
                None,
                [],
            )

    assistant = FakeAssistantService()
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(router)
    app.dependency_overrides[get_owned_farm] = lambda: farm
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=user_id)
    app.dependency_overrides[require_super_admin] = lambda: SimpleNamespace(
        role="SUPER_ADMIN"
    )
    app.dependency_overrides[get_farm_assistant_service] = lambda: assistant

    with TestClient(app) as client:
        response = client.post(
            f"/farms/{farm_id}/assistant/chat",
            json={"question": "Who owes me?"},
        )

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.json() == {
        "conversation_id": str(conversation_id),
        "answer": "Which contact do you mean?",
        "needs_clarification": True,
        "data_scopes": [],
        "suggested_replies": [],
        "from_date": None,
        "to_date": None,
    }
    assert assistant.captured == {
        "farm_id": farm_id,
        "user_id": user_id,
        "question": "Who owes me?",
        "conversation_id": None,
        "source_route": None,
        "farm": farm,
    }


def test_chat_endpoint_returns_suggested_replies_and_source_route():
    farm_id = uuid4()
    user_id = uuid4()
    conversation_id = uuid4()
    farm = SimpleNamespace(id=farm_id)
    suggested_replies = [
        {
            "label": "Guide me step by step",
            "question": "Guide me step by step through the chicken purchase form.",
        }
    ]

    class FakeAssistantService:
        captured: dict[str, Any] | None = None

        async def answer_chat_question(self, **kwargs: Any):
            self.captured = kwargs
            return (
                conversation_id,
                "Tap Purchase birds.",
                False,
                [],
                None,
                None,
                suggested_replies,
            )

    assistant = FakeAssistantService()
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(router)
    app.dependency_overrides[get_owned_farm] = lambda: farm
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=user_id)
    app.dependency_overrides[require_super_admin] = lambda: SimpleNamespace(
        role="SUPER_ADMIN"
    )
    app.dependency_overrides[get_farm_assistant_service] = lambda: assistant

    with TestClient(app) as client:
        response = client.post(
            f"/farms/{farm_id}/assistant/chat",
            json={
                "question": "How do I buy chickens?",
                "source_route": "/(tabs)/flock",
            },
        )

    assert response.status_code == 200
    assert response.json()["suggested_replies"] == suggested_replies
    assert assistant.captured is not None
    assert assistant.captured["source_route"] == "/(tabs)/flock"


def test_conversation_routes_scope_access_to_authenticated_user_and_farm():
    farm_id = uuid4()
    user_id = uuid4()
    conversation_id = uuid4()
    created_at = datetime.now(timezone.utc)
    conversation = SimpleNamespace(
        id=conversation_id,
        title="Explain net profit",
        created_at=created_at,
        updated_at=created_at,
    )
    message = SimpleNamespace(
        id=uuid4(),
        role="user",
        content="Explain net profit",
        from_date=date(2026, 1, 1),
        to_date=date(2026, 1, 31),
        created_at=created_at,
    )

    class FakeAssistantService:
        captured_scope: dict[str, UUID] | None = None
        renamed_title: str | None = None

        async def list_conversations(self, **kwargs: Any):
            self.captured_scope = {
                "farm_id": kwargs["farm_id"],
                "user_id": kwargs["user_id"],
            }
            assert kwargs["limit"] == 10
            assert kwargs["offset"] == 5
            return [conversation]

        async def get_conversation(self, **kwargs: Any):
            self.captured_scope = {
                "farm_id": kwargs["farm_id"],
                "user_id": kwargs["user_id"],
            }
            assert kwargs["conversation_id"] == conversation_id
            return conversation, [message]

        async def delete_conversation(self, **kwargs: Any) -> None:
            self.captured_scope = {
                "farm_id": kwargs["farm_id"],
                "user_id": kwargs["user_id"],
            }
            assert kwargs["conversation_id"] == conversation_id

        async def rename_conversation(self, **kwargs: Any):
            self.captured_scope = {
                "farm_id": kwargs["farm_id"],
                "user_id": kwargs["user_id"],
            }
            assert kwargs["conversation_id"] == conversation_id
            self.renamed_title = kwargs["title"]
            conversation.title = kwargs["title"]
            return conversation

    assistant = FakeAssistantService()
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(router)
    app.dependency_overrides[get_owned_farm] = lambda: SimpleNamespace(id=farm_id)
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=user_id)
    app.dependency_overrides[require_super_admin] = lambda: SimpleNamespace(
        role="SUPER_ADMIN"
    )
    app.dependency_overrides[get_farm_assistant_service] = lambda: assistant

    with TestClient(app) as client:
        listed = client.get(
            f"/farms/{farm_id}/assistant/conversations?limit=10&offset=5"
        )
        retrieved = client.get(
            f"/farms/{farm_id}/assistant/conversations/{conversation_id}"
        )
        deleted = client.delete(
            f"/farms/{farm_id}/assistant/conversations/{conversation_id}"
        )
        renamed = client.patch(
            f"/farms/{farm_id}/assistant/conversations/{conversation_id}",
            json={"title": "  Flock review  "},
        )

    assert listed.status_code == 200
    assert listed.headers["cache-control"] == "no-store"
    assert listed.json()["items"][0]["id"] == str(conversation_id)
    assert retrieved.status_code == 200
    assert retrieved.headers["cache-control"] == "no-store"
    assert retrieved.json()["messages"][0]["content"] == "Explain net profit"
    assert deleted.status_code == 200
    assert deleted.json() == {"deleted": True}
    assert renamed.status_code == 200
    assert renamed.headers["cache-control"] == "no-store"
    assert renamed.json()["title"] == "Flock review"
    assert assistant.renamed_title == "Flock review"
    assert assistant.captured_scope == {"farm_id": farm_id, "user_id": user_id}
