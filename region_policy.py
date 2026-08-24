"""Shared region/source policy for the portable Job Tracker and MCP layer.

This module owns only cross-cutting tracker-region facts. Source-specific crawl
implementation details (for example LinkedIn geo IDs) remain with source code.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

SourceName = Literal["linkedin", "jora", "jobstreet"]
PublicRegion = Literal["SG", "TW", "China"]


@dataclass(frozen=True, slots=True)
class RegionPolicy:
    key: PublicRegion
    location: str
    supported_sources: frozenset[SourceName]


REGION_POLICIES: dict[PublicRegion, RegionPolicy] = {
    "SG": RegionPolicy(
        key="SG",
        location="Singapore",
        supported_sources=frozenset({"linkedin", "jora", "jobstreet"}),
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
}

DEFAULT_REGIONS: tuple[PublicRegion, ...] = tuple(REGION_POLICIES)

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
}

REGION_LOCATIONS: dict[PublicRegion, str] = {key: policy.location for key, policy in REGION_POLICIES.items()}

SOURCE_LABELS: dict[SourceName, str] = {
    "linkedin": "LinkedIn / jobs-scraper",
    "jora": "Jora / jobs-scraper",
    "jobstreet": "JobStreet / jobs-scraper",
}


def source_region_supported(source: str, region: str) -> tuple[bool, str | None]:
    """Preserve the v1.1 public source/region capability contract."""
    if source in {"jora", "jobstreet"} and region != "SG":
        return False, f"{source} is currently Singapore-only in v1.1.0; use source='linkedin' for region={region}"
    return True, None


def location_for(region: PublicRegion) -> str:
    return REGION_POLICIES[region].location


def source_label(source: SourceName) -> str:
    return SOURCE_LABELS[source]
