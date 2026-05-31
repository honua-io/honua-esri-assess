# Pagination Cap Exhaustion Diagnostic - Scope Plan

## Finding
Portal and Server pagination helpers silently truncate when enumeration exceeds 100 pages, violating the diagnostic guarantee that "soft coverage gaps surface through diagnostics[]".

## Architecture

### Portal.py (_paginate at lines 360-394)
Call sites with scope identifiers:
- Line 128: _collect_roles() → scope="portal.access.roles"
- Line 196: _collect_groups() → scope="portal.access.groups"
- Line 295: _collect_users() → scope="portal.access.users"

Loop cap: range(100)
Exhaustion signal: loop completes AND last_payload.get('nextStart') is int > 0

### Server.py (_paginate at lines 250-281)
Call sites with scope identifiers:
- Line 121: _collect_users() → scope="server.access.users"
- Line 177: _collect_roles() → scope="server.access.roles"

Loop cap: range(100)
Exhaustion signal: loop completes AND (last_payload.get('hasMore') OR last_payload.get('hasNext')) truthy

## Fix Strategy
1. Modify both _paginate helpers to track loop completion vs early exit
2. On cap exhaustion, append Diagnostic(code="partial-coverage", scope=<call_site>, message=<generic>, hint="Pagination cap of 100 reached; re-run with tighter query if full enumeration needed", severity="warn") to diagnostics list before return
3. Do NOT modify cap (100) — it's defensive; only add diagnostic
4. Diagnostic class is at src/honua_esri_assess/diagnostics.py:48-79; "partial-coverage" is in DIAGNOSTIC_CODES

## Regression Tests Required
- Portal: 3 tests (roles, groups, users pagination cap)
- Server: 2 tests (users, roles pagination cap)
- Each: fixture HTTP client with responses always indicating more pages (nextStart > 0 / hasMore/hasNext=true)
- Assert: collection stops at 100 iterations AND exactly one partial-coverage diagnostic emitted per scope

## Key Invariants
- Early exit conditions (invalid response, zero nextStart, nextStart==start) must NOT trigger diagnostic
- Diagnostic scope matches the _paginate call site scope exactly
- Hint should guide users to re-run with tighter org-scope query (e.g., per-group or time-bounded)