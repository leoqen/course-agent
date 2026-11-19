# 综合调研部分完成样例

> 冻结题 R04 的保存结果，运行日期2026-11-20；状态 PARTIAL。自家课程与销售均为合成验证资料，竞品为本次公开检索。此为文档演示样例，不是正在执行的聊天。

⚠ 本报告未完全通过来源、引用或格式检查，请结合来源与任务记录阅读。

| 课程 | 入学基础 | 现行完整售价 |
|---|---|---|
| 韩语零基础入门班（K01） | 无韩语学习经历[D38fc28cf2194] | 人民币1680元，完整课程学费[Dec59baf0a167] |
| 沪江网校 韩语零基础入门【音标语音暑期班】 | 本次尚未确认该课程现行入学基础 | 本次尚未确认该课程现行完整售价 |

## 销售统计（合成数据，金额单位：元）

| 区间（左闭右开） | 订单 | 收款 | 退款 | 净收款 | 依据 |
|---|---:|---:|---:|---:|---|
| 2026-06-12～07-01 | 88 | 147840.00 | 5040.00 | 142800.00 | [Q692bb7f200e9][Qc4a3faa86a6a] |
| 2026-07-01～08-01 | 150 | 252000.00 | 8400.00 | 243600.00 | [Qe9075d844682][Q96d5b1325220] |
| 2026-08-01～08-06 | 34 | 57120.00 | 1680.00 | 55440.00 | [Qb5f9674aa80d][Qaa330e9a657e] |

收款按付款时间、退款按发生时间统计，净收款非利润[M767d1718d802]。

2026-06与2026-08为不完整月份，不按月总量排名或做环比；无线索与广告费数据，不能计算ROI或咨询转化率[M767d1718d802]。


## 样例依据

- [M767d1718d802] 应用定义的销售口径：销售均为模拟记录。按付款时间统计成交及收款，按退款时间统计退款，区间左闭右开。退款不扣除成交订单数。金额人民币。日期字段带时间，查询使用完整日期边界。退款率按选定付款区间订单截至指定日期的成功退款订单占比。订单与退款应分别聚合后再按月份合并；按退款时间查询时，不得同时限定原订单付款时间必须在同一区间，否则会漏掉跨月退款。orders.status=PAID代表已成交，发生退款后仍保留PAID；无退款状态字段。区间净收款=区间收款-区间退款，不是利润或会计收入。没有线索、咨询人数、广告费用数据，不能计算咨询转化率或ROI。

- [Q692bb7f200e9] 实际SQL（合成交易库）：
```sql
SELECT COUNT(*) AS orders, SUM(amount) AS receipts, AVG(amount) AS average FROM orders WHERE course_id = 'K01' AND status = 'PAID' AND paid_at >= '2026-06-12' AND paid_at < '2026-07-01' LIMIT 501
```
结果：{"columns": ["orders", "receipts", "average"], "rows": [[88, "147840.00", "1680.000000"]]}

- [Qc4a3faa86a6a] 实际SQL（合成交易库）：
```sql
SELECT SUM(r.amount) AS refunds FROM refunds AS r JOIN orders AS o ON o.order_id = r.order_id WHERE o.course_id = 'K01' AND r.refunded_at >= '2026-06-12' AND r.refunded_at < '2026-07-01' LIMIT 501
```
结果：{"columns": ["refunds"], "rows": [["5040.00"]]}

- [Qe9075d844682] 实际SQL（合成交易库）：
```sql
SELECT COUNT(*) AS orders, SUM(amount) AS receipts, AVG(amount) AS average FROM orders WHERE course_id = 'K01' AND status = 'PAID' AND paid_at >= '2026-07-01' AND paid_at < '2026-08-01' LIMIT 501
```
结果：{"columns": ["orders", "receipts", "average"], "rows": [[150, "252000.00", "1680.000000"]]}

- [Q96d5b1325220] 实际SQL（合成交易库）：
```sql
SELECT SUM(r.amount) AS refunds FROM refunds AS r JOIN orders AS o ON o.order_id = r.order_id WHERE o.course_id = 'K01' AND r.refunded_at >= '2026-07-01' AND r.refunded_at < '2026-08-01' LIMIT 501
```
结果：{"columns": ["refunds"], "rows": [["8400.00"]]}

- [Qb5f9674aa80d] 实际SQL（合成交易库）：
```sql
SELECT COUNT(*) AS orders, SUM(amount) AS receipts, AVG(amount) AS average FROM orders WHERE course_id = 'K01' AND status = 'PAID' AND paid_at >= '2026-08-01' AND paid_at < '2026-08-06' LIMIT 501
```
结果：{"columns": ["orders", "receipts", "average"], "rows": [[34, "57120.00", "1680.000000"]]}

- [Qaa330e9a657e] 实际SQL（合成交易库）：
```sql
SELECT SUM(r.amount) AS refunds FROM refunds AS r JOIN orders AS o ON o.order_id = r.order_id WHERE o.course_id = 'K01' AND r.refunded_at >= '2026-08-01' AND r.refunded_at < '2026-08-06' LIMIT 501
```
结果：{"columns": ["refunds"], "rows": [["1680.00"]]}

- [Dec59baf0a167] 收费与服务规则.pdf：学费人民币1680元，含24节正式直播课，每节50分钟。

- [D38fc28cf2194] 课程介绍与选课指南.pdf：课程编号：K01。适合基础：无韩语学习经历。学习目标：掌握基础发音、常用问候和简单自我介绍。不适用于直接冲刺TOPIK等级或商务谈判。 选课需比较当前基础与学习目标；想应试不代表适合跳过基础阶段。建议每日20—30分钟复习。
