# AI Core EVID — Prediction-first architecture V3.2

> **Historical reference:** V4.0 [Research-first reset](RESEARCH_FIRST_V4.md) supersedes this document for new discretionary research priority and development/validation separation. Original scientific contracts and existing implementation details remain unchanged.

Effective: 2026-11-17. **This is the canonical priority / architecture for new work**, not a retroactive change to frozen research or to the V2.9 scientific governance kernel.

## 1. Product objective and non-negotiable constraints

Build a practical A-share forecasting system using free, lawfully accessible, reproducible information. Its purpose is to identify **future** opportunities before the outcome, estimate uncertainty and expected net excess return over a predeclared horizon (initial research target: 20 exchange sessions), verify that signal on genuinely independent observations, and then support disciplined, human-executed investment decisions.

Success is **not** the number of GitHub Actions passes, data-source PDFs, fail-closed reports or factor backtests. Success requires:
- a verifiable **decision-time** predictive signal that can rank eligible opportunities before their outcomes;
- positive, repeatable **after-cost**, benchmark-relative evidence with realistic liquidity, fill, risk and position sizing;
- a usable, dated candidate / forecast / confidence / reason / entry-invalidation-exit / position-review output;
- conservative NO BUY when the evidence, liquidity or risk conditions are insufficient.

The following **cannot be deleted** to accelerate research: leakage barriers, frozen 122/8 and V2.8.12 prospective sample integrity, blocked Fold3/Fold4 reads, original scientific gate decisions, honest OOS designation, source/event-time identity, cost and portfolio conservation, precommitted risk/stop-loss discipline and human trading authority.

## 2. New primary architecture — forecast is the product

```text
                REAL USER GOAL
    Find future A-share opportunities with
      verified, tradable net excess return
                      |
          PUBLIC DECISION-TIME INFORMATION
          (time, source, issuer, vintage)
                      |
            HYPOTHESIS & FEATURE LAB
       economic mechanism -> causal availability
        -> identifiable pre-outcome features
                      |
             FORECAST / RANK ENGINE
       eligible universe first -> estimated
       conditional return / rank / uncertainty
                      |
         INDEPENDENT ECONOMIC VALIDATION
        holdout/prospective -> matched benchmark
        -> fees, lot, limit, liquidity, risk
                      |
         CANDIDATE & DECISION CASE OUTPUT
     BUY eligible only if evidence qualifies;
        otherwise research watch / NO BUY
                      |
            POSITION & EXIT DISCIPLINE
            (human executes the order)
                      |
          CLOSED OUTCOME FEEDBACK LOOP
        observations -> failure diagnosis
            -> NEW future hypotheses
```

The **prediction hypothesis and measurable forecast** are now first-class; audits, pipelines and GitHub runners are enabling infrastructure, not parallel objectives.

### Four bounded lanes

| Lane | Responsibility | Concrete deliverable | New-work priority |
|---|---|---|---|
| **A — Predictive Discovery** | Explain *why future returns may differ*; compare feasible information families, decision timestamps and legitimate prospective validation paths; favor unexplored ex-ante mechanisms over repeating price thresholds | One independent-source, testable hypothesis with explicit information timing and baseline | **P0 when no credible predictor exists** |
| **B — Economic Test** | Freeze rule, eligible full universe, sample and comparison before qualifying outcomes; verify execution/cost mechanics | Named positive/negative/insufficient verdict with economic effect and independent test provenance | P0 immediately after A's admissible candidate |
| **C — Decision Delivery** | Reuse already present Decision Packet, validity and discipline engines; user-facing real stock cases and existing holdings | Dated stock/forecast/confidence/reason plus risk / eligible action; NO BUY if not promoted | P1 parallel, not an excuse to defer A/B |
| **D — Operations** | Keep existing scheduled experiments, data feeds and incidents intact; only address failures that materially block A/B/C or corrupt frozen evidence | Targeted repairs with evidence; **no new standing governance layer** | On demand |

Protected **122/8 prospective** and **V2.8.12 E-layer** are isolated evidence lanes: continue existing schedules without changing members, thresholds, outcome embargo or status; their readiness does not postpone unrelated P0 research.

