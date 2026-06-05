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
