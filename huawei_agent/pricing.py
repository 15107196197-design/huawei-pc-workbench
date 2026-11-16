"""Deterministic CNY quote calculation.  This module never retrieves a price.

Amounts are Decimal values rounded half up after every adjustment.  Evidence,
eligibility and stacking rules must be supplied by a channel adapter; a language
model must not invent them.  See docs/pricing.md for the input contract.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from itertools import product
from urllib.parse import urlparse


ENGINE_VERSION = "1.0.0"
CENT = Decimal("0.01")
ZERO = Decimal("0.00")
MAX_DISCOUNTS = 12
CONDITIONS = {"new_unactivated", "activated", "used", "refurbished", "unknown"}


class RuleError(ValueError):
    """Invalid data, rather than a policy that the engine should guess."""


def _number(value, *, field, money=False, positive=False):
    if isinstance(value, bool) or value is None:
        raise RuleError(f"{field}必须是有效数值")
    try:
        result = Decimal(str(value))
        if not result.is_finite() or result < 0 or (positive and result <= 0):
            raise RuleError(f"{field}必须是{'正' if positive else '非负'}有限数值")
        if money:
            result = result.quantize(CENT, rounding=ROUND_HALF_UP)
            if positive and result <= 0:
                raise RuleError(f"{field}按分取整后必须大于零")
        return result
    except (InvalidOperation, ValueError, OverflowError) as error:
        if isinstance(error, RuleError):
            raise
        raise RuleError(f"{field}不是有效数值") from error


def _money(value):
    return format(value.quantize(CENT, rounding=ROUND_HALF_UP), ".2f")


def _date(value, field):
    if not isinstance(value, str) or not value.strip():
        raise RuleError(f"缺少{field}（需包含时区的 ISO 时间）")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError("timezone missing")
        return parsed.astimezone(timezone.utc)
    except (ValueError, OverflowError) as error:
        raise RuleError(f"{field}不是包含时区的有效 ISO 时间") from error


def _url(value):
    if not isinstance(value, str):
        return False
    try:
        parsed = urlparse(value)
        return parsed.scheme in {"https", "http"} and bool(parsed.hostname)
    except ValueError:
        return False


def _text(value):
    return value.strip() if isinstance(value, str) else ""


def _step(kind, label, before, amount, source_url, **extra):
    return {
        "kind": kind,
        "label": label,
        "before": _money(before),
        "amount": _money(amount),
        "after": _money(before + amount),
        "source_url": source_url,
        **extra,
    }


def _unique_append(items, value):
    if value not in items:
        items.append(value)


def _eligibility(requirements, buyer):
    unknown = []
    for requirement in requirements:
        if requirement == "personal":
            value = None if buyer.get("kind") not in {"personal", "business"} else buyer["kind"] == "personal"
        elif requirement == "business":
            value = None if buyer.get("kind") not in {"personal", "business"} else buyer["kind"] == "business"
        else:
            value = buyer.get(requirement)
        if value is False:
            return False, []
        if value is not True:
            unknown.append(requirement)
    return (None if unknown else True), unknown


def _source_valid(rule, now, label):
    if rule.get("verified") is not True:
        raise RuleError(f"{label}未核实，未计入优惠")
    if not _url(rule.get("source_url")):
        raise RuleError(f"{label}缺少有效来源，未计入优惠")
    if rule.get("observed_at") is not None and _date(rule["observed_at"], f"{label}采集时间") > now:
        raise RuleError(f"{label}采集时间在未来，未计入优惠")
    if rule.get("expires_at") is not None and _date(rule["expires_at"], f"{label}失效时间") <= now:
        raise RuleError(f"{label}已失效，未计入优惠")


def _discounts(raw, buyer, now, issues, assumptions):
    if not isinstance(raw, list):
        raise RuleError("discounts必须是列表")
    if len(raw) > MAX_DISCOUNTS:
        raise RuleError(f"单个报价最多支持{MAX_DISCOUNTS}条优惠；须先清理重复或无关规则")
    result = []
    used_ids = set()
    invalid = False
    for item in raw:
        try:
            if not isinstance(item, dict):
                raise RuleError("优惠规则必须是对象")
            rule_id = _text(item.get("id"))
            label = _text(item.get("label")) or rule_id or "未命名优惠"
            if not rule_id or rule_id in used_ids:
                raise RuleError("优惠id缺失或重复，未计入该规则")
            used_ids.add(rule_id)
            _source_valid(item, now, label)
            kind = item.get("kind")
            if not isinstance(kind, str) or kind not in {"fixed", "percent"}:
                raise RuleError(f"{label}优惠类型无效")
            value = _number(item.get("value"), field=f"{label}优惠值", money=kind == "fixed", positive=True)
            if kind == "percent" and value > 1:
                raise RuleError(f"{label}比例必须大于0且不超过1；0.15表示减免15%")
            threshold = _number(item.get("threshold", 0), field=f"{label}门槛", money=True)
            basis = item.get("base", "current")
            if not isinstance(basis, str) or basis not in {"current", "original"}:
                raise RuleError(f"{label}计算基数无效")
            order = item.get("order", 0)
            if isinstance(order, bool) or not isinstance(order, int):
                raise RuleError(f"{label}计算顺序必须是整数")
            group = item.get("exclusive_group") or ""
            if not isinstance(group, str):
                raise RuleError(f"{label}互斥组必须是字符串")
            requirements = item.get("requires", [])
            if not isinstance(requirements, list) or any(not _text(r) for r in requirements):
                raise RuleError(f"{label}资格条件必须是非空字符串列表")
            eligible, unknown = _eligibility(requirements, buyer)
            if eligible is False:
                _unique_append(issues, f"{label}资格不满足，未计入优惠")
                continue
            if unknown:
                _unique_append(assumptions, f"{label}需确认资格：{'、'.join(unknown)}；未从确定金额中扣减")
            result.append({
                "id": rule_id, "label": label, "kind": kind, "value": value,
                "threshold": threshold, "base": basis, "order": order,
                "exclusive_group": group, "eligible": eligible,
                "source_url": item["source_url"],
            })
        except RuleError as error:
            invalid = True
            _unique_append(issues, str(error))
    return result, invalid


def _prepare_subsidy(raw, buyer, now, issues, assumptions):
    if not raw:
        return None, False
    try:
        if not isinstance(raw, dict):
            raise RuleError("补贴规则必须是对象")
        if buyer.get("kind") == "business":
            _unique_append(issues, "企业采购不计入个人国补")
            return None, False
        if raw.get("eligible") is False or buyer.get("subsidy_eligible") is False:
            _unique_append(issues, "国补资格不满足，未计入优惠")
            return None, False
        _source_valid(raw, now, "国补")
        rate = _number(raw.get("rate"), field="国补比例", positive=True)
        if rate > 1:
            raise RuleError("国补比例必须大于0且不超过1")
        cap = _number(raw.get("cap"), field="国补上限", money=True)
        eligible = raw.get("eligible") is True and buyer.get("subsidy_eligible") is True and buyer.get("kind") == "personal"
        if not eligible:
            _unique_append(assumptions, "个人国补资格、商品参与资格或购买人类型待确认；未从确定金额中扣减")
        return {"rate": rate, "cap": cap, "eligible": eligible, "source_url": raw["source_url"]}, False
    except RuleError as error:
        _unique_append(issues, str(error))
        return None, True


def _prepare_trade(raw, now, issues, assumptions):
    if not raw:
        return None, False
    try:
        if not isinstance(raw, dict):
            raise RuleError("换新规则必须是对象")
        if not _url(raw.get("source_url")):
            raise RuleError("换新报价缺少有效来源，未计入")
        if raw.get("expires_at") is not None and _date(raw["expires_at"], "换新失效时间") <= now:
            raise RuleError("换新报价已失效，未计入")
        if raw.get("observed_at") is not None and _date(raw["observed_at"], "换新采集时间") > now:
            raise RuleError("换新报价采集时间在未来，未计入")
        credit = _number(raw.get("credit", 0), field="旧机回收款", money=True)
        extra = _number(raw.get("extra_discount", 0), field="额外换新优惠", money=True)
        method = raw.get("method", "cash")
        if not isinstance(method, str) or method not in {"cash", "voucher"}:
            raise RuleError("旧机抵扣方式必须为cash或voucher")
        confirmed = raw.get("confirmed") is True
        if not confirmed and (credit or extra):
            _unique_append(assumptions, "旧机回收款或换新优惠尚未确认，未从确定金额中扣减；须以验机结果为准")
        return {"credit": credit, "extra_discount": extra, "method": method,
                "confirmed": confirmed, "source_url": raw["source_url"],
                "voucher_covers_fees": raw.get("voucher_covers_fees") is True}, False
    except RuleError as error:
        _unique_append(issues, str(error))
        return None, True


def _plans(rules):
    """Enumerate zero/one from each exclusive group and each optional rule."""
    groups = {}
    for rule in rules:
        key = ("group", rule["exclusive_group"]) if rule["exclusive_group"] else ("rule", rule["id"])
        groups.setdefault(key, [None]).append(rule)
    for choices in product(*groups.values()):
        yield sorted((rule for rule in choices if rule is not None), key=lambda rule: (rule["order"], rule["id"]))


def _calculate_plan(base, shipping, fee, rules, subsidy, trade, source_url):
    amount = base
    steps = [_step("base", "商品原始报价", ZERO, base, source_url)]
    applied = []
    used_orders = set()
    for rule in rules:
        basis = amount if rule["base"] == "current" else base
        if basis < rule["threshold"]:
            continue
        reduction = rule["value"] if rule["kind"] == "fixed" else (basis * rule["value"]).quantize(CENT, rounding=ROUND_HALF_UP)
        if not reduction:
            continue
        if reduction > amount:
            return None  # Never turn an overlarge coupon into a fabricated zero price.
        if rule["order"] in used_orders:
            return None  # Stacking order is ambiguous.  Do not choose the cheapest permutation.
        used_orders.add(rule["order"])
        steps.append(_step("discount", rule["label"], amount, -reduction, rule["source_url"],
                           rule_id=rule["id"], basis=_money(basis), threshold=_money(rule["threshold"])))
        amount -= reduction
        applied.append(rule["id"])
    if trade and trade["extra_discount"]:
        reduction = trade["extra_discount"]
        if reduction > amount:
            return None
        steps.append(_step("trade_in_extra", "额外换新优惠", amount, -reduction, trade["source_url"]))
        amount -= reduction
    if subsidy:
        reduction = min((amount * subsidy["rate"]).quantize(CENT, rounding=ROUND_HALF_UP), subsidy["cap"])
        steps.append(_step("subsidy", "个人国补", amount, -reduction, subsidy["source_url"],
                           rate=str(subsidy["rate"]), cap=_money(subsidy["cap"])))
        amount -= reduction
    product_amount = amount
    if shipping:
        steps.append(_step("shipping", "运费", amount, shipping, source_url))
        amount += shipping
    if fee:
        steps.append(_step("mandatory_fee", "必付费用", amount, fee, source_url))
        amount += fee
    credit = ZERO
    if trade and trade["method"] == "voucher" and trade["credit"]:
        redemption_limit = amount if trade["voucher_covers_fees"] else product_amount
        credit = min(trade["credit"], redemption_limit)
        steps.append(_step("trade_in_voucher", "旧机回收券抵扣", amount, -credit, trade["source_url"],
                           face_value=_money(trade["credit"])))
        amount -= credit
    checkout = amount
    if trade and trade["method"] == "cash" and trade["credit"]:
        credit = trade["credit"]
        steps.append(_step("trade_in_cash", "独立旧机回收收入", checkout, -credit, trade["source_url"],
                           affects="estimated_cash_outlay"))
    outlay = checkout - credit if trade and trade["method"] == "cash" else checkout
    return {"checkout": checkout, "outlay": outlay, "credit": credit, "steps": steps,
            "applied": applied}


def _optimize(base, shipping, fee, rules, subsidy, trade, source_url):
    best = None
    for plan in _plans(rules):
        result = _calculate_plan(base, shipping, fee, plan, subsidy, trade, source_url)
        if result is not None and (best is None or (result["checkout"], len(result["applied"]), result["applied"]) < (best["checkout"], len(best["applied"]), best["applied"])):
            best = result
    return best


def _quote(offer, buyer, now, region, duplicate_ids, max_age_hours):
    if not isinstance(offer, dict):
        offer = {}
    result = {
        "offer_id": _text(offer.get("id")), "sku_key": _text(offer.get("sku_key")),
        "product_name": _text(offer.get("product_name")), "channel": _text(offer.get("channel")),
        "seller": _text(offer.get("seller")), "condition": offer.get("condition") if isinstance(offer.get("condition"), str) else "unknown",
        "service_key": _text(offer.get("service_key")) or "unspecified", "status": "excluded",
        "checkout_amount": None, "estimated_cash_outlay": None, "trade_in_credit": "0.00",
        "conditional_checkout_amount": None, "conditional_estimated_cash_outlay": None,
        "steps": [], "conditional_steps": [], "applied_discount_ids": [],
        "assumptions": [], "issues": [], "source_url": offer.get("source_url"),
        "observed_at": offer.get("observed_at"), "expires_at": offer.get("expires_at"),
        "currency": "CNY", "region": region,
    }
    issues, assumptions = result["issues"], result["assumptions"]
    try:
        if not result["offer_id"] or result["offer_id"] in duplicate_ids:
            raise RuleError("报价id缺失或重复")
        if not result["sku_key"]:
            raise RuleError("缺少精确SKU，无法比较型号和配置")
        if not result["channel"] or not result["seller"]:
            raise RuleError("缺少渠道或具体销售商家")
        if not isinstance(offer.get("condition", "unknown"), str) or result["condition"] not in CONDITIONS:
            raise RuleError("商品状态无效")
        if offer.get("currency", "CNY") != "CNY":
            raise RuleError("当前引擎仅支持人民币CNY")
        if not _url(offer.get("source_url")):
            raise RuleError("报价缺少有效来源，已剔除")
        if offer.get("price_type", "full") != "full" or offer.get("is_deposit") is True:
            raise RuleError("定金、分期月供或非完整商品价不能作为到手价")
        observed = _date(offer.get("observed_at"), "报价采集时间")
        if observed > now:
            raise RuleError("报价采集时间在未来，已剔除")
        if offer.get("expires_at") is not None:
            if _date(offer["expires_at"], "报价失效时间") <= now:
                raise RuleError("报价已失效，已剔除")
        else:
            assumptions.append("报价有效期未确认")
        if max_age_hours is not None and Decimal(str((now - observed).total_seconds())) > max_age_hours * 3600:
            raise RuleError("报价超过本次任务允许的采集时效，已剔除")
        if offer.get("in_stock") is False:
            raise RuleError("商品无库存，不能作为可购买最低价")
        if offer.get("in_stock") is not True:
            assumptions.append("库存待确认")
        if offer.get("verified") is not True:
            assumptions.append("报价及活动证据尚未核实")
        if not result["product_name"]:
            assumptions.append("产品名称待确认")
        if result["condition"] == "unknown":
            assumptions.append("商品激活、新旧或翻新状态待确认")
        if result["service_key"] == "unspecified":
            assumptions.append("发票、保修等服务条件未归一，不能确认跨商家可比")
        offer_region = _text(offer.get("region"))
        if offer_region and offer_region != region:
            raise RuleError("报价地区与本次任务地区不一致")
        base = _number(offer.get("base_price"), field="商品价", money=True, positive=True)
        shipping = _number(offer.get("shipping", 0), field="运费", money=True)
        fee = _number(offer.get("mandatory_fee", 0), field="必付费用", money=True)
        rules, invalid_discount = _discounts(offer.get("discounts", []), buyer, now, issues, assumptions)
        subsidy, invalid_subsidy = _prepare_subsidy(offer.get("subsidy"), buyer, now, issues, assumptions)
        trade, invalid_trade = _prepare_trade(offer.get("trade_in"), now, issues, assumptions)
        known_rules = [rule for rule in rules if rule["eligible"] is True]
        known_subsidy = subsidy if subsidy and subsidy["eligible"] else None
        known_trade = trade if trade and trade["confirmed"] else None
        confirmed = _optimize(base, shipping, fee, known_rules, known_subsidy, known_trade, offer["source_url"])
        if confirmed is None:
            raise RuleError("换新优惠超过商品金额，规则无法成立，已剔除")
        potential = _optimize(base, shipping, fee, rules, subsidy, trade, offer["source_url"])
        eligible_orders = Counter(rule["order"] for rule in rules)
        for order, count in eligible_orders.items():
            same_order = [rule for rule in rules if rule["order"] == order]
            if count > 1 and (len({rule["exclusive_group"] for rule in same_order}) != 1 or any(not rule["exclusive_group"] for rule in same_order)):
                _unique_append(assumptions, "部分可叠加优惠的计算顺序相同，未组合使用；需明确先后顺序")
        for rule in rules:
            if rule["kind"] == "fixed" and rule["value"] > base:
                _unique_append(issues, f"{rule['label']}超过商品原价，未采用该规则")
                invalid_discount = True
        result.update({
            "status": "conditional" if assumptions or invalid_discount or invalid_subsidy or invalid_trade else "verified",
            "checkout_amount": _money(confirmed["checkout"]),
            "estimated_cash_outlay": _money(confirmed["outlay"]),
            "trade_in_credit": _money(confirmed["credit"]), "steps": confirmed["steps"],
            "applied_discount_ids": confirmed["applied"],
        })
        if potential is not None and (potential["checkout"] < confirmed["checkout"] or potential["outlay"] < confirmed["outlay"]):
            result.update({"conditional_checkout_amount": _money(potential["checkout"]),
                           "conditional_estimated_cash_outlay": _money(potential["outlay"]),
                           "conditional_steps": potential["steps"]})
    except (RuleError, InvalidOperation) as error:
        issues.append(str(error))
    return result


def calculate_quotes(payload: dict) -> dict:
    """Calculate supplied offers, keeping unknown benefits out of firm amounts.

    ``best`` compares only verified, in-stock quotes with identical SKU, product
    condition and service_key.  Its primary winner uses checkout amount; a
    separate cash-outlay winner keeps independently paid old-device cash clear.
    """
    output = {"quotes": [], "best": [], "warnings": [], "engine_version": ENGINE_VERSION}
    if not isinstance(payload, dict):
        output["warnings"].append("输入必须是对象")
        return output
    try:
        now = _date(payload["now"], "计算时间") if payload.get("now") is not None else datetime.now(timezone.utc)
        region = _text(payload.get("region"))
        if not region:
            raise RuleError("必须明确报价地区")
        buyer = payload.get("buyer", {})
        if not isinstance(buyer, dict):
            raise RuleError("buyer必须是对象")
        if buyer.get("kind") is not None and (not isinstance(buyer["kind"], str) or buyer["kind"] not in {"personal", "business"}):
            raise RuleError("购买人类型必须为personal或business")
        offers = payload.get("offers", [])
        if not isinstance(offers, list):
            raise RuleError("offers必须是列表")
        max_age_hours = None
        if payload.get("max_age_hours") is not None:
            max_age_hours = _number(payload["max_age_hours"], field="允许采集时效", positive=True)
        counts = Counter(_text(offer.get("id")) for offer in offers if isinstance(offer, dict))
        duplicates = {offer_id for offer_id, count in counts.items() if count > 1}
        output["quotes"] = [_quote(offer, buyer, now, region, duplicates, max_age_hours) for offer in offers]
        groups = defaultdict(list)
        for quote in output["quotes"]:
            groups[(quote["sku_key"], quote["condition"], quote["service_key"])].append(quote)
        for (sku, condition, service), quotes in sorted(groups.items()):
            verified = [quote for quote in quotes if quote["status"] == "verified"]
            if not verified:
                continue
            minimum = min(Decimal(quote["checkout_amount"]) for quote in verified)
            cash_minimum = min(Decimal(quote["estimated_cash_outlay"]) for quote in verified)
            winners = [quote for quote in verified if Decimal(quote["checkout_amount"]) == minimum]
            output["best"].append({
                "sku_key": sku, "condition": condition, "service_key": service,
                "offer_id": winners[0]["offer_id"], "offer_ids": [quote["offer_id"] for quote in winners],
                "checkout_amount": _money(minimum),
                "estimated_cash_outlay": winners[0]["estimated_cash_outlay"],
                "lowest_cash_outlay": _money(cash_minimum),
                "lowest_cash_outlay_offer_ids": [quote["offer_id"] for quote in verified if Decimal(quote["estimated_cash_outlay"]) == cash_minimum],
                "conditional_offer_ids": [quote["offer_id"] for quote in quotes if quote["status"] == "conditional"],
                "ranking_basis": "checkout_amount", "verified_offer_count": len(verified),
                "scope": "仅限本次输入中已核实、同SKU、同商品状态及同服务条件的报价",
            })
        output["calculated_at"] = now.isoformat()
        if any(quote["status"] != "verified" for quote in output["quotes"]):
            output["warnings"].append("条件报价和已剔除报价未参加已核实最低价比较；请查看各报价的待确认项与问题")
        if not output["best"] and offers:
            output["warnings"].append("当前没有满足条件的已核实可比报价，不能给出确定最低价")
        output["warnings"].append("规则引擎只计算输入的证据和规则；未连接实时渠道、未验证来源网页真实性，也不代表全网最低价")
    except RuleError as error:
        output["warnings"].append(str(error))
    return output