## 3. Reframe hypotheses around future changes, not past rise thresholds

A candidate can have risen, fallen or moved sideways. *Having already risen* is not a universal eligibility condition and *having not risen* is not a positive signal either.

Before any factor code:
1. State the **economic mechanism** (for example an earnings-expectations revision, a newly public operating change, delayed information absorption, or a liquidity-related risk premium). These are candidates for investigation, **not claims of profitable edge**.
2. State what **could have been observed at decision time**, including date, vendor, issuer/security identity, corrective disclosures and when orders could actually be entered.
3. Distinguish *forecast inputs* from target, outcome and explanatory hindsight. Feature construction must not require the future target's price move.
4. Choose **one minimal independent data source and one simple baseline**. If free reliable decision-time data and a non-opened evaluation path cannot be established, stop with **SOURCE_NOT_ADMISSIBLE** before building new workflows.
5. Preregister *one* unmodified hypothesis with observable failure criteria and a feasible execution model. Never grid-search signs, windows or samples in a previously opened archive and relabel the best as independent.
6. Evaluate **forecast value and tradeable economics**, not just hit rate or before-fee mean return. Compare against a matched contemporaneous eligible pool and/or a time-matched **total-return** index, including transaction fees, slippage, 100-share lots, risk and unresolved fills.

### Explicitly retired / constrained directions

- 2023/24 60-session low absolute volatility: `research/v31_2023_2024_lowvol_one_shot/RESULT.json` — not promoted.
- 2023/24 20-session short reversal: `research/v31_2023_2024_short_reversal_one_shot/RESULT.json` — not promoted.
- 2023/24 120-to-20-session medium momentum: `research/V3.1_MEDIUM_MOMENTUM_SKIP20_DEV_VERDICT_20261117.md` — not promoted.
- 2018–20 historical Q3 growth/ROE: `research/V3.1_Q3_GROWTH_2018_2020_DEVELOPMENT_ECONOMICS_VERDICT_20261117.md` — development feasibility failure; the 2021/22 frozen follow-up is evidence-blocked, **not silently redesigned**.
- Other closed V2.8/2.9 negative studies retain their original recorded verdicts.

These negative specific tests do **not** disprove every mechanism in their economic family. They bar **hindsight retuning on the same observed samples**; a future genuinely new hypothesis requires a new independently eligible evaluation.

## 4. Reuse actual modules instead of rebuilding the platform

| Existing asset | New role | Do not misrepresent |
|---|---|---|
| `scripts/v281_stage1_factor_screen.py`, `scripts/v29_pinned_historical_rank.py` | Historical descriptive/feature research only | Not certified current predictor |
| `scripts/v290_strategy_validity_evaluator.py`, `scripts/v291_portfolio_path_evaluator.py`, `scripts/v29_strategy_validity_validator.py` | Reusable independent economic validity calculation | Portfolio evaluator needs upstream executable chronological paths |
| `scripts/v294_evidence_strength_synthesizer.py`, `scripts/v29_decision_packet_adapter.py` | Evidence synthesis and time-stamped Decision Case adaptation | Adapter does not independently authenticate caller-provided hash references |
| `scripts/v29_discipline_engine.py` | Existing conservative buy/add/hold/reduce/exit discipline | Does not authorize broker orders |
| `scripts/v29_current_issuer_research_review.py`, `scripts/v29_daily_review.py`, `scripts/v29_position_watchlist.py` | Real-issuer source-bound review / user positions | Real issuer or watchlist is not verified alpha |
| Existing GitHub Actions schedules and frozen research artifacts | Background evidence provenance/essential incident operations | Green checks do not equal forecast capability |

**No code migration or bulk deletion of 175 existing workflow files / 277 existing scripts is part of this architecture change**. Existing reproducibility matters; new research work must justify every new executable surface. Historical files remain accessible rather than erased.

## 5. Day-to-day execution contract

