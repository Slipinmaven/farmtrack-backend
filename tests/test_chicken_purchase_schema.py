import unittest
from datetime import date, datetime, time
from decimal import Decimal
from uuid import uuid4

from pydantic import ValidationError

from app.schemas.chicken_purchase import (
    ChickenReceiptItemRequest,
    ChickenPurchaseRequest,
    ChickenPurchaseResponse,
    PurchaseReceiptCreateRequest,
    PaymentCreate,
)
from app.schemas.enums import TransactionStatus, TransactionType
from app.schemas.enums import ChickenType


class ChickenPurchaseSchemaTests(unittest.TestCase):
    def test_accepts_valid_purchase_with_multiple_payments(self):
        payload = {
            "supplier_id": str(uuid4()),
            "transaction_date": "2026-10-09",
            "items": [
                {
                    "product_id": str(uuid4()),
                    "chicken_type": ChickenType.LAYERS,
                    "unit_id": str(uuid4()),
                    "quantity": 25,
                    "unit_price": "350.00",
                },
                {
                    "product_id": str(uuid4()),
                    "chicken_type": ChickenType.BROILER,
                    "unit_id": str(uuid4()),
                    "quantity": 10,
                    "unit_price": "50.00",
                },
            ],
            "payments": [
                {
                    "amount": "500.00",
                    "payment_date": "2026-10-09",
                    "payment_method": "cash",
                },
                {
                    "amount": "300.00",
                    "payment_date": "2026-10-09",
                    "payment_method": "mpesa",
                },
            ],
        }

        purchase = ChickenPurchaseRequest.model_validate(payload)

        self.assertEqual(len(purchase.items), 2)
        self.assertEqual(purchase.items[0].quantity, 25)
        self.assertEqual(purchase.items[0].unit_price, Decimal("350.00"))
        self.assertEqual(purchase.transaction_date, date(2026, 10, 9))
        self.assertEqual(len(purchase.payments), 2)
        self.assertEqual(purchase.payments[0].amount, Decimal("500.00"))
        self.assertEqual(purchase.payments[1].amount, Decimal("300.00"))

    def test_rejects_non_positive_purchase_quantity_and_negative_price(self):
        base = {
            "transaction_date": "2026-10-09",
            "items": [
                {
                    "product_id": str(uuid4()),
                    "chicken_type": ChickenType.LAYERS,
                    "unit_id": str(uuid4()),
                    "quantity": 1,
                    "unit_price": "0",
                }
            ],
        }

        for invalid_values in (
            {"items": [{**base["items"][0], "quantity": 0}]},
            {"items": [{**base["items"][0], "unit_price": "-0.01"}]},
        ):
            with self.subTest(invalid_values=invalid_values):
                with self.assertRaises(ValidationError):
                    ChickenPurchaseRequest.model_validate({**base, **invalid_values})

    def test_purchase_rejects_client_transaction_type_and_conversion_factor(self):
        base_item = {
            "product_id": str(uuid4()),
            "chicken_type": ChickenType.LAYERS,
            "unit_id": str(uuid4()),
            "quantity": 1,
            "unit_price": "1.00",
        }
        with self.assertRaises(ValidationError):
            ChickenPurchaseRequest.model_validate(
                {
                    "transaction_date": "2026-10-09",
                    "transaction_type": "sale",
                    "items": [base_item],
                }
            )
        with self.assertRaises(ValidationError):
            ChickenPurchaseRequest.model_validate(
                {
                    "transaction_date": "2026-10-09",
                    "items": [{**base_item, "conversion_factor": "50"}],
                }
            )

    def test_rejects_duplicate_block_allocations(self):
        block_id = str(uuid4())

        with self.assertRaises(ValidationError):
            ChickenReceiptItemRequest.model_validate(
                {
                    "transaction_item_id": str(uuid4()),
                    "quantity_received": 2,
                    "batch_assignment": {
                        "action": "CREATE",
                        "new_batch": {
                            "name": "New chicks",
                            "chicken_type": "layers",
                        },
                    },
                    "block_allocations": [
                        {"block_id": block_id, "quantity": 1},
                        {"block_id": block_id, "quantity": 1},
                    ],
                }
            )

    def test_receipt_request_accepts_partial_delivery_and_allocation(self):
        receipt = PurchaseReceiptCreateRequest.model_validate(
            {
                "transaction_id": str(uuid4()),
                "received_date": "2026-10-09",
                "received_time": "09:30:00",
                "items": [
                    {
                        "transaction_item_id": str(uuid4()),
                        "quantity_received": 10,
                        "batch_assignment": {
                            "action": "CREATE",
                            "new_batch": {
                                "name": "New chicks",
                                "chicken_type": "layers",
                            },
                        },
                        "block_allocations": [
                            {"block_id": str(uuid4()), "quantity": 10}
                        ],
                    }
                ],
            }
        )

        self.assertEqual(receipt.received_time, time(9, 30))
        self.assertEqual(receipt.items[0].quantity_received, 10)

    def test_rejects_incorrect_block_allocation_total(self):
        with self.assertRaises(ValidationError):
            ChickenReceiptItemRequest.model_validate(
                {
                    "transaction_item_id": str(uuid4()),
                    "quantity_received": 2,
                    "batch_assignment": {
                        "action": "USE_EXISTING",
                        "batch_id": str(uuid4()),
                    },
                    "block_allocations": [
                        {"block_id": str(uuid4()), "quantity": 1}
                    ],
                }
            )

    def test_rejects_extra_batch_assignment_fields(self):
        with self.assertRaises(ValidationError):
            ChickenReceiptItemRequest.model_validate(
                {
                    "transaction_item_id": str(uuid4()),
                    "quantity_received": 1,
                    "batch_assignment": {
                        "action": "CREATE",
                        "batch_id": str(uuid4()),
                        "new_batch": {
                            "name": "New chicks",
                            "chicken_type": "layers",
                        },
                    },
                    "block_allocations": [
                        {"block_id": str(uuid4()), "quantity": 1}
                    ],
                }
            )

    def test_new_batch_age_requires_age_unit(self):
        with self.assertRaises(ValidationError):
            ChickenReceiptItemRequest.model_validate(
                {
                    "transaction_item_id": str(uuid4()),
                    "quantity_received": 1,
                    "batch_assignment": {
                        "action": "CREATE",
                        "new_batch": {
                            "name": "New chicks",
                            "chicken_type": "layers",
                            "age": 14,
                        },
                    },
                    "block_allocations": [
                        {"block_id": str(uuid4()), "quantity": 1}
                    ],
                }
            )

    def test_new_batch_rejects_negative_age(self):
        with self.assertRaises(ValidationError):
            ChickenReceiptItemRequest.model_validate(
                {
                    "transaction_item_id": str(uuid4()),
                    "quantity_received": 1,
                    "batch_assignment": {
                        "action": "CREATE",
                        "new_batch": {
                            "name": "New chicks",
                            "chicken_type": "layers",
                            "age": -1,
                            "age_unit": "days",
                        },
                    },
                    "block_allocations": [
                        {"block_id": str(uuid4()), "quantity": 1}
                    ],
                }
            )

    def test_payment_amount_must_be_positive_and_currency_precision_limited(self):
        base = {
            "payment_date": "2026-10-09",
            "payment_method": "cash",
        }

        for amount in ("0", "1.001"):
            with self.subTest(amount=amount):
                with self.assertRaises(ValidationError):
                    PaymentCreate.model_validate({**base, "amount": amount})

    def test_response_accepts_persisted_purchase_fields(self):
        now = datetime.now()
        response = ChickenPurchaseResponse.model_validate(
            {
                "id": uuid4(),
                "farm_id": uuid4(),
                "contact_id": None,
                "items": [
                    {
                        "id": uuid4(),
                        "product_id": uuid4(),
                        "chicken_type": ChickenType.LAYERS,
                        "unit_id": uuid4(),
                        "quantity": "25.000",
                        "conversion_factor": "1.000",
                        "ordered_base_quantity": "25.000",
                        "unit_price": "350.00",
                        "subtotal_amount": "8750.00",
                        "discount_amount": "0.00",
                        "total_amount": "8750.00",
                        "notes": None,
                        "quantity_received": "0",
                        "quantity_remaining": "25.000",
                    }
                ],
                "payments": [],
                "transaction_type": TransactionType.PURCHASE,
                "transaction_total": "8750.00",
                "amount_paid": "0.00",
                "balance_due": "8750.00",
                "credit_balance": "0.00",
                "transaction_date": "2026-10-09",
                "status": TransactionStatus.COMPLETED,
                "reference_number": None,
                "notes": None,
                "created_at": now,
                "updated_at": now,
            }
        )

        self.assertEqual(response.transaction_total, Decimal("8750.00"))
        self.assertEqual(response.balance_due, Decimal("8750.00"))
        self.assertEqual(response.credit_balance, Decimal("0.00"))


if __name__ == "__main__":
    unittest.main()
