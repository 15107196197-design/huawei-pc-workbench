"""Synthetic fixtures only: these are not real products or live channel prices."""

from copy import deepcopy
from decimal import Decimal
import unittest

from huawei_agent.pricing import calculate_quotes


NOW = "2026-10-19T12:00:00+08:00"
SOURCE = "https://example.invalid/fixture-only"


def offer(**changes):
    result = {
        "id": "fixture-a", "channel": "测试渠道", "seller": "测试商家",
        "sku_key": "SYNTHETIC-PC-16-512", "product_name": "虚构规则测试产品",
        "condition": "new_unactivated", "service_key": "fixture-invoice-warranty-1y",
        "base_price": "1000.00", "shipping": "0", "mandatory_fee": "0", "currency": "CNY",
        "source_url": SOURCE, "observed_at": "2026-10-19T11:00:00+08:00",
        "expires_at": "2026-10-19T18:00:00+08:00", "in_stock": True, "verified": True,
        "discounts": [],
    }
    result.update(changes)
    return result


def discount(**changes):
    result = {"id": "coupon", "label": "测试满减", "kind": "fixed", "value": "100",
              "threshold": "1000", "base": "current", "order": 1,
              "exclusive_group": "", "requires": [], "verified": True, "source_url": SOURCE}
    result.update(changes)
    return result


def subsidy(**changes):
    result = {"verified": True, "rate": ".15", "cap": "1500", "eligible": True, "source_url": SOURCE}
    result.update(changes)
    return result


def trade(**changes):
    result = {"credit": "200", "extra_discount": "100", "confirmed": True,
              "method": "cash", "source_url": SOURCE}
    result.update(changes)
    return result


def calculate(*offers, buyer=None, **extra):
    payload = {"region": "杭州", "buyer": {"kind": "personal", "student": False, "subsidy_eligible": True},
               "offers": list(offers or [offer()]), "now": NOW}
    if buyer is not None:
        payload["buyer"] = buyer
    payload.update(extra)
    return calculate_quotes(payload)


