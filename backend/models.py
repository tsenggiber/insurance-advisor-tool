from pydantic import BaseModel
from typing import Optional, List


class ClientData(BaseModel):
    name: str
    birth_date: Optional[str] = None   # YYYY-MM-DD，與 insurance_age 二擇一
    insurance_age: Optional[int] = None # 直接輸入保險年齡
    gender: str      # male / female
    occupation_class: int  # 1-6
    monthly_income: float


class Policy(BaseModel):
    company: str
    insurance_type: str
    product_name: str
    coverage_amount: float
    annual_premium: float
    premium_type: str       # 自然保費 / 平準保費
    coverage_end_age: int
    policy_date: Optional[str] = None   # 民國格式，如 110/05/01
    is_lifetime: bool = False            # 終身型保障
    occupation_class: Optional[int] = None  # 職業類別 1-6（傷害/意外險）
    # 細部保障金額（掃描時自動填入，無法辨識填 0）
    disease_hosp_daily: float = 0       # 疾病住院日額
    accident_hosp_daily: float = 0      # 意外住院日額
    inpatient_surgery: float = 0        # 住院手術（每次）
    outpatient_surgery: float = 0       # 門診手術（每次）
    specific_treatment: float = 0       # 特定處置（每次）
    medical_reimburse: float = 0        # 醫療實支實付上限
    accident_reimburse: float = 0       # 意外實支實付上限
    deductible: float = 0               # 實支自負額
    disability_monthly: float = 0       # 失能月給付
    long_care_monthly: float = 0        # 長照月給付
    critical_illness: float = 0         # 重大疾病/特定傷病一次金
    cancer_first: float = 0             # 初次罹癌一次金
    cancer_hosp_daily: float = 0        # 癌症住院日額
    cancer_surgery: float = 0           # 癌症手術（每次）
    accident_death: float = 0           # 意外身故保額
    fracture: float = 0                 # 骨折保險金


class AdvisorInfo(BaseModel):
    name: str
    company: str
    unit: str
    phone: str
    line_id: str
    photo_base64: Optional[str] = None


class PremiumDataPoint(BaseModel):
    age: int
    natural_premium: float
    level_premium: float


class GapItem(BaseModel):
    category: str
    status: str          # 足夠 / 偏低 / 嚴重不足
    current_amount: float
    recommended_amount: float
    description: str


class Recommendation(BaseModel):
    priority: int
    category: str
    recommended_amount: float
    description: str


class CoverageSummary(BaseModel):
    life_total: float = 0
    medical_daily: float = 0
    cancer_lump_sum: float = 0
    disability_monthly: float = 0
    long_care_planned: bool = False
    accident_total: float = 0
    total_annual_premium: float = 0


class AnalysisResult(BaseModel):
    coverage_summary: CoverageSummary
    premium_trend: List[PremiumDataPoint]
    gap_analysis: List[GapItem]
    recommendations: List[Recommendation]


class AnalysisRequest(BaseModel):
    client: ClientData
    policies: List[Policy]
    advisor: AdvisorInfo


class PptxRequest(BaseModel):
    client: ClientData
    policies: List[Policy]
    advisor: AdvisorInfo
    analysis: AnalysisResult


class LoginRequest(BaseModel):
    username: str
    password: str
    device_token: Optional[str] = None


class SetExpiry(BaseModel):
    expires_at: Optional[str] = None  # YYYY-MM-DD 或 None（永不到期）


class UserCreate(BaseModel):
    username: str
    password: str
    display_name: str
    is_admin: bool = False


class ExtractRequest(BaseModel):
    image_base64: str


class ProductCreate(BaseModel):
    company: str
    product_name: str
    insurance_type: str
    premium_type: str
    coverage_end_age: int = 75


class RateTableRequest(BaseModel):
    company: str
    product_name: str
    gender: str           # male / female
    occupation_class: int | None = None  # 1-6，傷害險必填
