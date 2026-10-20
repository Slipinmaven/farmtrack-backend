import unittest
from uuid import uuid4

from pydantic import ValidationError

from app.schemas.product import ProductCreateRequest, ProductUpdateRequest


class ProductUnitRequestTests(unittest.TestCase):
    def test_new_products_are_not_sellable_by_default(self):
        request = ProductCreateRequest.model_validate(
            {
                "name": "Layer feed",
                "product_type": "feed",
                "product_units": [
                    {
                        "unit_id": uuid4(),
                        "conversion_factor": 1,
                        "is_base_unit": True,
                    }
                ],
            }
        )

        self.assertFalse(request.is_sellable)

    def test_sellable_flag_can_be_set_and_updated(self):
        product_id = uuid4()
        request = ProductCreateRequest.model_validate(
            {
                "name": "Table eggs",
                "product_type": "eggs",
                "is_sellable": True,
                "product_units": [
                    {
                        "unit_id": product_id,
                        "conversion_factor": 1,
                        "is_base_unit": True,
                    }
                ],
            }
        )

        self.assertTrue(request.is_sellable)
        self.assertTrue(ProductUpdateRequest.model_validate({"is_sellable": True}).is_sellable)

    def test_accepts_tray_conversion_to_egg_base_units(self):
        base_unit_id = uuid4()
        tray_unit_id = uuid4()

        request = ProductCreateRequest.model_validate(
            {
                "name": "Eggs",
                "product_type": "eggs",
                "product_units": [
                {
                    "unit_id": base_unit_id,
                    "conversion_factor": 1,
                    "is_base_unit": True,
                },
                {
                    "unit_id": tray_unit_id,
                    "conversion_factor": 30,
                    "is_base_unit": False,
                },
                ],
            }
        )

        self.assertEqual(request.product_units[1].conversion_factor, 30)

    def test_requires_exactly_one_base_unit_with_factor_one(self):
        unit_id = uuid4()
        invalid_definitions = [
            [{"unit_id": unit_id, "conversion_factor": 1}],
            [
                {"unit_id": unit_id, "conversion_factor": 2, "is_base_unit": True}
            ],
        ]

        for product_units in invalid_definitions:
            with self.subTest(product_units=product_units):
                with self.assertRaises(ValidationError):
                    ProductCreateRequest.model_validate(
                        {
                            "name": "Eggs",
                            "product_type": "eggs",
                            "product_units": product_units,
                        }
                    )

    def test_rejects_duplicate_units(self):
        unit_id = uuid4()

        with self.assertRaises(ValidationError):
            ProductCreateRequest.model_validate(
                {
                    "name": "Eggs",
                    "product_type": "eggs",
                    "product_units": [
                    {
                        "unit_id": unit_id,
                        "conversion_factor": 1,
                        "is_base_unit": True,
                    },
                    {"unit_id": unit_id, "conversion_factor": 30},
                    ],
                }
            )


if __name__ == "__main__":
    unittest.main()
