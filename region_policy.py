"""Shared region/source policy for the portable Job Tracker and MCP layer.

This module owns only cross-cutting tracker-region facts. Source-specific crawl
implementation details (for example LinkedIn geo IDs) remain with source code.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

SourceName = Literal["linkedin"]
PublicRegion = Literal["SG", "TW", "China", "Hangzhou", "Shenzhen"]


@dataclass(frozen=True, slots=True)
class RegionPolicy:
    key: PublicRegion
    location: str
    supported_sources: frozenset[SourceName]


REGION_POLICIES: dict[PublicRegion, RegionPolicy] = {
    "SG": RegionPolicy(
        key="SG",
        location="Singapore",
        supported_sources=frozenset({"linkedin"}),
    ),
    "TW": RegionPolicy(
        key="TW",
        location="Taiwan",
        supported_sources=frozenset({"linkedin"}),
    ),
    "China": RegionPolicy(
        key="China",
        location="Shanghai",
        supported_sources=frozenset({"linkedin"}),
    ),
    # 2026-11-19: 中國城市各自可選, 但共用 China 的 sheet tab (見 REGION_TAB_BASE)
    "Hangzhou": RegionPolicy(
        key="Hangzhou",
        location="Hangzhou",
        supported_sources=frozenset({"linkedin"}),
    ),
    "Shenzhen": RegionPolicy(
        key="Shenzhen",
        location="Shenzhen",
        supported_sources=frozenset({"linkedin"}),
    ),
}

# 預設 region 不含城市: 中國的城市是 opt-in (要明確指定才爬那個城市)
DEFAULT_REGIONS: tuple[PublicRegion, ...] = ("SG", "TW", "China")

REGION_ALIASES: dict[str, PublicRegion] = {
    "sg": "SG",
    "singapore": "SG",
    "tw": "TW",
    "taiwan": "TW",
    "台灣": "TW",
    "台湾": "TW",
    "cn": "China",
    "china": "China",
    "mainland china": "China",
    "中國": "China",
    "中国": "China",
    "shanghai": "China",
    "hangzhou": "Hangzhou",
    "hz": "Hangzhou",
    "杭州": "Hangzhou",
    "shenzhen": "Shenzhen",
    "sz": "Shenzhen",
    "深圳": "Shenzhen",
}

# 城市 region 共用哪個 sheet tab: <TAB_BASE>-Raw / <TAB_BASE>-Selected
# 中國城市共用 China 的 tab, 所以三個城市寫進同一張 China-Raw
REGION_TAB_BASE: dict[str, PublicRegion] = {
    "Hangzhou": "China",
    "Shenzhen": "China",
}

REGION_LOCATIONS: dict[PublicRegion, str] = {key: policy.location for key, policy in REGION_POLICIES.items()}

SOURCE_LABELS: dict[SourceName, str] = {
    "linkedin": "LinkedIn / jobs-scraper",
}


def source_region_supported(source: str, region: str) -> tuple[bool, str | None]:
    """Fail closed for retired sources while preserving one shared policy gate."""
    if source != "linkedin":
        return False, f"source={source!r} is not supported; supported source: linkedin"
    return True, None


def location_for(region: PublicRegion) -> str:
    return REGION_POLICIES[region].location


def source_label(source: SourceName) -> str:
    return SOURCE_LABELS[source]
