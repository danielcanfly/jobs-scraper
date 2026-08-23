# v1.1 implementation CI probe

Commit at checkout: cb860997ccc0f7a42dbdd0e259c8fd8a19409ae4

bootstrap_uv_exit_code: 0

## lock
exit_code: 0
```text
Using CPython 3.11.16 interpreter at: /opt/hostedtoolcache/Python/3.11.16/x64/bin/python3
Resolved 58 packages in 0.53ms
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
........................................................................ [ 72%]
............................                                             [100%]
```

## doctor
exit_code: 0
```text
🩺 jobs-scraper doctor
============================================================
  ✅ Python: 3.11 (need >= 3.11)
  ✅ venv interpreter: /home/runner/work/jobs-scraper/jobs-scraper/.venv/bin/python (exists)
  ✅ imports: OK
  ✅ file: sg_product_jobs.py: exists
  ✅ file: server.py: exists
  ✅ file: pyproject.toml: exists
  ✅ file: LICENSE: exists
  ✅ file: .gitignore: exists
  ✅ file: skills/jobs-scraper/SKILL.md: exists
  ✅ file: .codex-plugin/plugin.json: exists
  ⚠️  sheet config: 未設定: GSPREAD_SA_KEY_PATH, SHEET_ID, SHEET_GID — Sheet tools 會回 CONFIG_MISSING 結構化錯誤
  ✅ git hygiene: OK (no secrets tracked)
============================================================
⚠️  doctor: warnings only (Sheet tools 不一定可用, 但 scraper CLI 跟 read-only MCP 可用)
```

