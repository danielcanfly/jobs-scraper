"""
Unit tests for sg_product_jobs helpers.

執行: python test_helpers.py
不需要任何網路或 credentials, 純邏輯測試
"""
import sys
from pathlib import Path

# 把同目錄的 sg_product_jobs 加進 import path
sys.path.insert(0, str(Path(__file__).parent))
import sg_product_jobs as M


def test_build_e_formula_linkedin():
    e = M.build_e_formula("linkedin", "4430572342", "")
    assert e == '=HYPERLINK("https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/4430572342","https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/4430572342")', f"got: {e}"


def test_build_e_formula_jora():
    e = M.build_e_formula("jora", "abc123def456", "https://sg.jora.com/job/Product-Manager-abc123def456")
    assert "sg.jora.com/job/Product-Manager-abc123def456" in e
    assert e.startswith('=HYPERLINK(')


def test_build_e_formula_jora_no_url():
    """沒給 url 時 fallback 到 JORA_BASE"""
    e = M.build_e_formula("jora", "abc123def456", "")
    assert f"{M.JORA_BASE}/job/Product-Manager-abc123def456" in e


def test_build_e_formula_jobstreet():
    """2026-08-23 改: 純 id 格式, 沒 slug"""
    e = M.build_e_formula("jobstreet", "94145676", "")
    assert e == '=HYPERLINK("https://sg.jobstreet.com/job/94145676","https://sg.jobstreet.com/job/94145676")'


def test_build_e_formula_unknown_source():
    """未知 source fallback 到 linkedin 格式 (跟原本行為一致)"""
    e = M.build_e_formula("unknown", "12345", "")
    assert "linkedin.com/jobs-guest/jobs/api/jobPosting/12345" in e


def test_parse_sheet_row_linkedin_short_id():
    """LinkedIn sheet row 可能是純 digit (短 id display)"""
    row = ["New", "", "2026-08-22", "LinkedIn / Minimax", "4430572342", "OKX", "VP", "JD", "SG", "Onsite", ""]
    assert M.parse_sheet_row_to_key(row) == ("linkedin", "4430572342")


def test_parse_sheet_row_linkedin_api_url():
    """LinkedIn sheet row 可能是完整 API URL"""
    row = ["New", "", "2026-08-22", "LinkedIn / Minimax",
           "https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/4430572342",
           "OKX", "VP", "JD", "SG", "Onsite", ""]
    assert M.parse_sheet_row_to_key(row) == ("linkedin", "4430572342")


def test_parse_sheet_row_jora():
    """Jora sheet row: 32-char hex hash 在 URL 尾"""
    row = ["New", "", "2026-08-22", "Jora / Minimax",
           "https://sg.jora.com/job/Product-Manager-3edbbb646574ed2a0a926fee537b0e7c?abstrac",
           "Jora Co", "PM", "JD", "SG", "Onsite", ""]
    assert M.parse_sheet_row_to_key(row) == ("jora", "3edbbb646574ed2a0a926fee537b0e7c")


def test_parse_sheet_row_jora_with_query():
    """Jora URL 帶 query string"""
    row = ["New", "", "2026-08-22", "Jora / Minimax",
           "https://sg.jora.com/job/Foo-3edbbb646574ed2a0a926fee537b0e7c?tracking=abc&x=1",
           "Jora", "PM", "JD", "SG", "Onsite", ""]
    assert M.parse_sheet_row_to_key(row) == ("jora", "3edbbb646574ed2a0a926fee537b0e7c")


def test_parse_sheet_row_jobstreet():
    """JobStreet sheet row: /job/{digit} 純 id"""
    row = ["New", "", "2026-08-22", "JobStreet / Minimax",
           "https://sg.jobstreet.com/job/94145676",
           "Tech Data", "PM", "JD", "SG", "Onsite", ""]
    assert M.parse_sheet_row_to_key(row) == ("jobstreet", "94145676")


def test_parse_sheet_row_header():
    """Header row 沒 E 欄資料, 應該回 None"""
    row = ["Status", "Priority", "Date", "Source", "URL", "Co", "Title", "JD", "Loc", "WM", "Visa"]
    assert M.parse_sheet_row_to_key(row) is None


def test_parse_sheet_row_empty():
    """完全空 row 應該回 None"""
    row = ["", "", "", "", "", "", "", "", "", "", ""]
    assert M.parse_sheet_row_to_key(row) is None


def test_parse_sheet_row_too_short():
    """row 太短 (< 5 欄) 應該回 None"""
    row = ["A", "B", "C", "D"]
    assert M.parse_sheet_row_to_key(row) is None


# ─────────────────────────────────────────────────────────────
# _load_sheet_keys 測試
# ─────────────────────────────────────────────────────────────
def test_load_sheet_keys_normal():
    """既有 rows + 找下一個空白 row"""
    existing = [
        ["Status", "Priority", "Date", "Source", "URL", "Co", "Title", "JD", "Loc", "WM", "Visa"],  # header
        ["New", "", "2026-08-22", "JobStreet / Minimax", "https://sg.jobstreet.com/job/94145676", "Tech", "PM", "JD", "SG", "Onsite", ""],
        ["New", "", "2026-08-22", "LinkedIn / Minimax", "4430572342", "OKX", "VP", "JD", "SG", "Onsite", ""],
    ]
    keys, next_row = M._load_sheet_keys(existing)
    assert keys == {("jobstreet", "94145676"), ("linkedin", "4430572342")}
    assert next_row == 4  # row 4 開始是空白


