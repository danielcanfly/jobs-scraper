from __future__ import annotations

import inspect

import job_tracker as JT
import region_policy as RP
import server_v1_1 as S


def test_region_policy_owns_shared_tracker_region_facts():
    assert RP.DEFAULT_REGIONS == ("SG", "TW", "China")
    assert JT.DEFAULT_REGIONS is RP.DEFAULT_REGIONS
    assert JT.REGION_ALIASES is RP.REGION_ALIASES
    assert S.REGION_LOCATIONS is RP.REGION_LOCATIONS
    assert S.SOURCE_LABELS is RP.SOURCE_LABELS


def test_region_locations_preserve_v111_contract():
    assert RP.REGION_LOCATIONS == {
        "SG": "Singapore",
        "TW": "Taiwan",
        "China": "Shanghai",
    }
    assert RP.location_for("SG") == "Singapore"
    assert RP.location_for("TW") == "Taiwan"
    assert RP.location_for("China") == "Shanghai"


def test_source_region_capability_preserves_v111_contract():
    assert RP.source_region_supported("linkedin", "SG") == (True, None)
    assert RP.source_region_supported("linkedin", "TW") == (True, None)
    assert RP.source_region_supported("linkedin", "China") == (True, None)
    assert RP.source_region_supported("jora", "SG") == (True, None)
    assert RP.source_region_supported("jobstreet", "SG") == (True, None)
    assert RP.source_region_supported("jora", "TW") == (
        False,
        "jora is currently Singapore-only in v1.1.0; use source='linkedin' for region=TW",
    )
    assert RP.source_region_supported("jobstreet", "China") == (
        False,
        "jobstreet is currently Singapore-only in v1.1.0; use source='linkedin' for region=China",
    )
    assert S._source_region_supported("jobstreet", "China") == RP.source_region_supported("jobstreet", "China")


def test_source_labels_preserve_v111_contract():
    assert RP.SOURCE_LABELS == {
        "linkedin": "LinkedIn / jobs-scraper",
        "jora": "Jora / jobs-scraper",
        "jobstreet": "JobStreet / jobs-scraper",
    }
    for source, label in RP.SOURCE_LABELS.items():
        assert RP.source_label(source) == label


def test_tracker_custom_region_passthrough_is_not_narrowed():
    assert JT.canonical_region("Japan") == "Japan"
    assert JT.raw_tab("Japan") == "Japan-Raw"
    assert JT.selected_tab("Japan") == "Japan-Selected"


def test_region_policy_not_duplicated_in_v11_server():
    source = inspect.getsource(S)
    assert "REGION_LOCATIONS: dict[str, str] = {" not in source
    assert "SOURCE_LABELS: dict[str, str] = {" not in source
    assert "Region = RP.PublicRegion" in source
    assert "return RP.source_region_supported(source, region)" in source