class PricingTests(unittest.TestCase):
    def test_verified_base_quote_and_two_decimal_amounts(self):
        result = calculate(offer(base_price=1000, shipping=10, mandatory_fee="2.345"))
        self.assertEqual(result["quotes"][0]["checkout_amount"], "1012.35")
        self.assertEqual(result["quotes"][0]["status"], "verified")
        self.assertEqual(result["best"][0]["offer_id"], "fixture-a")

    def test_decimal_rounding_half_up_per_step(self):
        result = calculate(offer(base_price="100.05", discounts=[discount(kind="percent", value=".1", threshold=0)]))
        quote = result["quotes"][0]
        self.assertEqual(quote["steps"][1]["amount"], "-10.01")
        self.assertEqual(quote["checkout_amount"], "90.04")

    def test_exclusive_group_enumerates_instead_of_stacking(self):
        coupons = [discount(id="fixed", value=150, exclusive_group="one"),
                   discount(id="percent", kind="percent", value=".1", exclusive_group="one")]
        quote = calculate(offer(discounts=coupons))["quotes"][0]
        self.assertEqual(quote["checkout_amount"], "850.00")
        self.assertEqual(quote["applied_discount_ids"], ["fixed"])

    def test_threshold_is_checked_at_the_declared_order(self):
        coupons = [discount(id="first", value=100, threshold=0, order=1),
                   discount(id="second", value=200, threshold=1000, order=2)]
        quote = calculate(offer(discounts=coupons))["quotes"][0]
        # Skipping the first coupon preserves eligibility for the better second coupon.
        self.assertEqual(quote["checkout_amount"], "800.00")
        self.assertEqual(quote["applied_discount_ids"], ["second"])

    def test_original_price_threshold_is_distinct_from_current(self):
        coupons = [discount(id="first", value=100, threshold=0, order=1),
                   discount(id="second", value=200, threshold=1000, base="original", order=2)]
        self.assertEqual(calculate(offer(discounts=coupons))["quotes"][0]["checkout_amount"], "700.00")

    def test_percent_can_explicitly_use_original_base(self):
        coupons = [discount(id="first", value=100, threshold=0, order=1),
                   discount(id="second", kind="percent", value=".2", threshold=0, base="original", order=2)]
        self.assertEqual(calculate(offer(discounts=coupons))["quotes"][0]["checkout_amount"], "700.00")

    def test_known_student_eligibility(self):
        quote = calculate(offer(discounts=[discount(requires=["student"])]),
                          buyer={"kind": "personal", "student": True})["quotes"][0]
        self.assertEqual(quote["checkout_amount"], "900.00")
        self.assertEqual(quote["status"], "verified")

    def test_unknown_student_is_not_a_definite_discount(self):
        result = calculate(offer(discounts=[discount(requires=["student"])]),
                           buyer={"kind": "personal", "student": None})
        quote = result["quotes"][0]
        self.assertEqual(quote["checkout_amount"], "1000.00")
        self.assertEqual(quote["conditional_checkout_amount"], "900.00")
        self.assertEqual(quote["status"], "conditional")
        self.assertEqual(result["best"], [])

    def test_false_eligibility_does_not_apply_or_claim_potential(self):
        quote = calculate(offer(discounts=[discount(requires=["student"])]))["quotes"][0]
        self.assertEqual(quote["checkout_amount"], "1000.00")
        self.assertIsNone(quote["conditional_checkout_amount"])

    def test_custom_missing_qualification_is_unknown(self):
        quote = calculate(offer(discounts=[discount(requires=["coupon_owned"]) ]))["quotes"][0]
        self.assertEqual(quote["status"], "conditional")
        self.assertEqual(quote["checkout_amount"], "1000.00")

    def test_subsidy_rate_and_cap_are_supplied_not_assumed(self):
        quote = calculate(offer(base_price=20000, subsidy=subsidy()))["quotes"][0]
        self.assertEqual(quote["checkout_amount"], "18500.00")
        self.assertEqual(quote["steps"][1]["amount"], "-1500.00")

    def test_unknown_subsidy_qualification(self):
        quote = calculate(offer(subsidy=subsidy()), buyer={"kind": "personal", "subsidy_eligible": None})["quotes"][0]
        self.assertEqual(quote["checkout_amount"], "1000.00")
        self.assertEqual(quote["conditional_checkout_amount"], "850.00")
        self.assertEqual(quote["status"], "conditional")

    def test_unknown_product_subsidy_participation(self):
        quote = calculate(offer(subsidy=subsidy(eligible=None)))["quotes"][0]
        self.assertEqual(quote["checkout_amount"], "1000.00")
        self.assertEqual(quote["conditional_checkout_amount"], "850.00")

    def test_business_cannot_get_personal_subsidy(self):
        quote = calculate(offer(subsidy=subsidy()), buyer={"kind": "business", "subsidy_eligible": True})["quotes"][0]
        self.assertEqual(quote["checkout_amount"], "1000.00")
        self.assertIsNone(quote["conditional_checkout_amount"])
        self.assertTrue(any("企业采购" in issue for issue in quote["issues"]))

    def test_cash_trade_in_is_subtracted_exactly_once_and_separate_from_checkout(self):
        quote = calculate(offer(discounts=[discount(kind="percent", value=".15", threshold=0)],
                                shipping=10, trade_in=trade(), subsidy=subsidy()))["quotes"][0]
        self.assertEqual(quote["checkout_amount"], "647.50")
        self.assertEqual(quote["estimated_cash_outlay"], "447.50")
        self.assertEqual(quote["trade_in_credit"], "200.00")
        self.assertEqual([step["kind"] for step in quote["steps"]],
                         ["base", "discount", "trade_in_extra", "subsidy", "shipping", "trade_in_cash"])

    def test_voucher_trade_in_is_not_subtracted_twice(self):
        quote = calculate(offer(trade_in=trade(method="voucher")))["quotes"][0]
        self.assertEqual(quote["checkout_amount"], "700.00")
        self.assertEqual(quote["estimated_cash_outlay"], "700.00")

    def test_voucher_cannot_implicitly_cover_shipping_or_exceed_product(self):
        quote = calculate(offer(base_price=100, shipping=20, trade_in=trade(credit=200, extra_discount=0, method="voucher")))["quotes"][0]
        self.assertEqual(quote["checkout_amount"], "20.00")
        self.assertEqual(quote["trade_in_credit"], "100.00")

    def test_unconfirmed_trade_in_is_only_potential(self):
        quote = calculate(offer(trade_in=trade(confirmed=False)))["quotes"][0]
        self.assertEqual(quote["checkout_amount"], "1000.00")
        self.assertEqual(quote["estimated_cash_outlay"], "1000.00")
        self.assertEqual(quote["conditional_checkout_amount"], "900.00")
        self.assertEqual(quote["conditional_estimated_cash_outlay"], "700.00")

    def test_unknown_stock_is_conditional_and_out_of_stock_is_excluded(self):
        result = calculate(offer(in_stock=None), offer(id="b", in_stock=False))
        self.assertEqual([quote["status"] for quote in result["quotes"]], ["conditional", "excluded"])
        self.assertEqual(result["best"], [])

    def test_expired_and_future_observations_are_excluded(self):
        result = calculate(offer(expires_at=NOW), offer(id="b", observed_at="2026-10-20T00:00:00+08:00"))
        self.assertTrue(all(quote["status"] == "excluded" for quote in result["quotes"]))
        self.assertTrue(all(quote["checkout_amount"] is None for quote in result["quotes"]))

    def test_timezone_is_required_and_offsets_are_normalized(self):
        result = calculate(offer(observed_at="2026-10-19T03:00:00Z"),
                           offer(id="b", observed_at="2026-10-19T11:00:00"))
        self.assertEqual([quote["status"] for quote in result["quotes"]], ["verified", "excluded"])

    def test_missing_source_deposit_monthly_price_are_excluded(self):
        result = calculate(offer(source_url=""), offer(id="b", price_type="deposit"), offer(id="c", price_type="monthly_installment"))
        self.assertTrue(all(quote["status"] == "excluded" for quote in result["quotes"]))

    def test_malformed_or_zero_money_cannot_become_a_fake_low_price(self):
        for value in ["0", "0.001", "NaN", "Infinity", "-1", True, "invalid", "1e99999"]:
            with self.subTest(value=value):
                quote = calculate(offer(base_price=value))["quotes"][0]
                self.assertEqual(quote["status"], "excluded")
                self.assertIsNone(quote["checkout_amount"])

    def test_invalid_oversized_coupon_is_not_clamped_into_zero(self):
        quote = calculate(offer(discounts=[discount(value=1001)]))["quotes"][0]
        self.assertEqual(quote["checkout_amount"], "1000.00")
        self.assertEqual(quote["status"], "conditional")

    def test_unverified_or_unsourced_discounts_are_not_applied(self):
        for changes in [{"verified": False}, {"source_url": ""}]:
            with self.subTest(changes=changes):
                quote = calculate(offer(discounts=[discount(**changes)]))["quotes"][0]
                self.assertEqual(quote["checkout_amount"], "1000.00")
                self.assertEqual(quote["status"], "conditional")

    def test_expired_discount_does_not_invalidate_base_price(self):
        quote = calculate(offer(discounts=[discount(expires_at=NOW)]))["quotes"][0]
        self.assertEqual(quote["checkout_amount"], "1000.00")
        self.assertTrue(any("失效" in issue for issue in quote["issues"]))

    def test_grouping_does_not_mix_sku_condition_or_service(self):
        result = calculate(offer(), offer(id="b", sku_key="different-sku", base_price=500),
                           offer(id="c", condition="used", base_price=400),
                           offer(id="d", service_key="different-warranty", base_price=800))
        self.assertEqual(len(result["best"]), 4)

    def test_best_ignores_cheaper_conditional_price_and_keeps_ties(self):
        result = calculate(offer(), offer(id="b"), offer(id="c", base_price=100, verified=False))
        self.assertEqual(result["best"][0]["checkout_amount"], "1000.00")
        self.assertEqual(result["best"][0]["offer_ids"], ["fixture-a", "b"])
        self.assertEqual(result["best"][0]["conditional_offer_ids"], ["c"])

    def test_checkout_and_cash_outlay_winners_are_reported_separately(self):
        result = calculate(offer(base_price=900), offer(id="b", trade_in=trade(extra_discount=0)))
        group = result["best"][0]
        self.assertEqual(group["offer_id"], "fixture-a")
        self.assertEqual(group["lowest_cash_outlay_offer_ids"], ["b"])
        self.assertEqual(group["lowest_cash_outlay"], "800.00")

    def test_missing_service_or_product_condition_cannot_claim_comparable_lowest(self):
        result = calculate(offer(service_key=""), offer(id="b", condition="unknown"))
        self.assertTrue(all(quote["status"] == "conditional" for quote in result["quotes"]))
        self.assertEqual(result["best"], [])

    def test_duplicate_quote_ids_are_all_excluded(self):
        result = calculate(offer(), offer(base_price=20))
        self.assertTrue(all(quote["status"] == "excluded" for quote in result["quotes"]))

    def test_same_order_stackable_rules_are_not_reordered_for_cheapest_result(self):
        quote = calculate(offer(discounts=[discount(id="a", value=100), discount(id="b", value=200)]))["quotes"][0]
        self.assertEqual(quote["checkout_amount"], "800.00")
        self.assertEqual(quote["status"], "conditional")

    def test_explicit_freshness_limit_excludes_old_data(self):
        self.assertEqual(calculate(offer(), max_age_hours="0.5")["quotes"][0]["status"], "excluded")

    def test_region_mismatch_and_non_cny_are_excluded(self):
        result = calculate(offer(region="上海"), offer(id="b", currency="USD"))
        self.assertTrue(all(quote["status"] == "excluded" for quote in result["quotes"]))

    def test_traceable_arithmetic_reconciles_every_cent(self):
        quote = calculate(offer(base_price="999.99", shipping="8.50", mandatory_fee="2.10",
                                discounts=[discount(kind="percent", value=".123", threshold=0)],
                                subsidy=subsidy(rate=".17"), trade_in=trade(method="voucher")))["quotes"][0]
        running = Decimal("0")
        for step in quote["steps"]:
            self.assertEqual(Decimal(step["before"]), running)
            running += Decimal(step["amount"])
            self.assertEqual(Decimal(step["after"]), running)
            self.assertTrue(step["source_url"])
        self.assertEqual(running, Decimal(quote["checkout_amount"]))

    def test_input_is_not_mutated(self):
        payload = {"region": "杭州", "buyer": {"kind": "personal"}, "offers": [offer()], "now": NOW}
        original = deepcopy(payload)
        calculate_quotes(payload)
        self.assertEqual(payload, original)

    def test_malformed_public_inputs_fail_closed(self):
        for payload in [None, [], {"offers": []}, {"region": "杭州", "buyer": []},
                        {"region": "杭州", "buyer": {"kind": []}}, {"region": "杭州", "offers": {}},
                        {"region": "杭州", "now": "tomorrow"}]:
            with self.subTest(payload=payload):
                result = calculate_quotes(payload)
                self.assertEqual(result["best"], [])
                self.assertTrue(result["warnings"])
        result = calculate(offer(condition=[]), offer(id="b", discounts=[discount(kind=[])]))
        self.assertEqual(result["quotes"][0]["status"], "excluded")
        self.assertEqual(result["quotes"][1]["status"], "conditional")

    def test_discount_count_limit_is_explicit_not_silently_truncated(self):
        quote = calculate(offer(discounts=[discount(id=str(i), order=i) for i in range(13)]))["quotes"][0]
        self.assertEqual(quote["status"], "excluded")
        self.assertTrue(any("最多" in issue for issue in quote["issues"]))


if __name__ == "__main__":
    unittest.main()
