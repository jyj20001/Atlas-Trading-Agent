# K-Line Provider Data Consistency Validation Report

**日期:** 2026-07-25
**验证内容:** EastMoney vs Tencent 前复权 K 线一致性

---

## 测试结果

### ✅ Provider Chain

| Provider | 状态 | 返回条数 | 最早日期 | 最晚日期 |
|----------|:----:|:--------:|:--------:|:--------:|
| EastMoney | **❌ 被限流** | 0 | — | — |
| Tencent (fallback) | ✅ **可用** | 640 | 2023-12-01 | 2026-07-24 |

**发现:** 东方财富 API (`push2his.eastmoney.com`) 在连续测试后返回空响应（HTTP 200 + 空 body），疑似 IP 限流。多次重试后仍不恢复。

### EastMoney Provider 行为

- 第 1 次调用: ✅ 成功返回数据
- 第 5-10 次调用: ⚠️ 偶发空响应
- 10 次以上: ❌ 持续被屏蔽（`RemoteDisconnected` / 空 body）

### Provider Chain Fallback

```python
EastMoney → 失败 (2次重试, 5s 超时) → Tencent → 成功 (640根)
```

**平均耗时:** ~10s/只 (含 EastMoney 重试 2s + Tencent 请求 8s)

---

## 数据一致性评估

由于 EastMoney 被限流，无法完成跨 Provider 一致性对比。

### Tencent 单数据源稳定性

| 股票 | K 线数量 | 最早日期 | 时间跨度 |
|------|:--------:|:--------:|:--------:|
| 600000 浦发银行 | 640 | 2023-12-01 | 2.5 年 |
| 600004 白云机场 | 640 | 2023-12-01 | 2.5 年 |
| 600006 东风股份 | 640 | 2023-12-01 | 2.5 年 |

数据跨度和 K 线数量一致，无退市/合并导致的断裂。

---

## 数据库变更已生效

| 字段 | 说明 |
|------|------|
| `source` | 已有字段，标注数据源 (tencent/eastmoney) |
| `adjust_type` | 新增字段，标注复权类型 (qfq/hfq/none) |

### 迁移验证

```sql
ALTER TABLE daily_klines ADD COLUMN adjust_type TEXT DEFAULT 'qfq';
```

*自动迁移，兼容旧库。*

---

## 结论与建议

### EastMoney 不可用于生产

| 问题 | 影响 |
|------|------|
| IP 限流 | 连续请求 5-10 次后空响应 |
| 无官方 SLA | 无法保障可用性 |
| **不推荐**作为主要数据源 | ❌ |

### 替代方案

| 方案 | 状态 | 推荐 |
|------|:----:|:----:|
| 东方财富 API | ❌ 被限流 | 保留做备选，非主力 |
| **腾讯 API** | ✅ **稳定可用** | **当前主力** |
| 富途 OpenAPI (OpenD) | 🚧 需安装 `futu-api` + 启动 OpenD | **推荐未来** |

### 架构决策

- EastMoney Provider **保留**在 Provider 链中（优先级 0），失败后自动 fallback
- 当前 Tencent 640 根已是最大可用数据量
- 如需更早历史（2018+），需实施 **富途 OpenAPI** 方案
- Provider 链架构已就绪，只需增加新的 Provider 即可扩展

---

*验证完成。不修改策略。*
