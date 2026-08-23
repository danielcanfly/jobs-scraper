# v1.1 implementation CI probe

Commit at checkout: 8447a60aaa72dd3f0e6d8713c6adf1e048ade6f6

bootstrap_uv_exit_code: 0

## lock
exit_code: 0
```text
Using CPython 3.11.16 interpreter at: /opt/hostedtoolcache/Python/3.11.16/x64/bin/python3
Resolved 58 packages in 0.65ms
```

## sync
exit_code: 0
```text
 + httpcore2==2.12.0
 + httpx2==2.12.0
 + idna==3.19
 + iniconfig==2.3.0
 + jobs-scraper==1.1.0 (from file:///home/runner/work/jobs-scraper/jobs-scraper)
 + jsonschema==4.26.0
 + jsonschema-specifications==2025.9.1
 + lxml==6.1.2
 + mcp==2.0.0
 + mcp-types==2.0.0
 + oauthlib==3.3.1
 + opentelemetry-api==1.44.0
 + orjson==3.12.0
 + packaging==26.3
 + pluggy==1.6.0
 + pyasn1==0.6.4
 + pyasn1-modules==0.4.2
 + pycparser==3.0
 + pydantic==2.13.4
 + pydantic-core==2.46.4
 + pygments==2.21.0
 + pyjwt==2.13.0
 + pytest==9.1.1
 + python-dotenv==1.2.3
 + python-multipart==0.0.32
 + referencing==0.37.0
 + requests==2.34.2
 + requests-oauthlib==2.0.0
 + rpds-py==2026.6.3
 + scrapling==0.4.14
 + soupsieve==2.9.2
 + sse-starlette==3.4.8
 + starlette==1.6.0
 + tld==0.13.2
 + truststore==0.10.4
 + typing-extensions==4.16.0
 + typing-inspection==0.4.4
 + urllib3==2.7.0
 + uvicorn==0.52.4
 + w3lib==2.4.1
```

## compile
exit_code: 0
```text
```

## helpers
exit_code: 0
```text
  ✅ test_build_e_formula_linkedin
  ✅ test_build_e_formula_jora
  ✅ test_build_e_formula_jora_no_url
  ✅ test_build_e_formula_jobstreet
  ✅ test_build_e_formula_unknown_source
  ✅ test_parse_sheet_row_linkedin_short_id
  ✅ test_parse_sheet_row_linkedin_api_url
  ✅ test_parse_sheet_row_jora
  ✅ test_parse_sheet_row_jora_with_query
  ✅ test_parse_sheet_row_jobstreet
  ✅ test_parse_sheet_row_header
  ✅ test_parse_sheet_row_empty
  ✅ test_parse_sheet_row_too_short
  ✅ test_load_sheet_keys_normal
  ✅ test_load_sheet_keys_with_gap
  ✅ test_load_sheet_keys_empty
  ✅ test_build_sheet_row_normal
  ✅ test_build_sheet_row_dedup_skip
  ✅ test_build_sheet_row_no_jd_skip
  ✅ test_build_sheet_row_no_job_id_skip
  ✅ test_build_sheet_row_visa_only_sg
  ✅ test_work_mode_onsite_title
  ✅ test_work_mode_onsite_title_with_hyphen
  ✅ test_work_mode_hybrid_jd
  ✅ test_work_mode_remote_jd
  ✅ test_work_mode_onsite_jd
  ✅ test_work_mode_empty

============================================================
  27/27 通過, 0 失敗
```

## pytest
exit_code: 0
```text
........................................................................ [ 64%]
........................................                                 [100%]
```

## doctor
exit_code: 0
```text
🩺 jobs-scraper v1.1 doctor
============================================================
  ✅ Python: 3.11 (need >= 3.11)
  ✅ venv interpreter: /home/runner/work/jobs-scraper/jobs-scraper/.venv/bin/python (exists)
  ✅ imports: OK
  ✅ file: sg_product_jobs.py: exists
  ✅ file: server.py (legacy v1.0 entrypoint): exists
  ✅ file: server_v1_1.py: exists
  ✅ file: job_tracker.py: exists
  ✅ file: pyproject.toml: exists
  ✅ file: LICENSE: exists
  ✅ file: .gitignore: exists
  ✅ file: skills/jobs-scraper/SKILL.md: exists
  ✅ file: skills/jobs-scraper/references/JOB_TRACKER_SCHEMA.md: exists
  ✅ file: .codex-plugin/plugin.json: exists
  ⚠️  sheet config: v1.1 未設定: GSPREAD_SA_KEY_PATH, SHEET_ID — crawl_jobs 仍可用；Sheet tools 會 fail closed。SHEET_GID 不需設定
  ✅ git hygiene: OK (no secrets tracked)
============================================================
⚠️  doctor: warnings only (public-source crawl works; Sheet tools need user-owned Sheet config)
```

