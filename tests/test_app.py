import unittest
from datetime import date

from app import SavingsGoal, ai_categorize, app, parse_date


class FinFlowHelperTests(unittest.TestCase):
    def test_parse_date_accepts_iso_date(self):
        self.assertEqual(parse_date("2026-11-20"), date(2026, 11, 20))

    def test_parse_date_returns_none_for_invalid_input(self):
        self.assertIsNone(parse_date("20/11/2026"))
        self.assertIsNone(parse_date(""))

    def test_keyword_categorization(self):
        self.assertEqual(ai_categorize("Monthly grocery shopping"), "Food")
        self.assertEqual(ai_categorize("Petrol refill"), "Transport")
        self.assertEqual(ai_categorize("Unrecognized purchase"), "Other")

    def test_savings_goal_progress_is_bounded(self):
        goal = SavingsGoal(title="Emergency fund", target=1000, saved=1250)
        self.assertEqual(goal.percent, 100)
        self.assertEqual(goal.remaining, 0)

    def test_savings_goal_handles_zero_target(self):
        goal = SavingsGoal(title="New goal", target=0, saved=0)
        self.assertEqual(goal.percent, 0)
        self.assertEqual(goal.remaining, 0)

    def test_private_routes_redirect_anonymous_users_to_login(self):
        app.config.update(TESTING=True)
        client = app.test_client()
        for path in ("/", "/expense", "/income", "/api/summary"):
            response = client.get(path)
            self.assertEqual(response.status_code, 302, path)
            self.assertIn("/login", response.headers["Location"])


if __name__ == "__main__":
    unittest.main()
