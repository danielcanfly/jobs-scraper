"""v1.6.4: 中國城市 region (杭州 / 深圳) + 移除中國專屬簽證判斷。

兩件事綁在一起驗, 因為它們共用同一個 region 觀念:
  1. 中國不再只爬上海 — Hangzhou / Shenzhen 各自是可選的 region, 共用 China 的 sheet tab。
  2. 中國職缺不做簽證判斷 (台灣人可拿通行證入職), 但 SG / TW 的判斷不能因此變弱。
"""

from __future__ import annotations

import job_tracker as JT
import region_policy as RP
import sg_product_jobs as M
from jobs_scraper.sources import linkedin as L


# ─────────────────────────────────────────────────────────────
# 1. geoId: 城市 preset
# ─────────────────────────────────────────────────────────────
def test_china_cities_have_verified_geo_ids():
    """geoId 取自 LinkedIn GEO typeahead, 且已實抓驗證過回傳地點。"""
    assert L.KNOWN_GEO_IDS["Hangzhou"] == ("101821877", "Hangzhou")
    assert L.KNOWN_GEO_IDS["Shenzhen"] == ("106750182", "Shenzhen")
    assert L.KNOWN_GEO_IDS["Shanghai"] == ("107388191", "Shanghai")


def test_city_geo_ids_are_distinct():
    """三個中國城市的 geoId 不能撞, 否則 --location 會爬到同一個城市。"""
    ids = [L.KNOWN_GEO_IDS[name][0] for name in ("Shanghai", "Hangzhou", "Shenzhen")]
    assert len(set(ids)) == 3


def test_cli_location_preset_resolves_city_geo_ids():
    """--location Hangzhou / Shenzhen 會帶到正確的 geoId 進 list URL。"""
    for city, geo_id in (("Hangzhou", "101821877"), ("Shenzhen", "106750182")):
        resolved_id, resolved_name = M.KNOWN_GEO_IDS[city]
        assert (resolved_id, resolved_name) == (geo_id, city)
        url = M.build_linkedin_list_url("r2592000", 0, location=resolved_name, geo_id=resolved_id)
        assert f"geoId={geo_id}" in url
        assert f"location={city}" in url


# ─────────────────────────────────────────────────────────────
# 2. region policy: 城市是 region, 共用 China tab
# ─────────────────────────────────────────────────────────────
def test_city_regions_are_explicit_and_opt_in():
    """城市進得了 region 清單, 但不是預設 (預設仍是 SG / TW / China)。"""
    assert RP.DEFAULT_REGIONS == ("SG", "TW", "China")
    assert RP.REGION_POLICIES["Hangzhou"].location == "Hangzhou"
    assert RP.REGION_POLICIES["Shenzhen"].location == "Shenzhen"
    assert RP.REGION_POLICIES["China"].location == "Shanghai"


def test_city_aliases_resolve_to_their_own_region():
    for alias in ("hangzhou", "Hangzhou", "hz", "杭州"):
        assert JT.canonical_region(alias) == "Hangzhou"
    for alias in ("shenzhen", "Shenzhen", "sz", "深圳"):
        assert JT.canonical_region(alias) == "Shenzhen"
    # 既有 alias 不變
    assert JT.canonical_region("cn") == "China"
    assert JT.canonical_region("shanghai") == "China"


def test_city_regions_share_the_china_sheet_tabs():
    """三個中國城市寫進同一張 China-Raw / China-Selected。"""
    assert JT.raw_tab("Hangzhou") == "China-Raw"
    assert JT.selected_tab("Hangzhou") == "China-Selected"
    assert JT.raw_tab("Shenzhen") == "China-Raw"
    assert JT.selected_tab("Shenzhen") == "China-Selected"
    assert JT.raw_tab("China") == "China-Raw"
    # 非中國 region 不受 tab base 影響
    assert JT.raw_tab("SG") == "SG-Raw"
    assert JT.raw_tab("Japan") == "Japan-Raw"


def test_expected_tabs_dedupes_the_shared_china_tab():
    """initialize 時同一個 tab 不能被 addSheet 兩次。"""
    tabs = JT.expected_tabs(["SG", "TW", "China", "Hangzhou", "Shenzhen"])
    assert tabs == ["SG-Raw", "SG-Selected", "TW-Raw", "TW-Selected", "China-Raw", "China-Selected"]
    assert len(tabs) == len(set(tabs))


def test_plan_initialize_does_not_create_china_tab_twice():
    """共用 tab 的 region 一起 initialize 時, create 清單裡 China-Raw 只出現一次。"""
    sh = _FakeSpreadsheet([])
    plan = JT.plan_initialize(sh, ["China", "Hangzhou", "Shenzhen"])
    assert plan["create"] == ["China-Raw", "China-Selected"]


# ─────────────────────────────────────────────────────────────
# 3. 簽證: 中國專屬判斷移除, SG / TW 覆蓋不變
# ─────────────────────────────────────────────────────────────
def test_china_only_visa_phrases_produce_no_signal():
    """中國專屬的簽證字眼不再被判成 blocker。"""
    for text in (
        "僅限中國公民",
        "必須為中國公民",
        "必須為大陸公民",
        "上海戶口優先",
        "中國人優先",
        "大陸人優先",
        "Chinese nationals preferred",
    ):
        assert M.detect_visa_signal(text) == "", text


def test_generic_citizenship_requirements_are_still_flagged():
    """SG / TW 的判斷不能因為移除中國字眼而變弱。"""
    hard_cases = [
        "Applicants must be Singapore citizens only",
        "僅限公民",
        "必須為公民",
        "must be a Chinese citizen",
    ]
    for text in hard_cases:
        signal = M.detect_visa_signal(text)
        assert signal.startswith("⚠️ HARD:"), f"{text!r} → {signal!r}"


def test_taiwan_citizenship_requirements_are_still_flagged():
    for text in ("Taiwan citizens only", "must be a Taiwan citizen", "僅限台灣公民"):
        signal = M.detect_visa_signal(text)
        assert signal.startswith("⚠️ HARD:"), f"{text!r} → {signal!r}"


def test_china_rows_never_get_a_visa_signal():
    """非 SG 的 row 不跑簽證偵測 — 中國職缺的 K 欄留空。"""
    job = {
        "job_id": "cn-1",
        "source": "linkedin",
        "title": "Product Director",
        "location": "Hangzhou, Zhejiang, China",
        "jd_text": "Chinese citizens only",
    }
    row = M._build_sheet_row(job, "LinkedIn / Minimax", "Hangzhou", set())
    assert row is not None
    assert row[10] == ""


# ─────────────────────────────────────────────────────────────
# helpers
# ─────────────────────────────────────────────────────────────
class _FakeWorksheet:
    def __init__(self, title: str):
        self.title = title
        self.id = 1
        self.row_count = 100
        self.col_count = 27

    def _cells(self):
        return [[""]] * 3

    def get_all_values(self):
        return self._cells()


class _FakeSpreadsheet:
    def __init__(self, worksheets):
        self._worksheets = list(worksheets)

    def worksheets(self):
        return self._worksheets