For user instruction "继续" under 股票预测:
1. Read this file and latest proof of the **nearest incomplete P0 outcome**. Do not default to the most recent script, failure monitor or document.
2. Do one **Problem Elimination Pass**: which expensive step can be deleted/avoided/absorbed before any optimization?
3. Choose one action that closes a predictive or economic uncertainty **now**. Distinguish feature feasibility, preregistration, executed experiment and independent evidence.
4. Deliver something **verifiable** (measured comparison, reproducible research receipt, source-backed hypothesis, executable decision case); do not stop at a generic plan or passive waiting. If no valid independent outcome is currently permissible, work on unrelated information feasibility or existing source-backed decision outputs, never open protected blind data.
5. After any batch, check fundamental scientific and accounting errors: membership and timestamp before price; cost/cash conservation; universe completeness; actual fills vs proxies; primary baseline integrity. Fix observed faults or record the blocker once. Do not add broad defensive wrappers for speculative edge cases.
6. Declare **PROVED / FAILED / INSUFFICIENT / BLOCKED** accurately. Never promote a merely appealing stock or negative experiment as BUY/ADD. The system should output usable research/watch cases even when alpha is blocked.
7. Stop iterating on a failed **fixed** hypothesis. A new experiment must bring a genuinely new mechanism/data or independent evaluation, not another parameter combination over observed outcomes.

**Resource allocation decision:** new P0 work belongs to **finding and validating a predictive edge**. Operational reliability is an obligation but cannot become the principal deliverable. The previous `docs/MAINLINE_DECISION_FIRST.md` continues to document existing decision-engine interfaces and frozen invariants, subordinated to this priority order for new work.

## 6. Explicit present state / acceptance

As of 2026-11-17: **NO VERIFIED ALPHA / NO BUY**. No independent tested prediction signal is ready to trade. Failing strategies and source limitations are real research information, not tasks to keep repairing.

Architecture migration is complete when README + agent policy point here, existing engines are reused, frozen contracts remain unchanged, and a new "continue" turn starts from the predictive/validation bottleneck rather than another unneeded workflow. **Changing documentation alone does not prove forecast ability or trading readiness.**

## 2026-11-19：交易前纸面可执行性前移（复用，而非预测策略）

已加入通用纯函数 `scripts/v32_candidate_tradeability.py` 的 `evaluate(candidates, account)` 与六项最小回归测试 `scripts/test_v32_candidate_tradeability.py`。实测 [GitHub Actions run 44480964965](https://github.com/Justalittlebittt/AI-Core-EVID/actions/runs/44480964965) `completed/success`。

**为何必须有此边界**：近期冻结的2026-09-18融资Top10两种模型各有一只科创板最低200股超过单名¥10,000；2025/26沪深300调入名单的部分股票亦超出固定单名预算。在计算未来20日收益**之前**，需要先使用T时点股票代码、已可得参考价、预算和板块权限判断纸面交易资格，避免事后因“买不起”换股/减小交易单位。

可重用函数只接受显式传入的 `security_id`、`reference_price_cny`、`reference_session` 和账户预算/权限；不读取股价或未来结果，不对原名单排序或补选。主板/创业板最低买100股；科创板最低买200股、超过200股允许按1股递增（验证来源：上交所2026年[交易规则](https://www.sse.com.cn/lawandrules/sselawsrules2025/stocks/exchange/c/c_20260424_10816482.shtml)和[投教说明](https://edu.sse.com.cn/tib/qa/)；深交所[主板/创业板说明](https://www.szse.cn/www/investor/institute/rules/t20230706_601604.html)）。函数输出`PAPER_MIN_LOT_AFFORDABLE_ONLY`或`BLOCKED_PAPER_BUY`，总是`trade_authorized=false`。使用固定示例最小单边¥5佣金+0.03%佣金率+0.1%入场滑点；**不是**真实券商收费或限价簿成交验证；也**不保证整个候选组合的共享现金配置**。

此能力不修改冻结8股、不把负面研究转换为买入证据、不替代已有`scripts/v29_eight_portfolio_capacity.py`对特定8股的组合风险检查。后续任何全市场研究候选筛选时，交易资格必须在**T+20收益读取前**得到明确状态；未提供真实账户输入时保持UNKNOWN，不虚构用户资金。交易前资格只是必要条件，仍缺真正独立、扣费后可重复超额的预测证据，**NO BUY**。
