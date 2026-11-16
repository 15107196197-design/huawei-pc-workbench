# 报价规则引擎 v1 契约

`huawei_agent.pricing.calculate_quotes(payload: dict) -> dict` 是离线、确定性计算器。它不采价、不调用模型、不确认网页真实性，没有内置真实商品、价格、补贴比例或渠道优惠。

调用方必须先核实政策、活动、商家、商品配置与资格，再填写规则。`verified: true` 是调用方的证据审核声明，不能由内容模型自行设定。界面展示来源链接不等于已证实该价格可下单。

## 输入

主契约沿用项目方案，以下是完整的必要说明。

- `region`：明确地区，如 `杭州`。有 `offer.region` 时必须相符。
- `buyer.kind`：`personal` 或 `business`。其他资格使用严格布尔值；缺失或 null 都是未知，不把字符串 `"true"` 当作资格成立。
- `offers`：具体商家、完整 SKU 的报价列表；不能只写“淘宝最低价”。每项必须有唯一 `id`、`channel`、`seller`、`sku_key`、有效 `source_url`、带时区 `observed_at`、大于零的 `base_price`。
- `now`：可选，带时区的 ISO 时间，方便受控重放和测试。生产入口须使用服务端时间，不能让客户端伪造过去时间以启用过期报价。
- `max_age_hours`：可选，调用方指定的采集时效。没有该值时引擎不猜测“多久算最新”。

报价附加字段：

| 字段 | 约束 |
|---|---|
| `service_key` | 已归一的发票、保修与其他必需服务条件。未提供为 `unspecified`，只展示条件报价，不进入确定最低价 |
| `condition` | `new_unactivated` / `activated` / `used` / `refurbished` / `unknown`；unknown 不参加确定比较 |
| `product_name` | 缺失时标为条件报价 |
| `currency` | 仅 CNY |
| `shipping`、`mandatory_fee` | 可选，默认为 0；必须覆盖已知全部必付费用 |
| `expires_at` | 失效时间；缺失时只能作条件报价；恰好到期已失效 |
| `in_stock` | true 才能参加确定最低价；false 剔除；未知为条件报价 |
| `verified` | true 才能参加确定最低价 |
| `price_type` | 可选，默认 `full`；定金、分期月供等非 full 报价剔除 |
| `is_deposit` | true 时剔除 |

优惠 `discounts` 最多 12 条；超过上限显式剔除报价，不截断规则。每条包含：

- `id`、`label`、`verified: true`、`source_url`。
- `kind: fixed` 金额减免，或 `kind: percent` 比例减免。`value: 0.15` 表示减免 15%，不是支付 15%，也不能写 15。
- `threshold`：门槛，默认 0。`base: current` 表示以该步当前商品价判断门槛及计算比例；`original` 表示以原始商品价判断和计算。运费和费用不进入商品价门槛。
- `order`：整数，从小到大。可叠加且实际生效的两条规则不能有相同 order；引擎不为获低价猜顺序。
- `exclusive_group`：同组最多选一条。空字符串表示独立可选。引擎枚举组合，也允许不用某条优惠以保留后续门槛。
- `requires`：资格名称数组，例如 `student`、`coupon_owned`、`personal`、`business`。除 personal/business 外，从 buyer 同名布尔字段读取。
- 可选 `observed_at`、`expires_at`：发现未来或过期优惠时不计入。

`subsidy` 需要来源与 `verified: true`，显式 `rate` 和 `cap`，且 `subsidy.eligible` 与 `buyer.subsidy_eligible` 均为 true，购买人类型为 personal。企业采购不计入个人国补。未知资格只产生条件估算。

`trade_in` 需有效来源，`credit` 为旧机回收款，`extra_discount` 为额外换新优惠；`confirmed: true` 表示针对本次买家的最终金额已确认。未确认只给条件估算。`method: cash` 是独立回收现金；`voucher` 是购新抵扣券。券默认只能抵商品，不抵运费与必付费用；真实规则允许时显式设 `voucher_covers_fees: true`。券最多用到可抵扣额，不生成负成交价。可提供 observed_at/expires_at。

## 计算顺序与精度

本版明确支持以下一种顺序：

1. 原始商品价。
2. 按 order 的平台优惠（枚举符合互斥和资格条件的组合）。
3. 已确认额外换新优惠。
4. 对该时点商品价计算补贴比例和上限。
5. 加运费及必付费用。
6. 回收券抵扣，或另列现金回收收入。

金额与每一步减免用 Decimal，四舍五入到分（ROUND_HALF_UP），所有输出金额是两位小数字符串。每一步记录 before、amount、after、来源。不能用超额券把金额截断为虚假零元。

适配器只能把真实适用、顺序匹配的活动映射到此模型。如果渠道要求不同顺序、不同补贴基数、条件返现、支付工具费用、跨商品满减等，本版不支持；不得强行映射并宣称最低价。应把它作为待确认项，或先扩展模型和对应测试。

## 输出与展示

- `quotes[].checkout_amount`：只采用已确认优惠的保守结算金额；不是把所有可能优惠相减的数字。
- `estimated_cash_outlay`：有已确认回收现金时为结算额减独立回收款。回收券已经在结算额中抵扣，不再减第二次。旧机现金超过购新结算额时净支出可以为负，必须明确这是两笔交易的净额。
- `trade_in_credit`：本次实际抵扣或另列的回收款。
- `conditional_checkout_amount`、`conditional_estimated_cash_outlay`、`conditional_steps`：存在尚未确认资格、验机等条件时的较低估算；不能作为已核实价格宣传。
- `status`：`verified` / `conditional` / `excluded`；被剔除报价的金额为 null。待确认项在 assumptions，错误、优惠不适用等在 issues。
- `best`：按 `sku_key + condition + service_key` 分组，只比较 verified。`offer_id` 是最低结算额方案；`offer_ids` 保留并列。`lowest_cash_outlay` 与 `lowest_cash_outlay_offer_ids` 单列最低现金净支出，避免混淆结算价与回收所得。
- 每个 best 都标明范围：仅限本次输入中已核实且可比的报价，不是全网最低价。

无有效证据、过期、未来采集时间、无库存、定金/月供、地区不符、金额异常、重复 id 等不会进入确定最低价。引擎不能凭金额高低判断商家是否诈骗；来源真实性、完整费用与商品状态仍须渠道适配器和审核流程证实。

## 验证

运行 `python3 -m unittest discover -s tests -p test_pricing.py -v`。

测试仅使用 example.invalid 的合成规则样本，不包含真实华为型号、实时报价或真实活动数据。
