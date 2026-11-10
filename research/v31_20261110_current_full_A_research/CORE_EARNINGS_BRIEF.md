# 2026-11-10 F10扣非利润数据源实际核验

样本：既有432只财务初筛A档，不重新选股。供应商信息取自2026-11-10采集，披露截止2026-11-09。
使用原有 F10 扣非归母利润金额字段 KCFJCXSYJLR；原有摘要 DEDUCT_BASIC_EPS 是不同的每股指标，二者不得互相补写。

| 来源与质量指标 | 只数 |
|---|---:|
| 既有初筛A档 | 432 |
| F10 H1/Q3均按证券、机构与公告日对应 | 432 |
| F10 H1/Q3扣非归母利润金额均有数值 | 432 |
| 可计算第三季度单季扣非归母利润且数值为正 | 427 |
| F10扣非利润为正、核对无F10标记且无ST名称提示（仅字段完整度） | 419 |
| ST名称提示（来自既有原始摘要检查） | 8 |

F10各类状态/缺失见下表；不是上市公司官方公告历史时点原件认证。
| 原有F10统计键 | 只数 |
|---|---:|
| reviewed_a_tier | 432 |
| both_periods_matched | 432 |
| latest_core_profit_available | 432 |
| both_core_profit_available | 432 |
| latest_core_profit_nonpositive | 1 |
| standalone_q3_core_profit_nonpositive | 5 |
| unmatched_or_missing | 0 |

**结论：这些是来源覆盖和财务事实检查，不是预测排名、估值认可或交易资格。NO BUY。**
