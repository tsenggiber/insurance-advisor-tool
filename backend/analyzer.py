import anthropic
import os
from datetime import date
from models import ClientData, Policy, AnalysisResult

_client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))

ANALYSIS_TOOL = {
    "name": "output_analysis",
    "description": "輸出保障缺口分析結果的結構化資料",
    "input_schema": {
        "type": "object",
        "required": ["coverage_summary", "premium_trend", "gap_analysis", "recommendations"],
        "properties": {
            "coverage_summary": {
                "type": "object",
                "required": ["life_total", "medical_daily", "cancer_lump_sum",
                             "disability_monthly", "long_care_planned", "accident_total", "total_annual_premium"],
                "properties": {
                    "life_total": {"type": "number", "description": "壽險總保額（元）"},
                    "medical_daily": {"type": "number", "description": "醫療住院日額（元）"},
                    "cancer_lump_sum": {"type": "number", "description": "癌症/重大傷病一次金（元）"},
                    "disability_monthly": {"type": "number", "description": "失能月給付（元）"},
                    "long_care_planned": {"type": "boolean", "description": "是否已規劃長照保障"},
                    "accident_total": {"type": "number", "description": "意外險總保額（元）"},
                    "total_annual_premium": {"type": "number", "description": "現有保費年繳合計（元）"}
                }
            },
            "premium_trend": {
                "type": "array",
                "description": "從當前年齡到80歲每5年一個資料點",
                "items": {
                    "type": "object",
                    "required": ["age", "natural_premium", "level_premium"],
                    "properties": {
                        "age": {"type": "integer"},
                        "natural_premium": {"type": "number", "description": "該年齡自然保費估算（元/年）"},
                        "level_premium": {"type": "number", "description": "平準保費固定合計（元/年）"}
                    }
                }
            },
            "gap_analysis": {
                "type": "array",
                "description": "至少包含壽險、醫療險、癌症/重大傷病、失能險、長照險五項",
                "items": {
                    "type": "object",
                    "required": ["category", "status", "current_amount", "recommended_amount", "description"],
                    "properties": {
                        "category": {"type": "string"},
                        "status": {"type": "string", "enum": ["足夠", "偏低", "嚴重不足"]},
                        "current_amount": {"type": "number"},
                        "recommended_amount": {"type": "number"},
                        "description": {"type": "string"}
                    }
                }
            },
            "recommendations": {
                "type": "array",
                "description": "最多5項，按優先順序排列",
                "items": {
                    "type": "object",
                    "required": ["priority", "category", "recommended_amount", "description"],
                    "properties": {
                        "priority": {"type": "integer"},
                        "category": {"type": "string"},
                        "recommended_amount": {"type": "number"},
                        "description": {"type": "string"}
                    }
                }
            }
        }
    }
}


def _calculate_age(birth_date_str: str) -> int:
    birth = date.fromisoformat(birth_date_str)
    today = date.today()
    age = today.year - birth.year - ((today.month, today.day) < (birth.month, birth.day))
    return age


def analyze_coverage(client_data: ClientData, policies: list[Policy], clause_texts: dict[str, str] | None = None) -> AnalysisResult:
    if client_data.birth_date:
        current_age = _calculate_age(client_data.birth_date)
        age_line = f"出生日期：{client_data.birth_date}（保險年齡 {current_age} 歲）"
    elif client_data.insurance_age:
        current_age = client_data.insurance_age
        age_line = f"保險年齡：{current_age} 歲"
    else:
        raise ValueError("需要提供出生日期或保險年齡")

    clause_texts = clause_texts or {}
    clause_parts = []
    for p in policies:
        key = f"{p.company}｜{p.product_name}"
        text = clause_texts.get(key, "")
        if text:
            clause_parts.append(f"【{p.product_name}】\n{text[:2000]}")
    clause_section = "\n\n".join(clause_parts) if clause_parts else "（未找到對應條款）"

    policies_text = "\n".join([
        f"- {p.company}｜{p.insurance_type}｜{p.product_name}｜"
        f"保額 {p.coverage_amount:,.0f} 元｜年繳 {p.annual_premium:,.0f} 元｜"
        f"{p.premium_type}｜保障至 {p.coverage_end_age} 歲"
        for p in policies
    ]) or "（無現有保單）"

    prompt = f"""你是台灣壽險業務員的分析助理。請根據以下客戶資料與現有保單，進行保障缺口分析。

## 客戶資料
- 姓名：{client_data.name}
- {age_line}
- 性別：{"男" if client_data.gender == "male" else "女"}
- 職業類別：第 {client_data.occupation_class} 類
- 月收入：{client_data.monthly_income:,.0f} 元

## 現有保單
{policies_text}

## 缺口分析標準
- 壽險：保額應達月收入 × 120 倍（10年收入）＝ {client_data.monthly_income * 120:,.0f} 元
- 醫療險：住院日額應 ≥ 3,000 元
- 重大傷病/癌症一次金：應 ≥ 100 萬元
- 失能險：月給付應 ≥ 月收入 60%＝ {client_data.monthly_income * 0.6:,.0f} 元
- 長照險：50歲以上應已規劃

## 保單條款原文（供參考，以條款為準）
{clause_section}

## 自然保費趨勢估算說明
- 自然保費（naturalPremium）：彙整所有「自然保費」型態保單，依台灣壽險市場費率，每5年估算年齡增長後的保費增幅（約每10年翻1.5-2倍）
- 平準保費（levelPremium）：彙整所有「平準保費」型態保單的年繳保費，金額固定不變
- 資料從 {current_age} 歲開始到 80 歲，每 5 年一個點

請使用 output_analysis 工具回傳分析結果。""".format(clause_section=clause_section)

    response = _client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=4096,
        tools=[ANALYSIS_TOOL],
        tool_choice={"type": "tool", "name": "output_analysis"},
        messages=[{"role": "user", "content": prompt}]
    )

    tool_use_block = next(
        (b for b in response.content if b.type == "tool_use"),
        None
    )
    if not tool_use_block:
        raise ValueError("Claude 未回傳分析結果")

    data = tool_use_block.input
    usage = {"input_tokens": response.usage.input_tokens, "output_tokens": response.usage.output_tokens}
    return AnalysisResult(**data), usage
