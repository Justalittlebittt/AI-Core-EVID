from __future__ import annotations

import argparse
import json
import re

SKIP_PATTERNS=[
    re.compile(r"^关于参加.*业绩说明会.*公告$"),
    re.compile(r"^关于召开.*业绩说明会.*公告$"),
]

def normalize_title(title:str)->str:
    return re.sub(r"\s+","",str(title or "").replace("<em>","").replace("</em>",""))

def triage_title(title:str)->dict:
    t=normalize_title(title)
    for p in SKIP_PATTERNS:
        if p.search(t):
            return {
                "triage_state":"SKIP_LOW_INFORMATION_ADMIN_NOTICE",
                "normalized_title":t,
                "matched_pattern":p.pattern,
                "eligibility_effect":"NONE_NO_STATE_CHANGE",
            }
    return {
        "triage_state":"MATERIALIZE_CANDIDATE",
        "normalized_title":t,
        "matched_pattern":"",
        "eligibility_effect":"NONE_CANDIDATE_ROUTING_ONLY",
    }

def self_test():
    cases=[
      ("关于参加科创板2026年半年度人工智能行业集体业绩说明会的公告","SKIP_LOW_INFORMATION_ADMIN_NOTICE"),
      ("奇安信关于参加科创板2026年半年度人工智能行业集体业绩说明会的公告","MATERIALIZE_CANDIDATE"),
      ("关于召开2026年半年度业绩说明会的公告","SKIP_LOW_INFORMATION_ADMIN_NOTICE"),
      ("2026年半年度报告","MATERIALIZE_CANDIDATE"),
      ("关于子公司算力服务合同的进展公告","MATERIALIZE_CANDIDATE"),
      ("投资者关系活动记录表","MATERIALIZE_CANDIDATE"),
      ("关于AI服务器产品订单的公告","MATERIALIZE_CANDIDATE"),
    ]
    # The issuer-name-prefixed attendance notice is intentionally not skipped by
    # the anchored rule until we normalize/recognize that title family safely.
    tests=[]
    for i,(title,expected) in enumerate(cases,1):
        got=triage_title(title)["triage_state"]
        tests.append({"name":f"Q{i:02d}","pass":got==expected,"title":title,"expected":expected,"actual":got})
    result={"schema":"AI_CORE_EVID_V2_8_4_CANDIDATE_TRIAGE_SELFTEST_V1",
            "tests":tests,"passed":sum(x["pass"] for x in tests),"total":len(tests),
            "all_pass":all(x["pass"] for x in tests)}
    print(json.dumps(result,ensure_ascii=False,indent=2))
    if not result["all_pass"]: raise SystemExit(2)

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("command",choices=["self-test","title"])
    ap.add_argument("--title")
    a=ap.parse_args()
    if a.command=="self-test": self_test()
    else:
        print(json.dumps(triage_title(a.title or ""),ensure_ascii=False,indent=2))

if __name__=="__main__":
    main()
