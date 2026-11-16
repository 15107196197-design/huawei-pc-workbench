import unittest

from huawei_agent.validation import reconcile_literal_evidence


class LiteralEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.facts = [{"id": "storage", "category": "存储", "excerpt": "512 GB / 1 TB", "verified": True}]
        self.draft = {"title": "配置", "body": "存储提供512 GB/1 TB。", "fact_ids": ["storage"]}

    def test_false_objection_to_literal_fact_is_resolved_with_record(self):
        result = reconcile_literal_evidence({"passed": False, "issues": [{"quote": "存储提供512 GB/1 TB。", "reason": "漏了512GB"}]}, self.draft, self.facts)
        self.assertTrue(result["passed"])
        self.assertEqual(result["issues"], [])
        self.assertEqual(result["literal_resolutions"][0]["fact_id"], "storage")

    def test_negative_or_changed_value_is_not_waived(self):
        for quote in ["存储不提供512 GB/1 TB。", "存储提供256 GB/1 TB。"]:
            draft = self.draft | {"body": quote}
            result = reconcile_literal_evidence({"passed": False, "issues": [{"quote": quote}]}, draft, self.facts)
            self.assertFalse(result["passed"])

    def test_omitted_qualifier_cannot_be_resolved_by_substring(self):
        facts = [{"id": "storage", "category": "存储", "excerpt": "512 GB / 1 TB，仅部分配置", "verified": True}]
        result = reconcile_literal_evidence({"passed": False, "issues": [{"quote": self.draft["body"]}]}, self.draft, facts)
        self.assertFalse(result["passed"])


if __name__ == "__main__":
    unittest.main()
