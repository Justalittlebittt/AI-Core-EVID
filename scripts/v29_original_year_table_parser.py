#!/usr/bin/env python3
"""Conservative year-column table extraction from original Chinese annual PDFs.

A PDF numeric token anywhere in the document is NOT field evidence.
Only a current-fiscal-year table column under the 主要会计数据和财务指标
section, attached to the actual named row, can be a structured candidate.
All competing values, unclear units, missing labels and later restatements
remain explicit. This source parser does NOT certify 2023/24 release-time
PDF bytes, future-outcome OOS, alpha or live buy authorization.
"""
from __future__ import annotations

import re
from decimal import Decimal
from pathlib import Path

FIELDS=("revenue_yuan","parent_net_profit_yuan",
        "revenue_growth_yoy_pct","weighted_roe_pct")

def compact(s):
    return re.sub(r"[\s\u3000]","",str(s or "")).replace("（","(").replace("）",")")

def number(s):
    text=(compact(s).replace(",","").replace("，","").replace("%","")
          .replace("－","-").replace("−","-").replace("﹣","-"))
    if not re.fullmatch(r"-?\d+(?:\.\d+)?",text):
        return None
    return Decimal(text)

def row_label(rows,index,col):
    parts=[]
    for j in range(index,min(len(rows),index+5)):
        row=rows[j]
        # A next row with a current-year numeric value is a new table row,
        # even if PDF's Chinese field labels are split over multiple lines.
        if j>index and number(row[col]) is not None:
            break
        parts.extend(str(x) for x in row[:col] if x not in (None,""))
    return compact("".join(parts))

def classify(label):
    fields=[]
    if ("营业收入" in label and not any(t in label for t in (
        "扣除","比重","占营业收入","百分比","研发","不具备商业实质","其他业务"))):
        fields.append("revenue_yuan")
    if (any(t in label for t in (
        "归属于上市公司股东的净利润",
        "归属于母公司股东的净利润",
        "归属于母公司所有者的净利润"))
        and not any(t in label for t in ("扣除","每股","扣非"))):
        fields.append("parent_net_profit_yuan")
    if "加权平均净资产收益率" in label and not any(
        t in label for t in ("扣除","净损益")):
        fields.append("weighted_roe_pct")
    return fields

def currency_unit(before,actual_label):
    if "(元)" in actual_label or "（元）" in actual_label:
        return "yuan"
    if "(万元)" in actual_label or "（万元）" in actual_label:
        return "ten_thousand_yuan"
    if "(千元)" in actual_label or "（千元）" in actual_label:
        return "thousand_yuan"
    units=list(re.finditer(
        r"(?:单位|金额单位)\s*[:：]\s*(?:人民币)?\s*(元|万元|千元)",
        before))
    if units:
        return {"元":"yuan","万元":"ten_thousand_yuan",
                "千元":"thousand_yuan"}[units[-1].group(1)]
    return "UNRESOLVED_MONEY_UNIT"

