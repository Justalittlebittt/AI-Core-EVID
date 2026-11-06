#!/usr/bin/env python3
"""One read-only maturity decision brief from frozen 122/8/310 observations.

Reports signs and incompleteness, NOT an alpha significance test or BUY signal.
Never fetches quotes, changes frozen stocks or invents personal risk inputs.
"""
from __future__ import annotations

import argparse
import json
import math
from datetime import datetime, timezone
from pathlib import Path

from v29_growth_forward_cohort import evaluate as evaluate_parent
from v29_eight_pilot_outcome import evaluate as evaluate_eight
from v29_growth_310_conditional_result import evaluate as evaluate_control

COMPLETE="ONE_EPISODE_DESCRIPTIVE_NOT_BUY_EVIDENCE"
SINGLE="ONE_EPISODE_EXPLORATORY_NOT_BUY_EVIDENCE"

def percent(v):
    if not isinstance(v,(int,float)) or isinstance(v,bool) or not math.isfinite(v):
        return "未取得有效结果"
    return f"{v*100:+.2f}%"

def comparison(v):
    if not isinstance(v,(int,float)) or isinstance(v,bool) or not math.isfinite(v):
        return "未完成"
    if v>0:
        return "该时段领先（不能证明长期优势）"
    if v<0:
        return "该时段落后"
    return "该时段持平"

