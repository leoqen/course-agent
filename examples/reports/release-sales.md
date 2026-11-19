# 月度销售样例

> 冻结题 R02 的保存结果，运行日期2026-11-20；状态 SUCCEEDED。自家课程与销售均为合成验证资料，竞品为本次公开检索。此为文档演示样例，不是正在执行的聊天。

## 销售统计（合成数据，金额单位：元）

| 区间（左闭右开） | 订单 | 收款 | 退款 | 净收款 | 依据 |
|---|---:|---:|---:|---:|---|
| 2026-05-18～06-01 | 32 | 79360.00 | 2480.00 | 76880.00 | [Q04a96b145370][Qb9dda9719f28] |
| 2026-06-01～07-01 | 96 | 238080.00 | 32240.00 | 205840.00 | [Q4dac115d1665][Qe6380c6b1f1f] |
| 2026-07-01～07-03 | 8 | 19840.00 | 0.00 | 19840.00 | [Q77d75a3d577c][Q77404c8a7c8b] |

收款按付款时间、退款按发生时间统计，净收款非利润[Me65eef7db9a4]。


## 样例依据

- [Me65eef7db9a4] 应用定义的销售口径：销售均为模拟记录。按付款时间统计成交及收款，按退款时间统计退款，区间左闭右开。退款不扣除成交订单数。金额人民币。日期字段带时间，查询使用完整日期边界。退款率按选定付款区间订单截至指定日期的成功退款订单占比。订单与退款应分别聚合后再按月份合并；按退款时间查询时，不得同时限定原订单付款时间必须在同一区间，否则会漏掉跨月退款。orders.status=PAID代表已成交，发生退款后仍保留PAID；无退款状态字段。区间净收款=区间收款-区间退款，不是利润或会计收入。没有线索、咨询人数、广告费用数据，不能计算咨询转化率或ROI。

- [Q04a96b145370] 实际SQL（合成交易库）：
```sql
SELECT COUNT(*) AS orders, SUM(amount) AS receipts, AVG(amount) AS average FROM orders WHERE course_id = 'K02' AND status = 'PAID' AND paid_at >= '2026-05-18' AND paid_at < '2026-06-01' LIMIT 501
```
结果：{"columns": ["orders", "receipts", "average"], "rows": [[32, "79360.00", "2480.000000"]]}

- [Qb9dda9719f28] 实际SQL（合成交易库）：
```sql
SELECT SUM(r.amount) AS refunds FROM refunds AS r JOIN orders AS o ON o.order_id = r.order_id WHERE o.course_id = 'K02' AND r.refunded_at >= '2026-05-18' AND r.refunded_at < '2026-06-01' LIMIT 501
```
结果：{"columns": ["refunds"], "rows": [["2480.00"]]}

- [Q4dac115d1665] 实际SQL（合成交易库）：
```sql
SELECT COUNT(*) AS orders, SUM(amount) AS receipts, AVG(amount) AS average FROM orders WHERE course_id = 'K02' AND status = 'PAID' AND paid_at >= '2026-06-01' AND paid_at < '2026-07-01' LIMIT 501
```
结果：{"columns": ["orders", "receipts", "average"], "rows": [[96, "238080.00", "2480.000000"]]}

- [Qe6380c6b1f1f] 实际SQL（合成交易库）：
```sql
SELECT SUM(r.amount) AS refunds FROM refunds AS r JOIN orders AS o ON o.order_id = r.order_id WHERE o.course_id = 'K02' AND r.refunded_at >= '2026-06-01' AND r.refunded_at < '2026-07-01' LIMIT 501
```
结果：{"columns": ["refunds"], "rows": [["32240.00"]]}

- [Q77d75a3d577c] 实际SQL（合成交易库）：
```sql
SELECT COUNT(*) AS orders, SUM(amount) AS receipts, AVG(amount) AS average FROM orders WHERE course_id = 'K02' AND status = 'PAID' AND paid_at >= '2026-07-01' AND paid_at < '2026-07-03' LIMIT 501
```
结果：{"columns": ["orders", "receipts", "average"], "rows": [[8, "19840.00", "2480.000000"]]}

- [Q77404c8a7c8b] 实际SQL（合成交易库）：
```sql
SELECT SUM(r.amount) AS refunds FROM refunds AS r JOIN orders AS o ON o.order_id = r.order_id WHERE o.course_id = 'K02' AND r.refunded_at >= '2026-07-01' AND r.refunded_at < '2026-07-03' LIMIT 501
```
结果：{"columns": ["refunds"], "rows": [[null]]}