## skills_install
exit_code: 0
```text
   Updating https://github.com/agentskills/agentskills.git (69ef37e9424c0a7ea9dd2293b559e43ec8176379)
    Updated https://github.com/agentskills/agentskills.git (69ef37e9424c0a7ea9dd2293b559e43ec8176379)
Resolved 5 packages in 471ms
   Building skills-ref @ git+https://github.com/agentskills/agentskills.git@69ef37e9424c0a7ea9dd2293b559e43ec8176379#subdirectory=skills-ref
      Built skills-ref @ git+https://github.com/agentskills/agentskills.git@69ef37e9424c0a7ea9dd2293b559e43ec8176379#subdirectory=skills-ref
Prepared 4 packages in 408ms
Installed 4 packages in 1ms
 + python-dateutil==2.9.0.post0
 + six==1.17.0
 + skills-ref==0.1.0 (from git+https://github.com/agentskills/agentskills.git@69ef37e9424c0a7ea9dd2293b559e43ec8176379#subdirectory=skills-ref)
 + strictyaml==1.7.3
```

## skills_ref
exit_code: 0
```text
Valid skill: skills/jobs-scraper
```

## plugin_manifest
exit_code: 0
```text
```

## stdio_v10
exit_code: 0
```text
STDIO_MCP_SMOKE_PASS ['audit_sheet', 'crawl_jobs', 'get_stats', 'sync_jobs_to_sheet']
```

## stdio_v11
exit_code: 0
```text
STDIO_MCP_V11_SMOKE_PASS ['audit_sheet', 'crawl_jobs', 'get_stats', 'initialize_job_tracker', 'sync_jobs_to_sheet']
```

## fresh_v10
exit_code: 0
```text
[fresh-install] src=/home/runner/work/jobs-scraper/jobs-scraper  dst=/tmp/jobs-scraper-fresh-cpo0sudo
[fresh-install] copied
[fresh-install] venv: /tmp/jobs-scraper-fresh-cpo0sudo/.venv/bin/python (using /home/runner/work/jobs-scraper/jobs-scraper/.venv/bin/python3.11)
[fresh-install] deps installed (incl. pytest from [dev])
[fresh-install] compile OK
[fresh-install] pytest OK
[fresh-install] server import OK
[fresh-install] MCP tools listed: tools: ['audit_sheet', 'crawl_jobs', 'get_stats', 'sync_jobs_to_sheet']
[fresh-install] SKILL.md frontmatter OK

🎉 fresh install qualified at /tmp/jobs-scraper-fresh-cpo0sudo
```

## fresh_v11
exit_code: 0
```text
[fresh-install] src=/home/runner/work/jobs-scraper/jobs-scraper  dst=/tmp/jobs-scraper-v11-fresh-igwzocaw
[fresh-install] copied
[fresh-install] venv: /tmp/jobs-scraper-v11-fresh-igwzocaw/.venv/bin/python (using /home/runner/work/jobs-scraper/jobs-scraper/.venv/bin/python3.11)
[fresh-install] deps installed (incl. pytest from [dev])
[fresh-install] compile OK
[fresh-install] pytest OK
[fresh-install] server import OK
[fresh-install] MCP tools listed: tools: ['audit_sheet', 'crawl_jobs', 'get_stats', 'sync_jobs_to_sheet']
[fresh-install] SKILL.md frontmatter OK

🎉 fresh install qualified at /tmp/jobs-scraper-v11-fresh-igwzocaw
[fresh-install-v1.1] v1.1 tools: ['audit_sheet', 'crawl_jobs', 'get_stats', 'initialize_job_tracker', 'sync_jobs_to_sheet']
[fresh-install-v1.1] STDIO_MCP_V11_SMOKE_PASS ['audit_sheet', 'crawl_jobs', 'get_stats', 'initialize_job_tracker', 'sync_jobs_to_sheet']
FRESH_INSTALL_V11_PASS
```

## production_id_hygiene
exit_code: 0
No production Sheet ID in distributable/test surfaces.