def brief(verdict,outcome,eight=None,control=None,control_prices=None,now=None):
    now=now or datetime.now(timezone.utc)
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("AWARE_MATURITY_CLOCK_REQUIRED")
    if now<datetime.fromisoformat("2026-11-27T16:30:00+08:00"):
        raise ValueError("FROZEN_OUTCOME_NOT_YET_MATURE")
    if (verdict.get("schema")!="V29_FORWARD_122_TWENTIETH_SESSION_RESEARCH_VERDICT_V1"
        or verdict.get("frozen_cohort_count")!=122
        or verdict.get("fixed_entry_session")!="2026-11-02"
        or verdict.get("source_bytes_sha256")!=outcome.get("raw_outcome_sources_sha256")
        or verdict.get("protocol_sha256")!=outcome.get("protocol_sha256")
        or verdict.get("live_buy_eligibility")!="NOT_AUTHORIZED"
        or verdict.get("trade_authorized") is not False):
        raise ValueError("PARENT_EVIDENCE_NOT_BOUND")
    parent=verdict["outcome_evaluation"]
    completed=parent.get("status")==COMPLETE
    if completed:
        fresh=evaluate_parent(outcome,now=now)
        if fresh!=parent:
            raise ValueError("PARENT_EVALUATION_RECOMPUTE_MISMATCH")
    elif (parent.get("mean_net_excess") is not None
          or parent.get("strategy_validated") is not False):
        raise ValueError("INCOMPLETE_PARENT_CANNOT_CLAIM_ALPHA")
    lines=[
        "# V2.9 固定样本到期研究结论（非交易指令）",
        "",
        f"**原始入场：** {verdict['fixed_entry_session']}；**固定到期：** {verdict['fixed_exit_session']}；**股票数：** 122。",
        f"**来源覆盖：** {verdict['quote_source_eligible_count']}/122；**官方基准：** {verdict['benchmark_source_status']}。",
        "",
        "## 原始 122 股策略",
        f"- 结果状态：`{parent['status']}`",
        f"- 扣除预设 0.30% 往返成本的等权收益：**{percent(parent.get('mean_net'))}**",
        f"- 相对 H00300 全收益指数的净超额：**{percent(parent.get('mean_net_excess'))}**",
        f"- 超额收益方向：{comparison(parent.get('mean_net_excess'))}",
        f"- 个股净超额中位数：{percent(parent.get('median_individual_net_excess'))}；跑赢比例：{percent(parent.get('outperforming_name_fraction'))}",
        "",
        "## 冻结 8 股精选（同一时段、同一母样本）",
    ]
    if eight is None:
        lines.append("- 8 股结果：尚未提供或尚未落盘。不能据此推断胜负。")
    else:
        if not completed:
            raise ValueError("EIGHT_CANNOT_COMPLETE_BEFORE_PARENT")
        expected=evaluate_eight(outcome,now=now)
        if eight!=expected or eight.get("status")!=SINGLE:
            raise ValueError("EIGHT_OUTCOME_NOT_REPRODUCIBLE")
        lines.extend([
            f"- 等权净收益：**{percent(eight['selected_eight_mean_net'])}**",
            f"- 8 股减 122 股等权净收益：**{percent(eight['selected_eight_minus_parent_122'])}**（{comparison(eight['selected_eight_minus_parent_122'])}）",
            f"- 8 股减 H00300：**{percent(eight['selected_eight_minus_H00300_total_return'])}**",
            f"- 每股最低交易单位下的资金加权净收益：**{percent(eight['min_lot_weighted_net_proxy'])}**",
            f"- 最低单位资金加权减 H00300：**{percent(eight['min_lot_minus_H00300_total_return'])}**",
            f"- 资金加权减等权：**{percent(eight['min_lot_minus_equal_eight_net_proxy'])}**",
            "- 这些都是收盘价纸面代理，不证明有成交、可按价格建仓或账户风险已满足。",
        ])
    lines.extend(["","## 310 股条件对照（同次观察，非独立样本）"])
    if control is None and control_prices is None:
        lines.append("- 310 股结果：尚未提供或尚未落盘；不影响 122 股母实验。")
    elif control is None or control_prices is None:
        raise ValueError("CONTROL_PRICES_AND_RESULT_MUST_BE_PAIRED")
    else:
        if not completed:
            raise ValueError("CONTROL_CANNOT_COMPLETE_BEFORE_PARENT")
        expected=evaluate_control(control_prices,outcome,now=now)
        if (control.get("status")!=expected.get("status")
            or control.get("fixed_entry_session")!=expected.get("fixed_entry_session")
            or control.get("fixed_exit_session")!=expected.get("fixed_exit_session")
            or control.get("selected_total")!=122
            or control.get("comparator_total")!=188):
            raise ValueError("CONTROL_IDENTITY_NOT_REPRODUCIBLE")
        for metric in ("selected_minus_comparator","selected_minus_clean_88"):
            x,y=control.get(metric),expected.get(metric)
            if not ((x is None and y is None) or
                    (isinstance(x,(int,float)) and isinstance(y,(int,float))
                     and math.isclose(x,y,rel_tol=1e-12,abs_tol=1e-12))):
                raise ValueError("CONTROL_METRIC_NOT_REPRODUCIBLE:"+metric)
        lines.extend([
            f"- 固定 122 股减原始未入选 188 股：**{percent(control.get('selected_minus_comparator'))}**（{comparison(control.get('selected_minus_comparator'))}）",
            f"- 次级 122 股减无指定风险标记的 88 股：**{percent(control.get('selected_minus_clean_88'))}**",
            "- 122/188 与 122/88 只能提供描述性分组对比，不构成独立重复试验或因果识别。",
        ])
    lines.extend([
        "",
        "## 投资决策",
        "**NO ACTION：目前不足以授权实盘 BUY。**",
        "",
        "理由：一次共同市场行情中的股票与基准差值，不等于独立样本外可重复的预测能力；"
        "且交易成交价、个人资金与止损/止盈规则仍未核验。",
        "**不能**因为超额收益为正就事后提高证据等级或更改冻结筛选规则。",
        "",
    ])
    return "\n".join(lines)

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--verdict",required=True,type=Path)
    ap.add_argument("--outcomes",required=True,type=Path)
    ap.add_argument("--eight",type=Path)
    ap.add_argument("--control",type=Path)
    ap.add_argument("--control-prices",type=Path)
    ap.add_argument("--out",required=True,type=Path)
    args=ap.parse_args()
    now=datetime.now(timezone.utc)
    if now<datetime.fromisoformat("2026-11-27T16:30:00+08:00").astimezone(timezone.utc):
        raise SystemExit("PRE_MATURITY_NO_OUTCOME_READING")
    if args.out.exists():
        raise ValueError("DO_NOT_OVERWRITE_MATURITY_BRIEF")
    def load(p):
        return json.loads(p.read_text(encoding="utf-8")) if p is not None else None
    rendered=brief(load(args.verdict),load(args.outcomes),
                   load(args.eight),load(args.control),load(args.control_prices),now)
    args.out.parent.mkdir(parents=True,exist_ok=True)
    args.out.write_text(rendered,encoding="utf-8")
    print("V29_READ_ONLY_MATURITY_DECISION_BRIEF_WRITTEN_NO_BUY")

if __name__=="__main__":
    main()
