"""Pure Job Tracker schema, region, and header contract helpers."""
from __future__ import annotations

import re
from typing import Iterable

import region_policy as RP

SCHEMA_VERSION = "job-tracker-v1"
DEFAULT_ROWS = 1000
SCHEMA_COLUMNS = 27

HEADERS = (
    "Status｜狀態",
    "Priority｜優先級",
    "加入日期｜Added At",
    "Source｜來源",
    "Job URL｜職缺連結",
    "Company｜公司",
    "Job Title｜職稱",
    "JD | 描述",
    "Location｜地點",
    "Work Mode｜工作型態",
    "Visa / Constraint｜簽證限制",
    "Domain｜產品產業",
    "CV Version｜履歷版本",
    "Total /100",
    "Verdict｜評語",
    "Decision｜決策",
    "Application Strategy｜投遞策略",
    "Role Fit /25",
    "CV Proof /15",
    "AI / Tech Leverage /15",
    "Seniority Scope /10",
    "Company Quality /10",
    "Domain Advantage /10",
    "Application ROI /10",
    "Practical Constraints /5",
    "Positioning / Selling Points｜定位賣點",
    "Risks / Next Action｜風險下一步",
)

HEADER_NOTES = (
    "工作流狀態：New / Scored / Applied / Interviewing / Pending。",
    "投遞優先級：P0 / P1 / P2 / Low。用來排序實際處理順序，不只看總分。",
    "職缺加入或最近完成評分的日期。",
    "例如 LinkedIn、Jora、JobStreet、referral、company site。",
    "原始職缺 URL 或 jobs-scraper 產生的安全 HYPERLINK。",
    "公司名稱。",
    "職缺標題。",
    "完整職缺描述（JD）。",
    "職缺地點，例如 Singapore、Taipei、Shanghai、Remote。",
    "Remote / Hybrid / Onsite / Unknown。",
    "Work authorization、sponsorship、timezone、language、salary 等現實限制。",
    "AI SaaS、B2B SaaS、Marketplace、Travel-tech、Hospitality、Growth、Ads、Data Product 等。",
    "這份職缺應使用的履歷包裝版本。",
    "總分，滿分 100。",
    "整體投遞評語。",
    "Apply / Maybe / Skip。",
    "Do not apply / Quick apply only / Apply with tailored CV / Tailored CV + recruiter message / Tailored CV + hiring manager outreach。",
    "職務方向匹配度，滿分 25。",
    "履歷證據匹配度，滿分 15。",
    "AI 與技術槓桿，滿分 15。",
    "職級與職責範圍，滿分 10。",
    "公司品質與時機，滿分 10。",
    "Market / Domain Advantage，滿分 10。",
    "投遞報酬率，滿分 10。",
    "現實限制，滿分 5。",
    "一句定位角度 + 最該主打的 3 個候選人賣點。可直接用於 CV summary 或 recruiter message。",
    "主要弱點、公司/簽證/JD 風險、面試補強、下一步行動，例如找 HM、改 CV、補公司研究。",
)

VALIDATIONS: dict[int, tuple[str, ...]] = {
    0: ("New", "Scored", "Applied", "Interviewing", "Pending"),
    1: ("P0", "P1", "P2", "Low"),
    9: ("Remote", "Hybrid", "Onsite", "Unknown"),
    12: (
        "AI PM", "Growth PM", "Travel / Hospitality", "Founder / 0→1",
        "Strategy Ops", "Platform / Workflow", "General PM", "Web3 / Fintech",
    ),
    14: ("強烈值得投", "值得投", "邊緣", "不太建議", "不值得投"),
    15: ("Apply", "Maybe", "Skip"),
    16: (
        "Do not apply", "Quick apply only", "Apply with tailored CV",
        "Tailored CV + recruiter message", "Tailored CV + hiring manager outreach",
    ),
}

REGION_ALIASES = RP.REGION_ALIASES
DEFAULT_REGIONS = RP.DEFAULT_REGIONS
DEFAULT_SHEET_TITLES = {"sheet1", "工作表1", "工作表 1"}

COLUMN_WIDTHS = (
    111, 111,
    124, 124, 124,
    172, 172, 172,
    137, 137, 137, 137, 137,
    133, 133, 133, 133,
    109, 109, 109, 109, 109, 109, 109, 109,
    286, 286,
)
HEADER_HEIGHT_PX = 52

HEADER_RGB = {"red": 0.101960786, "green": 0.21568628, "blue": 0.33333334}
WHITE_RGB = {"red": 1.0, "green": 1.0, "blue": 1.0}

STATUS_COLORS = {
    "Pending": {"red": 1.0, "green": 1.0, "blue": 1.0},
    "Interviewing": {"red": 0.96862745, "green": 0.92941177, "blue": 0.64705884},
    "Applied": {"red": 0.95686275, "green": 0.7764706, "blue": 0.7764706},
    "Scored": {"red": 0.7764706, "green": 0.8980392, "blue": 0.9490196},
    "New": {"red": 0.81960785, "green": 0.9490196, "blue": 0.7764706},
}
PRIORITY_COLORS = {
    "P0": {"red": 0.9490196, "green": 0.6, "blue": 0.6},
    "P1": {"red": 0.96862745, "green": 0.7764706, "blue": 0.49803922},
}


class TrackerError(RuntimeError):
    def __init__(self, error_code: str, message: str):
        super().__init__(message)
        self.error_code = error_code
        self.message = message


def canonical_region(region: str) -> str:
    raw = (region or "").strip()
    if not raw:
        raise TrackerError("INVALID_REGION", "region must be non-empty")
    alias = REGION_ALIASES.get(raw.casefold())
    if alias:
        return alias
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9 _-]{0,31}", raw):
        raise TrackerError(
            "INVALID_REGION",
            "region may contain only letters, digits, spaces, '_' or '-' and must be <= 32 chars",
        )
    return raw


def canonical_regions(regions: Iterable[str] | None) -> list[str]:
    values = list(regions or DEFAULT_REGIONS)
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        region = canonical_region(value)
        key = region.casefold()
        if key not in seen:
            seen.add(key)
            out.append(region)
    if not out:
        raise TrackerError("INVALID_REGION", "at least one region is required")
    return out


def raw_tab(region: str) -> str:
    return f"{canonical_region(region)}-Raw"


def selected_tab(region: str) -> str:
    return f"{canonical_region(region)}-Selected"


def expected_tabs(regions: Iterable[str] | None = None) -> list[str]:
    tabs: list[str] = []
    for region in canonical_regions(regions):
        tabs.extend([raw_tab(region), selected_tab(region)])
    return tabs
