# 一条命令完成持仓日常检查（只读）

这是现有三个模块的**单一使用入口**：公开行情适配器 → 持仓止损/止盈及逻辑失效判断 → 券商可卖数量/T+1/停牌执行评估。没有新增任务调度、自动下单或投资策略。

在本地创建私有的 `positions.json`（数组；格式参见 `docs/POSITION_WATCHLIST_USAGE.md`）。真实仓位和券商文件**不要提交到公开 GitHub**。

```bash
python scripts/v29_daily_review.py \
  --positions /private/positions.json \
  --at '2026-10-26T15:30:00+08:00' \
  --expected-session 2026-10-26 \
  --max-quote-age-hours 1 \
  --json-out /private/daily-review.json
```

如需离线运行，加 `--quotes /private/quotes.json`。如果有券商账户的交易状态及可卖数量快照，加 `--broker-status /private/execution-context.json`；文件格式参见 `docs/EXIT_EXECUTION_READINESS.md`。无券商状态时，执行能力始终标识为未知。

输出按优先级展示：必须退出且成交未确认 → 行情不可判定 → 本次快照未触发退出。**“快照未触发退出”不等于推荐继续持有。** 第三方腾讯财经报价可能延迟、缺失或改变格式，不能证明停牌状态、T+1 可卖余额或成交可行性。必须由用户指定已确认的交易日（`--expected-session`）及带时区的评估时刻；程序不猜测节假日，不自动后台执行。错误会拒绝本次评估；缺行情则明确显示未知，逻辑失效仍保留退出要求。

本文件仅说明如何使用：不存储真实持仓，不改变已有投资纪律与冻结研究。
