# 综合调研成功样例

> 冻结题 R05 的保存结果，运行日期2026-11-20；状态 SUCCEEDED。自家课程与销售均为合成验证资料，竞品为本次公开检索。此为文档演示样例，不是正在执行的聊天。

| 课程 | 适用基础 | 现行完整售价 |
|---|---|---|
| 自家 TOPIK初级备考班（K03） | 掌握基础发音及常见基础词汇，入班前完成水平评估[D4fbdb347bd0e] | 2980元[D6486c78807a3] |
| 沪江网校 韩语TOPIK I 初级强化 | 本次尚未确认[Wb638f7aaf2c6] | 列表页显示“免费”，未确认对应完整课程售价[Wb638f7aaf2c6] |

## 销售统计（合成数据，金额单位：元）

| 区间（左闭右开） | 订单 | 收款 | 退款 | 净收款 | 依据 |
|---|---:|---:|---:|---:|---|
| 2026-05-26～06-01 | 15 | 44700.00 | 0.00 | 44700.00 | [Q5c2f4b852382][Q0764e5f853fd] |
| 2026-06-01～07-01 | 61 | 181780.00 | 5960.00 | 175820.00 | [Q983a9c99e558][Q515fba14b64f] |
| 2026-07-01～07-11 | 14 | 41720.00 | 2980.00 | 38740.00 | [Q92ae87c2aa3e][Q919767ce49fb] |

收款按付款时间、退款按发生时间统计，净收款非利润[Md37bf7b0bfa0]。

首尾为不完整月份，不按月总量排名或做环比；同期销售变化与竞品无因果证据[Md37bf7b0bfa0]。


## 样例依据

- [Md37bf7b0bfa0] 应用定义的销售口径：销售均为模拟记录。按付款时间统计成交及收款，按退款时间统计退款，区间左闭右开。退款不扣除成交订单数。金额人民币。日期字段带时间，查询使用完整日期边界。退款率按选定付款区间订单截至指定日期的成功退款订单占比。订单与退款应分别聚合后再按月份合并；按退款时间查询时，不得同时限定原订单付款时间必须在同一区间，否则会漏掉跨月退款。orders.status=PAID代表已成交，发生退款后仍保留PAID；无退款状态字段。区间净收款=区间收款-区间退款，不是利润或会计收入。没有线索、咨询人数、广告费用数据，不能计算咨询转化率或ROI。

- [Q5c2f4b852382] 实际SQL（合成交易库）：
```sql
SELECT COUNT(*) AS orders, SUM(amount) AS receipts, AVG(amount) AS average FROM orders WHERE course_id = 'K03' AND status = 'PAID' AND paid_at >= '2026-05-26' AND paid_at < '2026-06-01' LIMIT 501
```
结果：{"columns": ["orders", "receipts", "average"], "rows": [[15, "44700.00", "2980.000000"]]}

- [Q0764e5f853fd] 实际SQL（合成交易库）：
```sql
SELECT SUM(r.amount) AS refunds FROM refunds AS r JOIN orders AS o ON o.order_id = r.order_id WHERE o.course_id = 'K03' AND r.refunded_at >= '2026-05-26' AND r.refunded_at < '2026-06-01' LIMIT 501
```
结果：{"columns": ["refunds"], "rows": [[null]]}

- [Q983a9c99e558] 实际SQL（合成交易库）：
```sql
SELECT COUNT(*) AS orders, SUM(amount) AS receipts, AVG(amount) AS average FROM orders WHERE course_id = 'K03' AND status = 'PAID' AND paid_at >= '2026-06-01' AND paid_at < '2026-07-01' LIMIT 501
```
结果：{"columns": ["orders", "receipts", "average"], "rows": [[61, "181780.00", "2980.000000"]]}

- [Q515fba14b64f] 实际SQL（合成交易库）：
```sql
SELECT SUM(r.amount) AS refunds FROM refunds AS r JOIN orders AS o ON o.order_id = r.order_id WHERE o.course_id = 'K03' AND r.refunded_at >= '2026-06-01' AND r.refunded_at < '2026-07-01' LIMIT 501
```
结果：{"columns": ["refunds"], "rows": [["5960.00"]]}

- [Q92ae87c2aa3e] 实际SQL（合成交易库）：
```sql
SELECT COUNT(*) AS orders, SUM(amount) AS receipts, AVG(amount) AS average FROM orders WHERE course_id = 'K03' AND status = 'PAID' AND paid_at >= '2026-07-01' AND paid_at < '2026-07-11' LIMIT 501
```
结果：{"columns": ["orders", "receipts", "average"], "rows": [[14, "41720.00", "2980.000000"]]}

- [Q919767ce49fb] 实际SQL（合成交易库）：
```sql
SELECT SUM(r.amount) AS refunds FROM refunds AS r JOIN orders AS o ON o.order_id = r.order_id WHERE o.course_id = 'K03' AND r.refunded_at >= '2026-07-01' AND r.refunded_at < '2026-07-11' LIMIT 501
```
结果：{"columns": ["refunds"], "rows": [["2980.00"]]}

- [Wb638f7aaf2c6] 韩语能力考课程_在线韩语能力考辅导_韩语培训班价格-沪江网校：<https://class.hujiang.com/category/229>。仅证明本次取得的公开列表展示，不证明现行完整售价。

- [D4fbdb347bd0e] 课程介绍与选课指南.pdf：课程编号：K03。适合基础：掌握基础发音及常见基础词汇，入班前完成水平评估。学习目标：训练 TOPIK I听力、阅读题型与复习方法。不适用于TOPIK II中高级备考，不保证通过或达到指定分数。 选课需比较当前基础与学习目标；想应试不代表适合跳过基础阶段。建议每日40—60分钟复习。

- [D6486c78807a3] 收费与服务规则.pdf：学费人民币2980元，含36节正式直播课，每节60分钟。