## skills_install
exit_code: 0
```text
   Updating https://github.com/agentskills/agentskills.git (69ef37e9424c0a7ea9dd2293b559e43ec8176379)
    Updated https://github.com/agentskills/agentskills.git (69ef37e9424c0a7ea9dd2293b559e43ec8176379)
Resolved 5 packages in 458ms
   Building skills-ref @ git+https://github.com/agentskills/agentskills.git@69ef37e9424c0a7ea9dd2293b559e43ec8176379#subdirectory=skills-ref
      Built skills-ref @ git+https://github.com/agentskills/agentskills.git@69ef37e9424c0a7ea9dd2293b559e43ec8176379#subdirectory=skills-ref
Prepared 4 packages in 321ms
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
exit_code: 1
```text
  |     asyncio.run(run())
  |   File "/opt/hostedtoolcache/Python/3.11.16/x64/lib/python3.11/asyncio/runners.py", line 190, in run
  |     return runner.run(main)
  |            ^^^^^^^^^^^^^^^^
  |   File "/opt/hostedtoolcache/Python/3.11.16/x64/lib/python3.11/asyncio/runners.py", line 118, in run
  |     return self._loop.run_until_complete(task)
  |            ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  |   File "/opt/hostedtoolcache/Python/3.11.16/x64/lib/python3.11/asyncio/base_events.py", line 654, in run_until_complete
  |     return future.result()
  |            ^^^^^^^^^^^^^^^
  |   File "/home/runner/work/jobs-scraper/jobs-scraper/scripts/verify_mcp_stdio_v11.py", line 25, in run
  |     async with stdio_client(params) as (read, write):
  |   File "/opt/hostedtoolcache/Python/3.11.16/x64/lib/python3.11/contextlib.py", line 231, in __aexit__
  |     await self.gen.athrow(typ, value, traceback)
  |   File "/home/runner/work/jobs-scraper/jobs-scraper/.venv/lib/python3.11/site-packages/mcp/client/stdio.py", line 200, in stdio_client
  |     async with anyio.create_task_group() as tg:
  |   File "/home/runner/work/jobs-scraper/jobs-scraper/.venv/lib/python3.11/site-packages/anyio/_backends/_asyncio.py", line 815, in __aexit__
  |     raise BaseExceptionGroup(
  | ExceptionGroup: unhandled errors in a TaskGroup (1 sub-exception)
  +-+---------------- 1 ----------------
    | Exception Group Traceback (most recent call last):
    |   File "/home/runner/work/jobs-scraper/jobs-scraper/.venv/lib/python3.11/site-packages/mcp/client/stdio.py", line 204, in stdio_client
    |     yield read_stream, write_stream
    |   File "/home/runner/work/jobs-scraper/jobs-scraper/scripts/verify_mcp_stdio_v11.py", line 26, in run
    |     async with ClientSession(read, write) as session:
    |   File "/home/runner/work/jobs-scraper/jobs-scraper/.venv/lib/python3.11/site-packages/mcp/client/session.py", line 481, in __aexit__
    |     result = await self._task_group.__aexit__(exc_type, exc_val, exc_tb)
    |              ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
    |   File "/home/runner/work/jobs-scraper/jobs-scraper/.venv/lib/python3.11/site-packages/anyio/_backends/_asyncio.py", line 815, in __aexit__
    |     raise BaseExceptionGroup(
    | ExceptionGroup: unhandled errors in a TaskGroup (1 sub-exception)
    +-+---------------- 1 ----------------
      | Traceback (most recent call last):
      |   File "/home/runner/work/jobs-scraper/jobs-scraper/scripts/verify_mcp_stdio_v11.py", line 40, in run
      |     props = (sync.inputSchema or {}).get("properties") or {}
      |              ^^^^^^^^^^^^^^^^
      |   File "/home/runner/work/jobs-scraper/jobs-scraper/.venv/lib/python3.11/site-packages/pydantic/main.py", line 1042, in __getattr__
      |     raise AttributeError(f'{type(self).__name__!r} object has no attribute {item!r}')
      | AttributeError: 'Tool' object has no attribute 'inputSchema'. Did you mean: 'input_schema'?
      +------------------------------------
```

## fresh_v10
exit_code: 0
```text
[fresh-install] src=/home/runner/work/jobs-scraper/jobs-scraper  dst=/tmp/jobs-scraper-fresh-qkjvxx5w
[fresh-install] copied
[fresh-install] venv: /tmp/jobs-scraper-fresh-qkjvxx5w/.venv/bin/python (using /home/runner/work/jobs-scraper/jobs-scraper/.venv/bin/python3.11)
[fresh-install] deps installed (incl. pytest from [dev])
[fresh-install] compile OK
[fresh-install] pytest OK
[fresh-install] server import OK
[fresh-install] MCP tools listed: tools: ['audit_sheet', 'crawl_jobs', 'get_stats', 'sync_jobs_to_sheet']
[fresh-install] SKILL.md frontmatter OK

🎉 fresh install qualified at /tmp/jobs-scraper-fresh-qkjvxx5w
```

## fresh_v11
exit_code: 1
```text
  |   File "/opt/hostedtoolcache/Python/3.11.16/x64/lib/python3.11/asyncio/runners.py", line 190, in run
  |     return runner.run(main)
  |            ^^^^^^^^^^^^^^^^
  |   File "/opt/hostedtoolcache/Python/3.11.16/x64/lib/python3.11/asyncio/runners.py", line 118, in run
  |     return self._loop.run_until_complete(task)
  |            ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  |   File "/opt/hostedtoolcache/Python/3.11.16/x64/lib/python3.11/asyncio/base_events.py", line 654, in run_until_complete
  |     return future.result()
  |            ^^^^^^^^^^^^^^^
  |   File "/tmp/jobs-scraper-v11-fresh-mm3m0fgo/scripts/verify_mcp_stdio_v11.py", line 25, in run
  |     async with stdio_client(params) as (read, write):
  |   File "/opt/hostedtoolcache/Python/3.11.16/x64/lib/python3.11/contextlib.py", line 231, in __aexit__
  |     await self.gen.athrow(typ, value, traceback)
  |   File "/tmp/jobs-scraper-v11-fresh-mm3m0fgo/.venv/lib/python3.11/site-packages/mcp/client/stdio.py", line 200, in stdio_client
  |     async with anyio.create_task_group() as tg:
  |   File "/tmp/jobs-scraper-v11-fresh-mm3m0fgo/.venv/lib/python3.11/site-packages/anyio/_backends/_asyncio.py", line 815, in __aexit__
  |     raise BaseExceptionGroup(
  | ExceptionGroup: unhandled errors in a TaskGroup (1 sub-exception)
  +-+---------------- 1 ----------------
    | Exception Group Traceback (most recent call last):
    |   File "/tmp/jobs-scraper-v11-fresh-mm3m0fgo/.venv/lib/python3.11/site-packages/mcp/client/stdio.py", line 204, in stdio_client
    |     yield read_stream, write_stream
    |   File "/tmp/jobs-scraper-v11-fresh-mm3m0fgo/scripts/verify_mcp_stdio_v11.py", line 26, in run
    |     async with ClientSession(read, write) as session:
    |   File "/tmp/jobs-scraper-v11-fresh-mm3m0fgo/.venv/lib/python3.11/site-packages/mcp/client/session.py", line 481, in __aexit__
    |     result = await self._task_group.__aexit__(exc_type, exc_val, exc_tb)
    |              ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
    |   File "/tmp/jobs-scraper-v11-fresh-mm3m0fgo/.venv/lib/python3.11/site-packages/anyio/_backends/_asyncio.py", line 815, in __aexit__
    |     raise BaseExceptionGroup(
    | ExceptionGroup: unhandled errors in a TaskGroup (1 sub-exception)
    +-+---------------- 1 ----------------
      | Traceback (most recent call last):
      |   File "/tmp/jobs-scraper-v11-fresh-mm3m0fgo/scripts/verify_mcp_stdio_v11.py", line 40, in run
      |     props = (sync.inputSchema or {}).get("properties") or {}
      |              ^^^^^^^^^^^^^^^^
      |   File "/tmp/jobs-scraper-v11-fresh-mm3m0fgo/.venv/lib/python3.11/site-packages/pydantic/main.py", line 1042, in __getattr__
      |     raise AttributeError(f'{type(self).__name__!r} object has no attribute {item!r}')
      | AttributeError: 'Tool' object has no attribute 'inputSchema'. Did you mean: 'input_schema'?
      +------------------------------------

```

## production_id_hygiene
exit_code: 0
No production Sheet ID in distributable/test surfaces.
