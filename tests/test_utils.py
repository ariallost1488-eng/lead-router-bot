import unittest

from utils import extract_all_object_codes, extract_object_code, format_lead_message


class LeadUtilityTests(unittest.TestCase):
    def test_extracts_supported_listing_urls_and_plain_codes(self):
        self.assertEqual(
            extract_object_code("https://www.cian.ru/sale/suburban/335208747/?from=search"),
            "335208747",
        )
        self.assertEqual(
            extract_object_code("https://www.avito.ru/samara/kvartiry/2-komnatnaya_8121536203"),
            "8121536203",
        )
        self.assertEqual(extract_object_code("335208747"), "335208747")

    def test_does_not_treat_phone_numbers_or_unrelated_urls_as_object_codes(self):
        self.assertIsNone(extract_object_code("Мой телефон +79991234567"))
        self.assertIsNone(extract_object_code("https://example.com/property/335208747"))

    def test_extracts_unique_codes_in_message_order(self):
        self.assertEqual(
            extract_all_object_codes(
                "https://cian.ru/sale/suburban/335208747/, "
                "8121536203 https://avito.ru/samara/listing/8121536203"
            ),
            ["335208747", "8121536203"],
        )

    def test_short_fallback_keeps_agency_and_bounds_untrusted_fields(self):
        text = format_lead_message(
            {"ad_title": "Property" * 2000, "customer_name": "Customer" * 2000},
            agency_name="Test Agency",
        )

        self.assertIn("Test Agency", text)
        self.assertLessEqual(len(text), 3900)


if __name__ == "__main__":
    unittest.main()
