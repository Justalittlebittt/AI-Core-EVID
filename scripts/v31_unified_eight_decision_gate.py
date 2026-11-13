#!/usr/bin/env python3
"""One source-bound A-share research -> market -> account -> discipline gate.

Only consumes immutable archived research/market evidence. Never fetches a
price, places an order, invents a personal stop, or promotes retrospective alpha.
Optional private inputs remain local (never written to the repository).
"""
from __future__ import annotations

import argparse
import copy
import gzip
import hashlib
import json
from datetime import date, datetime
from pathlib import Path
from decimal import Decimal

from v29_eight_portfolio_capacity import ROOT, assess
from v29_decision_packet_adapter import adapt_and_evaluate
from v31_research_candidate_decision import build as archived_candidates
from v31_eight_closed_session_execution_context import security_code

DIR = Path("research/v31_20261110_eight_real_closed_session")
SOURCE = DIR / "RAW_EIGHT_EOD_SOURCE.json.gz"
EOD = DIR / "RESULT.json"
LATEST = DIR / "LATEST_AVAILABLE_VENDOR_CLOSE_20261109.json"
SCHEMA = "V31_ONE_ENTRY_SOURCE_BOUND_EIGHT_STOCK_DECISION_GATE_V1"


def digest(b):
    return hashlib.sha256(b).hexdigest()


def load_archived_market(root):
    compressed = (root / SOURCE).read_bytes()
    original = gzip.decompress(compressed)
    source = json.loads(original)
    eod = json.loads((root / EOD).read_bytes())
    latest = json.loads((root / LATEST).read_bytes())
    seal = digest(original)
    if (latest.get("archived_capture_sha256") != seal
        or eod.get("original_raw_source_sha256") != seal
        or latest.get("archived_capture") != SOURCE.as_posix()
        or latest.get("schema") != "V31_EIGHT_FROZEN_LATEST_AVAILABLE_20261109_VENDOR_EOD_CONTEXT_V1"
        or eod.get("schema") != "V31_EIGHT_FIXED_NAMES_20261110_CLOSED_SESSION_CONTEXT_V1"
        or source.get("vendor") != "baostock==0.9.4"
        or source.get("captured_at_utc") != eod.get("captured_at_utc")
        or source.get("captured_at_utc") != latest.get("data_captured_at_utc")
        or source.get("end") != "2026-11-10"
        or latest.get("observed_vendor_latest_session") != "2026-11-09"
        or latest.get("not_a_current_2026_11_10_close") is not True
        or latest.get("trade_authorized") is not False
        or eod.get("trade_authorized") is not False):
        raise ValueError("ARCHIVED_MARKET_SEALS_OR_VINTAGES_DIVERGED")
    return source,eod,latest,seal


