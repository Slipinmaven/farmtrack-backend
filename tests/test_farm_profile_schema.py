import unittest

from pydantic import ValidationError

from app.schemas.farm import FarmCreateRequest, FarmUpdateRequest


class FarmProfileSchemaTests(unittest.TestCase):
    def test_create_accepts_profile_fields_and_positive_capacity(self):
        request = FarmCreateRequest.model_validate(
            {
                "name": "Green Valley Farm",
                "description": "A farm profile description.",
                "location": "Nakuru",
                "phone_number": "+254700000000",
                "email": "hello@example.com",
                "maximum_chicken_capacity": 500,
            }
        )

        self.assertEqual(request.name, "Green Valley Farm")
        self.assertEqual(request.maximum_chicken_capacity, 500)

    def test_farm_name_is_limited_to_150_characters(self):
        with self.assertRaises(ValidationError):
            FarmCreateRequest.model_validate({"name": "F" * 151})

    def test_zero_capacity_is_rejected_for_create_and_update(self):
        with self.assertRaises(ValidationError):
            FarmCreateRequest.model_validate(
                {"name": "Green Valley Farm", "maximum_chicken_capacity": 0}
            )

        with self.assertRaises(ValidationError):
            FarmUpdateRequest.model_validate({"maximum_chicken_capacity": 0})

    def test_capacity_may_be_unset(self):
        request = FarmCreateRequest.model_validate({"name": "Green Valley Farm"})

        self.assertIsNone(request.maximum_chicken_capacity)