def test_load_sheet_keys_with_gap():
    """有空白 row 在中間, next_row 應該填那個 gap"""
    existing = [
        ["header"],
        ["data1", "x"],
        ["", "", "", "", "", "", "", "", "", "", ""],  # row 3 空
        ["data3", "x"],
    ]
    keys, next_row = M._load_sheet_keys(existing)
    assert next_row == 3  # 找到中間的 gap


def test_load_sheet_keys_empty():
    """只有 header, next_row 應該是 2"""
    existing = [["Status", "Date", "Source", "URL"]]
    keys, next_row = M._load_sheet_keys(existing)
    assert keys == set()
    assert next_row == 2


# ─────────────────────────────────────────────────────────────
# _build_sheet_row 測試
# ─────────────────────────────────────────────────────────────
def test_build_sheet_row_normal():
    """正常 job → 回傳 11 欄 row"""
    job = {
        "job_id": "94145676",
        "title": "Product Manager",
        "company": "Tech Co",
        "location": "Singapore",
        "source": "jobstreet",
        "jd_text": "Sample JD with location info",
        "jd_hash": "abc123",
        "url": "https://sg.jobstreet.com/job/94145676",
    }
    existing_keys = set()
    row = M._build_sheet_row(job, "JobStreet / Minimax", "Singapore", existing_keys)
    assert row is not None
    assert len(row) == 11
    assert row[0] == "New"  # A
    assert row[1] == ""  # B
    assert row[3] == "JobStreet / Minimax"  # D
    assert "94145676" in row[4]  # E (formula)
    assert row[5] == "Tech Co"  # F
    assert row[6] == "Product Manager"  # G
    assert row[7] == "Sample JD with location info"  # H
    assert row[8] == "Singapore"  # I
    # row[9] = work_mode (從 JD regex 推) 可能是空字串或 "Onsite" 看 regex match
    assert row[10] == "" or "HARD" in row[10] or "PR" in row[10] or "citizen" in row[10]  # K (visa)


def test_build_sheet_row_dedup_skip():
    """job_id 已在 existing_keys 裡 → 回 None"""
    job = {"job_id": "94145676", "source": "jobstreet", "jd_text": "JD"}
    existing_keys = {("jobstreet", "94145676")}
    assert M._build_sheet_row(job, "JobStreet / Minimax", "Singapore", existing_keys) is None


def test_build_sheet_row_no_jd_skip():
    """沒 jd_text → 回 None (即使不在 dedup 內)"""
    job = {"job_id": "94145676", "source": "jobstreet", "jd_text": ""}
    existing_keys = set()
    assert M._build_sheet_row(job, "JobStreet / Minimax", "Singapore", existing_keys) is None


def test_build_sheet_row_no_job_id_skip():
    """沒 job_id → 回 None"""
    job = {"title": "X", "source": "jobstreet", "jd_text": "JD"}
    existing_keys = set()
    assert M._build_sheet_row(job, "JobStreet / Minimax", "Singapore", existing_keys) is None


def test_build_sheet_row_visa_only_sg():
    """非 SG location → K 欄 visa 留空 (不跑 detect_visa_signal)"""
    job = {"job_id": "1", "source": "linkedin", "jd_text": "Must be PR", "title": "PM"}
    row = M._build_sheet_row(job, "LinkedIn / Minimax", "Taiwan", set())
    assert row[10] == ""  # K = "" (因為 location 是 Taiwan)


# ─────────────────────────────────────────────────────────────
# extract_work_mode 測試
# ─────────────────────────────────────────────────────────────
def test_work_mode_onsite_title():
    """Title 開頭 'Onsite - ...' 應該回 Onsite (沒 hyphen)"""
    assert M.extract_work_mode("", "Onsite - Product Manager") == "Onsite"


def test_work_mode_onsite_title_with_hyphen():
    """Title 開頭 'On-site - ...' 應該也回 Onsite"""
    assert M.extract_work_mode("", "On-site - Product Manager") == "Onsite"


def test_work_mode_hybrid_jd():
    """JD 開頭 'Location: Singapore (hybrid)' 應該回 Hybrid"""
    jd = "Location: Singapore (hybrid) work model"
    assert M.extract_work_mode(jd, "") == "Hybrid"


def test_work_mode_remote_jd():
    """JD 開頭 'on a remote basis' 應該回 Remote"""
    jd = "Office location. on a remote basis, full time role"
    assert M.extract_work_mode(jd, "") == "Remote"


def test_work_mode_onsite_jd():
    """JD 開頭 'WORK OPTION: In Office' 應該回 Onsite"""
    jd = "WORK OPTION: In Office. About the role..."
    assert M.extract_work_mode(jd, "") == "Onsite"


def test_work_mode_empty():
    """沒 match 應該回空字串"""
    assert M.extract_work_mode("random text without any mode", "Title") == ""


# ─────────────────────────────────────────────────────────────
# 跑所有測試
# ─────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import inspect
    tests = [(name, fn) for name, fn in globals().items() if name.startswith("test_") and callable(fn)]
    n_pass = 0
    n_fail = 0
    for name, fn in tests:
        try:
            fn()
            print(f"  ✅ {name}")
            n_pass += 1
        except AssertionError as e:
            print(f"  ❌ {name}: {e}")
            n_fail += 1
        except Exception as e:
            print(f"  💥 {name}: {type(e).__name__}: {e}")
            n_fail += 1
    print(f"\n{'='*60}")
    print(f"  {n_pass}/{len(tests)} 通過, {n_fail} 失敗")
    sys.exit(0 if n_fail == 0 else 1)
