from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from v284_ai_core_evidence_classifier import classify_text, stable_sha256

def classify_pages(rows:list[dict]) -> dict:
    decisions=[]
    seen_pages=set()
    for row in sorted(rows,key=lambda r:int(r["page_number"])):
        page=int(row["page_number"])
        if page<=0 or page in seen_pages:
            raise RuntimeError("PAGE_PROVENANCE_BLOCKED")
        seen_pages.add(page)
        text=str(row.get("text") or "")
        d=classify_text(text)
        decisions.append({"page_number":page,**d.as_dict()})

    eligible=[x for x in decisions if x["classification_state"]=="ELIGIBLE_AI_CORE"]
    adopter=[x for x in decisions if x["classification_state"]=="EXCLUDED_AI_ADOPTER_ONLY"]
    rnd=[x for x in decisions if x["classification_state"]=="EXCLUDED_AI_RND_ONLY"]

    if eligible:
        state="ELIGIBLE_AI_CORE"
        evidence=eligible[0]
    elif adopter and rnd:
        state="BLOCKED_AMBIGUOUS"
        evidence={
            "page_number":min(adopter[0]["page_number"],rnd[0]["page_number"]),
            "classification_state":"BLOCKED_AMBIGUOUS",
            "evidence_sentence":"",
            "matched_ai_role":[],
            "matched_commerciality":[],
            "reason":"mixed_adopter_only_and_rnd_only_without_positive_conjunction",
        }
    elif adopter:
        state="EXCLUDED_AI_ADOPTER_ONLY"; evidence=adopter[0]
    elif rnd:
        state="EXCLUDED_AI_RND_ONLY"; evidence=rnd[0]
    else:
        state="NOT_ESTABLISHED"
        evidence={
            "page_number":0,
            "classification_state":state,
            "evidence_sentence":"",
            "matched_ai_role":[],
            "matched_commerciality":[],
            "reason":"no_verified_positive_or_explicit_exclusion_evidence",
        }

    out={
        "classification_state":state,
        "evidence":evidence,
        "page_decisions":decisions,
        "evaluated_page_count":len(decisions),
    }
    out["decision_sha256"]=stable_sha256(out)
    return out

def from_csv(path:Path):
    x=pd.read_csv(path,dtype={"page_number":int}).fillna("")
    if not {"page_number","text"}.issubset(x.columns):
        raise RuntimeError("PAGE_TEXT_SCHEMA_BLOCKED")
    return classify_pages(x[["page_number","text"]].to_dict("records"))

def self_test():
    tests=[]
    def ck(name,rows,expected):
        try:
            got=classify_pages(rows)
            ok=got["classification_state"]==expected
            tests.append({"name":name,"pass":ok,"expected":expected,"actual":got["classification_state"],
                          "page_number":got["evidence"]["page_number"]})
        except RuntimeError as e:
            tests.append({"name":name,"pass":False,"expected":expected,"actual":str(e)})
    ck("A01_positive_page",[
        {"page_number":1,"text":"行业正在关注人工智能。"},
        {"page_number":2,"text":"公司AI服务器已完成批量交付，并向多家客户销售。"}
    ],"ELIGIBLE_AI_CORE")
    ck("A02_positive_preserves_page",[
        {"page_number":1,"text":"普通介绍。"},
        {"page_number":7,"text":"本公司人工智能芯片已经量产并实现销售收入。"}
    ],"ELIGIBLE_AI_CORE")
    ck("A03_adopter_only",[
        {"page_number":3,"text":"公司内部使用人工智能工具提升办公效率。"}
    ],"EXCLUDED_AI_ADOPTER_ONLY")
    ck("A04_rnd_only",[
        {"page_number":4,"text":"公司正在研发大模型产品，目前尚未商业化。"}
    ],"EXCLUDED_AI_RND_ONLY")
    ck("A05_mixed_exclusions_ambiguous",[
        {"page_number":1,"text":"公司内部使用人工智能工具提升办公效率。"},
        {"page_number":2,"text":"公司正在研发大模型产品，目前尚未商业化。"}
    ],"BLOCKED_AMBIGUOUS")
    ck("A06_positive_overrides_weaker_language",[
        {"page_number":1,"text":"公司正在研发大模型产品，目前尚未商业化。"},
        {"page_number":2,"text":"本公司AI服务器已向客户批量交付。"}
    ],"ELIGIBLE_AI_CORE")
    ck("A07_not_established",[
        {"page_number":1,"text":"公司销售数据中心电源产品。"},
        {"page_number":2,"text":"人工智能行业需求快速增长。"}
    ],"NOT_ESTABLISHED")
    tests.append({
        "name":"A08_evidence_page_is_7",
        "pass":classify_pages([
            {"page_number":1,"text":"普通介绍。"},
            {"page_number":7,"text":"本公司人工智能芯片已经量产并实现销售收入。"}
        ])["evidence"]["page_number"]==7
    })
    blocked=False
    try:
        classify_pages([{"page_number":1,"text":"a"},{"page_number":1,"text":"b"}])
    except RuntimeError:
        blocked=True
    tests.append({"name":"A09_duplicate_page_blocks","pass":blocked})
    result={
        "schema":"AI_CORE_EVID_V2_8_4_PAGE_SCOPED_CLASSIFIER_SELFTEST_V1",
        "tests":tests,
        "passed":sum(x["pass"] for x in tests),
        "total":len(tests),
        "all_pass":all(x["pass"] for x in tests),
    }
    result["receipt_sha256"]=stable_sha256(result)
    print(json.dumps(result,ensure_ascii=False,indent=2))
    if not result["all_pass"]: raise SystemExit(2)

def main():
    ap=argparse.ArgumentParser()
    sub=ap.add_subparsers(dest="cmd",required=True)
    sub.add_parser("self-test")
    c=sub.add_parser("classify-csv")
    c.add_argument("--page-text",required=True)
    a=ap.parse_args()
    if a.cmd=="self-test":
        self_test()
    else:
        print(json.dumps(from_csv(Path(a.page_text)),ensure_ascii=False,indent=2))

if __name__=="__main__":
    main()