def validate_market_by_identity(source,eod,latest,ids):
    archived = latest["rows"]
    eodrows = eod["rows"]
    observed = source["raw"]
    if (len(ids)!=8 or len(set(ids))!=8
        or len(archived)!=8 or len(eodrows)!=8 or len(observed)!=8
        or [z["security_id"] for z in archived]!=ids
        or [z["security_id"] for z in eodrows]!=ids
        or set(observed)!=set(ids)
        or latest["frozen_eight_count"]!=8
        or eod["sample_count"]!=8):
        raise ValueError("EIGHT_ARCHIVE_IDENTITY_DRIFT")
    notional=Decimal(0)
    checked=[]
    for sid,one,old in zip(ids,archived,eodrows):
        bars=observed[sid]
        if not isinstance(bars,list) or not bars:
            raise ValueError("EIGHT_RAW_BARS_NOT_REPRODUCIBLE:"+sid)
        dates=set()
        for bar in bars:
            dt=bar.get("date")
            if (bar.get("code")!=security_code(sid) or dt in dates
                or not source["start"]<=dt<=source["end"]
                or bar.get("adjustflag")!="3"):
                raise ValueError("RAW_BAR_CODE_DATE_OR_ADJUSTFLAG_INVALID:"+sid)
            dates.add(dt)
        latest_day=max(dates)
        last=next(z for z in bars if z["date"]==latest_day)
        if (latest_day!="2026-11-09"
            or one["latest_available_vendor_session"]!=latest_day
            or old["latest_vendor_bar_date"]!=latest_day
            or old["status"]!="EOD_VENDOR_BAR_MISSING"
            or old["target_2026_11_10_eod_close_cny"] is not None
            or last["tradestatus"]!="1" or last["isST"]!="0"
            or one["vendor_20261109_nonST_with_positive_volume"] is not True
            or one["broker_limit_order_fill_confirmed"] is not False):
            raise ValueError("EOD_MISSING_OR_1109_STATUS_CONTRADICTION:"+sid)
        try:
            close=Decimal(str(last["close"]))
            volume=Decimal(str(last["volume"]))
            amount=Decimal(str(last["amount"]))
            shares=one["one_lot_shares"]
        except (ValueError,TypeError,KeyError) as exc:
            raise ValueError("RAW_MARKET_NUMBERS_UNREADABLE:"+sid) from exc
        if (close<=0 or not close.is_finite()
            or volume<=0 or not volume.is_finite()
            or amount<=0 or not amount.is_finite()
            or type(shares) is not int or shares!=100
            or one["latest_vendor_unadjusted_close_cny"] != float(close)
            or Decimal(str(one["one_lot_proxy_cost_cny"])) != close*shares):
            raise ValueError("DERIVED_1109_BAR_OR_LOT_DOES_NOT_MATCH_SOURCE:"+sid)
        notional+=close*shares
        checked.append({
            "security_id":sid,
            "latest_available_close_date":latest_day,
            "latest_available_close_cny":float(close),
            "minimum_lot_shares":shares,
            "minimum_lot_reference_cny":float(close*shares),
            "closed_session_source_status":"VENDOR_OBSERVED_20261109_NOT_EXECUTABLE_FILL",
            "st_and_positive_volume_at_reference_date":True,
            "20261110_closed_session_available_in_capture":False,
            "trade_authorized":False,
        })
    if (notional!=Decimal(str(latest["available_20261109_minlot_proxy_cost_cny"]))
        or Decimal(str(latest["reference_20261102_minlot_proxy_cost_cny"]))!=Decimal(54558)
        or eod["nonst_positive_volume_quote_count"]!=0
        or eod["basket_min_lot_eod_notional_cny_if_complete"] is not None):
        raise ValueError("MARKET_TOTALS_OR_1110_GAP_INCONSISTENT")
    return checked,float(notional)


