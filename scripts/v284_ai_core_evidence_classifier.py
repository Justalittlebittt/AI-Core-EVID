from __future__ import annotations

import argparse
import hashlib
import json
import re
from dataclasses import dataclass
from typing import Iterable

AI_DIRECT = [
    "人工智能", "生成式人工智能", "大模型", "基础模型", "机器学习", "深度学习",
    "ai芯片", "人工智能芯片", "npu", "gpu", "ai服务器", "智能计算",
    "智算", "ai加速卡", "机器视觉", "ai算法", "人工智能算法"
]
COMMERCIAL = [
    "销售", "营业收入", "收入", "出货", "交付", "订单", "合同", "客户",
    "量产", "批量生产", "商业化", "商用", "收费", "提供服务", "上线运营"
]
RND_ONLY = [
    "计划研发", "拟研发", "正在研发", "探索", "研究阶段", "预研",
    "未来计划", "拟开展"
]
NEGATIVE_COMMERCIAL = [
    "尚未形成收入", "尚未商业化", "尚未量产", "尚无订单", "尚无客户"
]
INTERNAL_USE = [
    "内部使用", "办公效率", "内部管理", "内部运营", "自身生产效率", "内部提效"
]
COMPANY_SUBJECT = ["公司", "本公司", "子公司", "集团", "我们"]
THIRD_PARTY_CONTEXT = ["行业", "市场趋势", "客户行业", "被投企业", "参股公司"]


def stable_sha256(obj) -> str:
    b = json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(b).hexdigest()


def normalize_text(s: str) -> str:
    return re.sub(r"\s+", "", str(s or "")).lower()


def split_sentences(text: str) -> list[str]:
    return [x for x in re.split(r"[。！？；;\n]+", str(text or "")) if x.strip()]


def hits(text: str, terms: Iterable[str]) -> list[str]:
    t = normalize_text(text)
    return [x for x in terms if normalize_text(x) in t]


@dataclass
class Decision:
    state: str
    evidence_sentence: str
    ai_hits: list[str]
    commercial_hits: list[str]
    reason: str

    def as_dict(self):
        return {
            "classification_state": self.state,
            "evidence_sentence": self.evidence_sentence,
            "matched_ai_role": self.ai_hits,
            "matched_commerciality": self.commercial_hits,
            "reason": self.reason,
        }


def classify_text(text: str) -> Decision:
    sentences = split_sentences(text)
    eligible = []
    adopter = []
    rnd = []

    for raw in sentences:
        s = normalize_text(raw)
        ah = hits(s, AI_DIRECT)
        if not ah:
            continue
        ch = hits(s, COMMERCIAL)
        sh = hits(s, COMPANY_SUBJECT)
        rh = hits(s, RND_ONLY)
        nh = hits(s, NEGATIVE_COMMERCIAL)
        ih = hits(s, INTERNAL_USE)
        third = hits(s, THIRD_PARTY_CONTEXT)

        # Third-party / investee / industry context is never issuer business proof.
        if third:
            continue

        # Explicit internal adoption is never an external AI business.
        if ih and sh:
            adopter.append((raw, ah))
            continue

        # Explicit negation of commercialization has priority over positive-token
        # substring matches such as "尚未商业化" containing "商业化".
        if nh and sh:
            rnd.append((raw, ah))
            continue

        # R&D/future-only statements do not qualify unless the same sentence
        # also contains concrete positive commercialization evidence.
        if rh and not ch and sh:
            rnd.append((raw, ah))
            continue

        # Direct positive evidence requires issuer subject + AI role + commercial
        # operation in the same sentence.
        if sh and ah and ch:
            eligible.append((raw, ah, ch))

    if eligible:
        raw, ah, ch = eligible[0]
        return Decision(
            "ELIGIBLE_AI_CORE", raw, ah, ch,
            "issuer_subject_and_direct_ai_role_and_commercial_operation_same_sentence",
        )
    if adopter:
        raw, ah = adopter[0]
        return Decision(
            "EXCLUDED_AI_ADOPTER_ONLY", raw, ah, [],
            "internal_ai_use_without_external_ai_business",
        )
    if rnd:
        raw, ah = rnd[0]
        return Decision(
            "EXCLUDED_AI_RND_ONLY", raw, ah, [],
            "ai_research_or_plan_without_commercial_operation",
        )
    return Decision(
        "NOT_ESTABLISHED", "", [], [],
        "no_verified_positive_conjunction",
    )


def self_test():
    cases = [
        ("T01_ai_server_delivery",
         "公司AI服务器已完成批量交付，并向多家客户销售。",
         "ELIGIBLE_AI_CORE"),
        ("T02_ai_chip_mass_production",
         "本公司人工智能芯片已经量产并实现销售收入。",
         "ELIGIBLE_AI_CORE"),
        ("T03_machine_vision_commercial",
         "子公司的机器视觉产品采用深度学习算法，已向工业客户交付。",
         "ELIGIBLE_AI_CORE"),
        ("T04_rnd_only",
         "公司正在研发大模型产品，目前尚未商业化。",
         "EXCLUDED_AI_RND_ONLY"),
        ("T05_plan_only",
         "本公司未来计划研发人工智能算法平台。",
         "EXCLUDED_AI_RND_ONLY"),
        ("T06_internal_adoption",
         "公司内部使用人工智能工具提升办公效率。",
         "EXCLUDED_AI_ADOPTER_ONLY"),
        ("T07_industry_trend",
         "人工智能行业需求快速增长，行业服务器出货量持续提升。",
         "NOT_ESTABLISHED"),
        ("T08_generic_datacenter_supplier",
         "公司销售数据中心电源产品。人工智能行业景气度提升。",
         "NOT_ESTABLISHED"),
        ("T09_robot_without_ai",
         "公司机器人产品已实现批量销售。",
         "NOT_ESTABLISHED"),
        ("T10_market_commentary",
         "公司认为大模型将带来广阔市场机会。",
         "NOT_ESTABLISHED"),
        ("T11_rnd_plus_real_sale",
         "公司持续研发人工智能芯片，相关AI芯片已经向客户批量交付。",
         "ELIGIBLE_AI_CORE"),
        ("T12_investee_only",
         "参股公司从事人工智能业务并已实现收入。",
         "NOT_ESTABLISHED"),
    ]
    tests = []
    for name, text, expected in cases:
        got = classify_text(text)
        tests.append({
            "name": name,
            "expected": expected,
            "actual": got.state,
            "pass": got.state == expected,
        })
    result = {
        "schema": "AI_CORE_EVID_V2_8_4_AI_CORE_RULE_ENGINE_SELFTEST_V1",
        "tests": tests,
        "passed": sum(x["pass"] for x in tests),
        "total": len(tests),
        "all_pass": all(x["pass"] for x in tests),
    }
    result["receipt_sha256"] = stable_sha256(result)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if not result["all_pass"]:
        raise SystemExit(2)


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="command", required=True)
    sub.add_parser("self-test")
    c = sub.add_parser("classify-text")
    c.add_argument("--text", required=True)
    args = ap.parse_args()
    if args.command == "self-test":
        self_test()
    else:
        print(json.dumps(classify_text(args.text).as_dict(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
