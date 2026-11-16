"""Narrow visual-proof reconciliation boundaries; no HTTP or model calls."""

import unittest

from huawei_agent.validation import reconcile_visual_evidence


class VisualEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.pixel_issue = {"category": "product_pixels", "message": "产品主体疑似改变"}
        self.layout_issue = {"category": "layout", "message": "正文被遮挡"}
        self.proof = {
            "verified": True,
            "product_pixels_verified": True,
            "text_rendered": {
                "title": "合成核验测试",
                "sections": [{"points": ["内存 16 GB / 32 GB", "报价 5000 元"]}],
            },
        }

    def test_pixel_proof_only_resolves_product_pixels_category(self):
        result = reconcile_visual_evidence(
            {"passed": False, "issues": [self.pixel_issue, self.layout_issue]}, self.proof
        )
        self.assertFalse(result["passed"])
        self.assertEqual(result["issues"], [self.layout_issue])
        self.assertEqual(
            [item["issue"] for item in result["literal_resolutions"]], [self.pixel_issue]
        )
        pixel_only = reconcile_visual_evidence(
            {"passed": False, "issues": [self.pixel_issue]}, self.proof
        )
        self.assertTrue(pixel_only["passed"])
        self.assertEqual(pixel_only["issues"], [])

    def test_only_whitespace_difference_with_nested_rendered_text_is_resolved(self):
        issue = {
            "category": "text",
            "expected": "内存 16 GB / 32 GB",
            "observed": "内存\n16GB/\t32 GB",
        }
        result = reconcile_visual_evidence({"passed": False, "issues": [issue]}, self.proof)
        self.assertTrue(result["passed"])
        self.assertEqual(result["issues"], [])
        self.assertEqual(result["literal_resolutions"][0]["issue"], issue)

    def test_real_text_changes_or_unproven_rendering_remain_blocked(self):
        cases = [
            ("内存 16 GB / 32 GB", "内存 32 GB / 32 GB", self.proof),
            ("报价 5000 元", "报价 500 元", self.proof),
            ("内存 16 GB / 32 GB", "内存 16 GB、32 GB", self.proof),
            ("内存 16 GB / 32 GB", "内存16GB/32GB", self.proof | {"text_rendered": []}),
            ("屏幕 120 Hz", "屏幕120Hz", self.proof),
            (" \n\t", "", self.proof),
        ]
        for expected, observed, proof in cases:
            with self.subTest(expected=expected, observed=observed, proof=proof):
                issue = {"category": "text", "expected": expected, "observed": observed}
                result = reconcile_visual_evidence({"passed": False, "issues": [issue]}, proof)
                self.assertFalse(result["passed"])
                self.assertEqual(result["issues"], [issue])
                self.assertNotIn("literal_resolutions", result)

    def test_missing_failed_or_non_boolean_proof_does_not_waive_issues(self):
        text_issue = {"category": "text", "expected": "报价 5000 元", "observed": "报价5000元"}
        for proof in [{}, self.proof | {"verified": False}, self.proof | {"verified": 1}]:
            with self.subTest(proof=proof):
                issues = [self.pixel_issue, text_issue]
                result = reconcile_visual_evidence({"passed": False, "issues": issues}, proof)
                self.assertFalse(result["passed"])
                self.assertEqual(result["issues"], issues)
        for pixels_verified in [False, None, 1]:
            with self.subTest(product_pixels_verified=pixels_verified):
                result = reconcile_visual_evidence(
                    {"passed": False, "issues": [self.pixel_issue]},
                    self.proof | {"product_pixels_verified": pixels_verified},
                )
                self.assertFalse(result["passed"])
                self.assertEqual(result["issues"], [self.pixel_issue])

    def test_legacy_or_remaining_issues_override_passed_true(self):
        for issues in [
            ["产品主体疑似改变"],
            "布局遮挡正文",
            [self.layout_issue],
            [{"category": "text", "expected": "报价5000元", "observed": "报价500元"}],
        ]:
            with self.subTest(issues=issues):
                result = reconcile_visual_evidence({"passed": True, "issues": issues}, self.proof)
                self.assertFalse(result["passed"])
                self.assertEqual(result["issues"], issues if isinstance(issues, list) else [issues])
        declined = reconcile_visual_evidence({"passed": False, "issues": []}, self.proof)
        self.assertFalse(declined["passed"])


if __name__ == "__main__":
    unittest.main()