def build(root=ROOT, private=None):
    root=Path(root)
    research=archived_candidates(root)
    if (research["candidate_count"]!=8
        or research["candidate_strategy_independently_validated"] is not False
        or research["live_buy_eligibility"]!="NOT_AUTHORIZED"
        or research["future_outcomes_read"] is not False):
        raise ValueError("STRATEGY_VALIDITY_MUST_BE_SOURCE_BOUND")
    source,eod,latest,seal=load_archived_market(root)
    ids=[x["security_id"] for x in research["candidates"]]
    market,notional=validate_market_by_identity(source,eod,latest,ids)
    if (eod["original_eight_frozen_sealed_entry_sha256"]
        !=research["source_sha256"]["sealed_122_nov02_entry"]
        or latest["reference_20261102_minlot_proxy_cost_cny"]
        !=research["eight_minimum_lot_paper_entry_notional_cny"]):
        raise ValueError("FROZEN_8_PARENT_IDENTITY_OR_PRICE_CHANGED")
    audit={"status":"NOT_EVALUATED_NO_PRIVATE_ACCOUNT_INPUT",
           "paper_capacity_feasible":None,"basket_issues":[],"per_name":[]}
    packet_results={}
    if private is not None:
        if not isinstance(private,dict) or set(private)-{"account","positions","decision_packets"}:
            raise ValueError("UNRECOGNIZED_PRIVATE_FIELDS")
        if ("account" in private)!=( "positions" in private):
            raise ValueError("ACCOUNT_AND_POSITIONS_MUST_BE_TOGETHER")
        if "account" in private:
            # The existing portfolio assessor validates actual caller supplied
            # cash, board permissions, sizes and stops without inventing them.
            scored=assess(ids,private["account"],private["positions"])
            audit={"status":"USER_INPUT_PAPER_CAPACITY_ONLY_NOT_BROKER_CONFIRMED",
                   "paper_capacity_feasible":scored["paper_capacity_feasible"],
                   "basket_issues":scored["basket_issues"],
                   "per_name":scored["positions"],
                   "user_quote_not_certified_as_current_market":True,
                   "stop_gap_risk_unbounded":scored["stop_gap_risk_not_bounded"]}
        packet_list=private.get("decision_packets",[])
        if not isinstance(packet_list,list):
            raise ValueError("DECISION_PACKETS_MUST_BE_LIST")
        for item in packet_list:
            if not isinstance(item,dict) or set(item)!={"security_id","packet"}:
                raise ValueError("INVALID_PRIVATE_DECISION_PACKET")
            sid=item["security_id"]
            if sid not in ids or sid in packet_results:
                raise ValueError("DECISION_PACKET_SECURITY_ID_UNKNOWN_OR_DUPLICATE")
            packet=copy.deepcopy(item["packet"])
            # Source-bound evidence outranks an unverified user-supplied claim
            # of STRONG or MODERATE. The original packet is NOT altered on disk.
            if not isinstance(packet,dict) or not isinstance(packet.get("validity"),dict):
                raise ValueError("INVALID_DECISION_PACKET")
            claimed=packet["validity"].get("evidence_strength")
            packet["validity"]["evidence_strength"]="INSUFFICIENT"
            result=adapt_and_evaluate(packet)
            decision=result["discipline_decision"]["decision"]
            # Insufficient alpha must block risk increases, not a legitimate
            # REDUCE/EXIT of an already-held position.
            if (decision=="ACTION_ELIGIBLE"
                and result["discipline_input"]["action_type"] not in ("REDUCE","EXIT")):
                raise ValueError("DISCIPLINE_FAIL_CLOSED_EVIDENCE_INSIDE_PACKET")
            packet_results[sid]={
                "claimed_user_evidence_strength":claimed,
                "effective_source_bound_evidence_strength":"INSUFFICIENT",
                "discipline_decision":result["discipline_decision"],
                "packet_status":result["packet_status"],
                "source_overrode_unverified_reported_strength":claimed!="INSUFFICIENT",
            }
    reasons=[
        "NO_INDEPENDENTLY_VALIDATED_PREDICTIVE_EDGE",
        "20261110_CLOSED_SESSION_UNAVAILABLE_IN_CAPTURE",
        "VENDOR_PRICE_NOT_CERTIFIED_ORDER_FILL",
        "LIMIT_UP_DOWN_ORDER_BOOK_NOT_VERIFIED",
        "BROKER_TRADING_PERMISSIONS_NOT_CONFIRMED",
    ]
    if audit["status"]=="NOT_EVALUATED_NO_PRIVATE_ACCOUNT_INPUT":
        reasons.append("NO_VERIFIED_PRIVATE_CASH_STOP_AND_POSITION_INPUT")
    if audit["paper_capacity_feasible"] is False:
        reasons.append("CALLER_SUPPLIED_CAPACITY_CHECK_FAILED")
    rows=[]
    for i,(candidate,quote) in enumerate(zip(research["candidates"],market)):
        if candidate["security_id"]!=quote["security_id"]:
            raise ValueError("CANDIDATE_TO_PRICE_JOIN_DRIFT")
        rows.append({
            "research_rank_not_forecast_strength":candidate["rank_in_predeclared_2026_research"],
            "security_id":candidate["security_id"],
            "quote_reference":quote,
            "account_paper_capacity":next((x for x in audit["per_name"]
                                         if x["security_id"]==candidate["security_id"]),None),
            "discipline_packet_preview":packet_results.get(candidate["security_id"]),
            "decision":"BLOCK_BUY",
            "reasons":reasons,
        })
    return {
        "schema":SCHEMA,
        "decision_scope":"FROZEN_RESEARCH_EIGHT_NOT_LATEST_FULL_MARKET_RANK",
        "original_signal_date":"2026-10-30",
        "market_capture_time_utc":source["captured_at_utc"],
        "last_available_vendor_close_date":"2026-11-09",
        "requested_today_close_in_archive":"2026-11-10",
        "signal_is_not_verified_alpha":True,
        "source_sha256":{
            **research["source_sha256"],
            "latest_saved_vendor_daily_bars":seal,
        },
        "strategy_evidence":{
            "grade":"INSUFFICIENT",
            "independent_alpha_validated":False,
            "prior_2025_comparison_is_different_rule":True,
        },
        "market_evidence":{
            "status":"ONLY_PREVIOUS_TRADING_SESSION_EOD_AVAILABLE_AT_CAPTURE",
            "vendor_unadjusted_close_count":8,
            "current_session_eod_count":0,
            "min_lot_notional_at_20261109_vendor_closes_cny":notional,
            "broker_fill_or_order_book_verified":False,
        },
        "private_account_and_stop_gate":audit,
        "existing_discipline_adapter_used_only_when_user_supplies_full_packets":bool(packet_results),
        "blocking_reasons":reasons,
        "stocks":rows,
        "stock_count":len(rows),
        "action":"NO_ACTION_INSUFFICIENT_PREDICTIVE_EVIDENCE",
        "trade_authorized":False,
        "live_buy_eligibility":"NOT_AUTHORIZED",
        "user_input_or_broker_order_written_to_repository":False,
    }