def parse_original_table(doc,fiscal_year,maxpages=55):
    """Pure against open PyMuPDF document; caller controls binary source."""
    count=min(maxpages,len(doc))
    text=[doc[i].get_text("text") or "" for i in range(count)]
    section=[i for i,t in enumerate(text)
             if ("主要会计数据和财务指标" in compact(t)
                 or "近三年主要会计数据" in compact(t))]
    if not section:
        return {"status":"ACCOUNTING_TABLE_SECTION_NOT_LOCATED",
                "fiscal_year":fiscal_year,
                "fields":{x:{"status":"NO_CURRENT_YEAR_CELL","candidates":[]}
                          for x in FIELDS}}
    first=section[0]
    found=[]
    carry=None
    import pymupdf
    for page_index in range(first,min(first+4,count)):
        page=doc[page_index]
        for table in page.find_tables().tables:
            rows=table.extract()
            if not rows or len(rows)<2:
                continue
            headers=[]
            for ri,row in enumerate(rows[:5]):
                for col,cell in enumerate(row):
                    if re.fullmatch(rf"{fiscal_year}(?:年|年度)?",compact(cell)):
                        headers.append((ri,col))
            if headers:
                header_index,column=headers[0]
                origin="EXPLICIT_CURRENT_FISCAL_YEAR_TABLE_HEADER"
                carry=(column,table.col_count,page_index)
            elif (carry and carry[2]==page_index-1 and
                  carry[1]==table.col_count and table.bbox[1]<240):
                column=carry[0]
                header_index=-1
                origin="CONTINUED_LAST_PAGES_CURRENT_YEAR_TABLE_COLUMN"
            else:
                continue
            # A quarterly table can share names/columns. Never carry the
            # annual current-year header into quarterly financial figures.
            before=page.get_text("text",clip=pymupdf.Rect(
                0,0,page.rect.width,table.bbox[1])) or ""
            if ("分季度主要财务数据" in compact(before)
                    or "分季度主要会计数据" in compact(before)
                    or "年度分季度主要财务数据" in compact(before)):
                continue
            for row_index,row in enumerate(rows):
                if row_index<=header_index or column>=len(row):
                    continue
                current=number(row[column])
                if current is None:
                    continue
                label=row_label(rows,row_index,column)
                for field in classify(label):
                    unit=("percentage_points" if field=="weighted_roe_pct"
                          else currency_unit(before,label))
                    multiplier={"yuan":Decimal(1),
                                "thousand_yuan":Decimal(1000),
                                "ten_thousand_yuan":Decimal(10000),
                                "percentage_points":Decimal(1)}.get(unit)
                    evidence={
                        "financial_field":field,
                        "source_pdf_page_1based":page_index+1,
                        "fiscal_year_column_header":str(fiscal_year)+"年",
                        "current_year_table_column_index":column,
                        "current_year_row_index":row_index,
                        "field_label":label[:150],
                        "table_cell_original_text":str(row[column])[:140],
                        "table_cell_numeric":str(current),
                        "unit_evidence":unit,
                        "year_mapping_evidence":origin,
                        "table_bbox": [round(x,2) for x in table.bbox],
                        "source_table_cell_not_pit_release_hash":True,
                        "third_party_vendor_value_NOT_used_for_extraction":True,
                    }
                    if multiplier is None:
                        evidence["status"]="MONEY_UNIT_UNVERIFIED"
                    else:
                        evidence["status"]="CURRENT_FISCAL_YEAR_CELL_EXTRACTED"
                        evidence["normalized_value"]=str(current*multiplier)
                    found.append(evidence)
                    if field=="revenue_yuan":
                        # The annual revenue YoY figure is usually the first
                        # percentage cell after the preceding-year revenue.
                        # Require literal % OR a growth-labeled table header.
                        for j,cell in enumerate(row[column+1:],column+1):
                            growth=number(cell)
                            if growth is None or not -1000<growth<1000:
                                continue
                            if j<=column+1:
                                continue
                            current_header=compact(" ".join(
                                str(r[j]) for r in rows[:max(header_index+1,1)]
                                if j<len(r) and r[j] is not None))
                            if "%" not in str(cell) and not (
                                    "增减" in current_header and
                                    ("%" in current_header or "％" in current_header)):
                                continue
                            found.append({
                                **evidence,
                                "financial_field":"revenue_growth_yoy_pct",
                                "current_year_table_column_index":j,
                                "table_cell_original_text":str(cell)[:140],
                                "table_cell_numeric":str(growth),
                                "normalized_value":str(growth),
                                "unit_evidence":"percentage_points",
                                "status":"ANNUAL_REVENUE_YOY_COLUMN_EXTRACTED",
                            })
                            break
    resolved={}
    for field in FIELDS:
        candidates=[x for x in found if x["financial_field"]==field]
        values={x.get("normalized_value") for x in candidates
                if x["status"] in ("CURRENT_FISCAL_YEAR_CELL_EXTRACTED",
                                    "ANNUAL_REVENUE_YOY_COLUMN_EXTRACTED")}
        if len(values)==1 and all("normalized_value" in x for x in candidates):
            status="UNIQUE_FISCAL_YEAR_TABLE_CELL_EXTRACTED"
            amount=next(iter(values))
        elif len(values)>1:
            status="COMPETING_ORIGINAL_TABLE_VALUES"
            amount=None
        elif candidates:
            status="MISSING_UNIT_OR_COLUMN_CERTIFICATION"
            amount=None
        else:
            status="NO_CURRENT_YEAR_CELL"
            amount=None
        resolved[field]={
            "status":status,
            "extracted_value":amount,
            "evidence":candidates[:8],
            "candidate_count":len(candidates),
            "automatically_certified_as_original_release_time_vintage":False,
        }
    return {
        "status":"ORIGINAL_YEAR_ACCOUNTING_TABLE_SCAN_COMPLETE",
        "fiscal_year":fiscal_year,
        "original_full_pdf_pages":len(doc),
        "annual_financial_table_section_pdf_page_1based":first+1,
        "other_quarterly_tables_not_treated_as_annual":True,
        "fields":resolved,
    }
