# Discovery v0.9 — 2026-10-15

## Delivered

- Added an independent mentor-name field (trimmed, case-insensitive substring). It intersects research and other criteria; empty results explain that intersection. Name stays temporary and does not change the private preferences schema or research score.
- Discovery detail/proof/contact links and comparison entry now carry the public school/dept/year/degree/route/track/program scope. Comparison and detail preserve it through contact and return-to-discovery links. Unrelated URL values, including private notes, are discarded.
- A mentor link always uses the actual mentor school/dept. Track/program survive only when both incoming school and dept exactly match that mentor; missing incoming unit is not assumed compatible. Cross-unit/missing-unit contexts display a clear scope-clearing explanation. Year/degree/route survive.
- One saved comparison selection remains accessible after refresh: it displays the mentor, removal and contact action. Two to five selections retain the comparison table; removing the last selection restores the empty state. Existing compare_sel storage is reused.

## Verification

- Test-first reproduction: `python scripts/discovery_v9_ui_check.py` failed on the v0.8 implementation with `independent mentor name search is missing` before implementation.
- `python scripts/discovery_v9_ui_check.py`: PASS after changes. Synthetic public mentor fixtures, temporary template rendering and temporary private storage; no real private content read. Covers exact/partial/trimmed/English case-insensitive name matching, empty intersection, direct detail and comparison-to-detail-to-contact scope, unknown URL values excluded, cross-unit and missing-unit project scope cleared, visible warning, single-selection refresh/removal, 1/2/1/0 states, HTTP and file mode, no page errors, 390px page overflow.
- `node tests/discovery_rules.cjs`: PASS.
- `node tests/discovery_scope.cjs`: 3 passed; unsupported project scopes still cannot reuse legacy review pass/fail.
- `node --check site/discovery.js`: PASS.
- Scoped `git diff --check`: PASS.
- Screenshots in `cache/ux_v9/discovery/`: discovery-desktop.png, discovery-mobile.png, compare-desktop.png, compare-mobile.png. Desktop width 1440, mobile width 390. Visually inspected discovery desktop/mobile and comparison mobile; single mentor table remains contained on mobile.
- An intermediate expanded UI run timed out on Playwright's network-idle wait; the test now waits for DOM readiness plus Discovery's explicit ready signal and blocks external network requests. The complete final run passed.

## Boundaries

- Only site/discovery.js, templates/discovery.html.j2, templates/compare.html.j2, templates/detail.html.j2, scripts/discovery_v9_ui_check.py and this report were edited.
- No build, generated HTML, schema, dataset, core scoring, version token, staging or commit changes. The 11 pre-existing untracked sources remain untouched.
- These tests verify navigation into a temporary contact destination and query identity; contact/project persistence remains covered by the workflow owner's suites.
- Temporary name filtering is not retained through navigation; only the approved public scope whitelist is carried. Existing browser comparison storage remains the persistence mechanism; no new candidate-list backend was introduced.