def render(report):
    if (report.get("schema")!=SCHEMA
        or report.get("trade_authorized") is not False
        or report.get("live_buy_eligibility")!="NOT_AUTHORIZED"
        or report.get("stock_count")!=8
        or report.get("strategy_evidence",{}).get("grade")!="INSUFFICIENT"
        or report.get("strategy_evidence",{}).get("independent_alpha_validated") is not False
        or report.get("signal_is_not_verified_alpha") is not True
        or any(x["decision"]!="BLOCK_BUY" for x in report.get("stocks",[]))):
        raise ValueError("INTEGRATED_GATE_UNSAFE_TO_RENDER")
    lines=[
        "# AI Core V3.1｜统一股票决策门（真实8股、只读）",
        "",
        "研究股票身份冻结于2026-10-30。行情仅来自2026-11-10采集时当时可取得的2026-11-09非官方日线。",
        "**不代表2026-11-10收盘或当前可成交价格，也不是股票推荐。**",
        "",
        "| 原研究序号 | 股票 | 11月9日行情参考价 | 最低一手名义金额 | 决策 |",
        "|---:|---|---:|---:|---|",
    ]
    for r in report["stocks"]:
        x=r["quote_reference"]
        lines.append(
            f"| {r['research_rank_not_forecast_strength']} | {r['security_id']} | "
            f"¥{x['latest_available_close_cny']:.2f} | ¥{x['minimum_lot_reference_cny']:,.2f} | 阻止新增买入 |"
        )
    lines.extend([
        "",
        f"8股最低一手参考金额（不含手续费和滑点）：¥{report['market_evidence']['min_lot_notional_at_20261109_vendor_closes_cny']:,.2f}。",
        f"独立预测证据：{report['strategy_evidence']['grade']}；账户风控：{report['private_account_and_stop_gate']['status']}。",
        "数据、涨跌停盘口、券商权限及真正成交均未完成实盘认证，既有风控模块仍供私人输入后只读评估。",
        "**最终：NOT_AUTHORIZED / NO BUY。**",
        "",
    ])
    return "\n".join(lines)




def select_one(report, security_id):
    """Project an already source-bound eight-name result to one read-only JSON case."""
    # Retain the existing no-trade output boundary; do not create a second gate.
    render(report)
    matches=[r for r in report["stocks"] if r["security_id"]==security_id]
    if len(matches)!=1:
        raise ValueError("UNKNOWN_OR_DUPLICATE_RESEARCH_SECURITY")
    row=matches[0]
    audit=report["private_account_and_stop_gate"]
    account={
        "status":audit["status"],
        "paper_capacity_feasible":audit["paper_capacity_feasible"],
        "basket_issues":audit["basket_issues"],
    }
    if "stop_gap_risk_unbounded" in audit:
        account["stop_gap_risk_unbounded"]=audit["stop_gap_risk_unbounded"]
    case={
        "schema":"V31_ONE_STOCK_SOURCE_BOUND_READ_ONLY_DECISION_CASE_V1",
        "security_id":security_id,
        "source_scope":report["decision_scope"],
        "research_rank_not_forecast_strength":row["research_rank_not_forecast_strength"],
        "original_signal_date":report["original_signal_date"],
        "market_capture_time_utc":report["market_capture_time_utc"],
        "market_reference":row["quote_reference"],
        "source_sha256":report["source_sha256"],
        "strategy_evidence":report["strategy_evidence"],
        "market_evidence":report["market_evidence"],
        "private_account_and_stop_gate":account,
        "account_paper_capacity":row["account_paper_capacity"],
        "discipline_packet_preview":row["discipline_packet_preview"],
        "blocking_reasons":row["reasons"],
        "decision":row["decision"],
        "action":report["action"],
        "trade_authorized":False,
        "live_buy_eligibility":"NOT_AUTHORIZED",
        "historical_vendor_quote_not_broker_fill":True,
        "private_input_not_written_to_repository":True,
    }
    # Detach nested maps/lists: callers may annotate the exported JSON without
    # mutating the source-bound eight-stock evidence still held in memory.
    return copy.deepcopy(case)


def render_one(report, security_id):
    """One auditable historical research Decision Case, never an order ticket."""
    # Reuse the existing display's one high-consequence no-trade boundary.
    render(report)
    matches=[r for r in report["stocks"] if r["security_id"]==security_id]
    if len(matches)!=1:
        raise ValueError("UNKNOWN_OR_DUPLICATE_RESEARCH_SECURITY")
    row=matches[0]
    quote=row["quote_reference"]
    hashes=report["source_sha256"]
    lines=[
        "# AI Core V3.1｜单只股票决策卡（只读）", "",
        f"**股票：** {security_id}；**历史研究顺序：** {row['research_rank_not_forecast_strength']}（不是预测能力排序）。",
        f"**信号日期：** {report['original_signal_date']}；**行情参考日期：** {quote['latest_available_close_date']}。",
        f"**参考价格：** ¥{quote['latest_available_close_cny']:.2f}（非官方供应商历史收盘，非当前盘口、成交报价或买入限价）。",
        f"**最低交易单位：** {quote['minimum_lot_shares']}股；**最低一手历史参考金额：** ¥{quote['minimum_lot_reference_cny']:,.2f}（不含费用）。",
        f"**本次归档所要求的2026-11-10收盘行情：** 缺失；本卡仅复用较早的{quote['latest_available_close_date']}记录。", "",
        "## 证据身份与科学有效性", "",
        f"- 独立预测证据等级：**{report['strategy_evidence']['grade']}**；没有经过认证的策略超额收益证据。",
        f"- 原始冻结入场快照 SHA256：`{hashes['sealed_122_nov02_entry']}`",
        f"- 已归档历史行情原始记录 SHA256：`{hashes['latest_saved_vendor_daily_bars']}`",
        "- 哈希用于绑定仓库归档字节，不证明行情是交易所官方报价，也不证明行情的历史决策时点可得性。",
        "- 冻结8股身份及历史数据未变更；不读取受保护的独立样本外结果。", "",
        "## 风险与交易资格", "",
        f"- 账户/止损审查状态：**{report['private_account_and_stop_gate']['status']}**。",
        f"- 纪律模块判定：**{row['discipline_packet_preview']['discipline_decision']['decision'] if row['discipline_packet_preview'] else 'NOT_EVALUATED_NO_USER_DECISION_PACKET'}**。",
        f"- 本股票决策：**{row['decision']}**。下单、加仓均未获授权。",
        "- 已触发的阻断因素：",
    ]
    lines.extend(f"  - {reason}" for reason in row["reasons"])
    paper=row["account_paper_capacity"]
    if paper is not None:
        audit=report["private_account_and_stop_gate"]
        lines.extend([
            "",
            "## 用户本地参数的纸面风险核算（非券商成交认证）", "",
            f"- 本股用户输入数量：{paper['shares']}股；用户参考名义敞口：¥{paper['reference_notional_cny']}。",
            f"- 用户指定参考价：¥{paper['user_reference_price_cny']}；用户指定止损价：¥{paper['user_stop_price_cny']}（均由本地参数提供，并非系统自动给出的下单建议）。",
            f"- 按（用户参考价－用户止损价）×{paper['shares']}股计算的**本股**止损距离风险：¥{paper['stop_distance_loss_cny']}（未计跳空与滑点）。",
            f"- 与2026-11-09归档供应商收盘参考价¥{quote['latest_available_close_cny']:.2f}为不同来源；纸面容量计算只采用用户指定参考价，不会用过时行情覆盖用户数据。",
            f"- 组合层面纸面容量是否通过：**{'通过' if audit['paper_capacity_feasible'] else '未通过'}**（仅针对用户本地提交的八股篮子）。",
            "- 本股个别约束：" + ("、".join(paper["issues"]) if paper["issues"] else "未触发纸面个股限制"),
            "- 全篮子共享现金及总风险约束：" + ("、".join(audit["basket_issues"]) if audit["basket_issues"] else "未触发纸面组合限制"),
            "- 账户参数只在本地进程读取和打印；本命令不写入仓库。历史参考价与用户输入价可能不同。",
            "- 纸面通过不等于有效策略、当前交易权限、跳空止损保障或实际成交。",
        ])
    lines.extend(["", "**结论：NOT_AUTHORIZED / NO BUY；下一步仅限补充独立证据、有效行情与用户提供的风险输入，不得下单。**", ""])
    return "\n".join(lines)


def main():
    p=argparse.ArgumentParser(description="Sealed evidence+EOD+capital+discipline single decision gate; no broker orders.")
    p.add_argument("--format",choices=("markdown","json"),default="markdown")
    p.add_argument("--private-input",type=Path,help="Optional LOCAL account + positions and/or existing V2.9 decision packets; never committed.")
    p.add_argument("--security-id",help="Render one fixed-eight security as a read-only Decision Case (Markdown or JSON).")
    args=p.parse_args()
    private=json.loads(args.private_input.read_text(encoding="utf-8")) if args.private_input else None
    result=build(private=private)
    if args.format=="json":
        output=select_one(result,args.security_id) if args.security_id else result
        print(json.dumps(output,ensure_ascii=False,indent=2))
    else:
        print(render_one(result,args.security_id) if args.security_id else render(result))


if __name__=="__main__":
    main()
