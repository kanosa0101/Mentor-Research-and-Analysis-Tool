# Workflow v0.8 delivery — 2026-10-15

## Implemented

- Applications now has URL-addressable project/material/communication/reminder sections. `section=material` is used by contact preparation's material link. Current project is visible and supplies default links for new records.
- A valid target resolves its real project and mentor before initializing forms, overriding contradictory mentor/year URL hints. Existing record editing still loads that record's exact associations. Form reset and consecutive reminders retain current context.
- Application form edits have cancellation guards for section changes, editing another record, clearing, project changes, and leaving the page. Failed saves retain input and report alongside the active form.
- Contact preparation has an independent multi-reminder list and form, with edit/complete/reopen, bound to the selected target; a reply is no longer required to schedule a task. The list has bounded height and contact actions have quick section links.
- Draft/reply/reminder changes are guarded on view/target changes and leaving the page. Cancelling keeps input intact. Successful saves clear the relevant dirty state.
- Today separates due items from future plans. From a mentor with no project, the empty state names the already-selected mentor and offers one direct project-creation action. With projects it asks for the applicable project, not a repeated mentor search.
- Public navigation context school/dept/year/degree/route/track/program survives desk/manage/return navigation without extending private schema or automatically saving it. Target identity takes priority. Uncollected direction copy now says to verify the official page; default attachment history no longer displays hash strings.

## Files owned

`site/desk.js`, `site/workflow.js`, `site/templates/desk.html.j2`, `site/templates/applications.html.j2`, `scripts/contact_ui_check.py`, `scripts/application_ui_check.py`, new `scripts/workflow_v8_ui_check.py`.

No backend/schema/global CSS/nav/board/data edits. No build or commit. UI scripts render only the two owned templates into a temporary site and use temporary private storage; they do not need generated HTML updates to test current source.

## Verification

- Initial regression run failed at `target project context must be selected` after creating a valid temporary project/target. Fixed implementation then passed.
- `python scripts/workflow_v8_ui_check.py`: PASS. Includes valid-target overrides contradictory mentor/year, public program context preservation, known-mentor empty state, consecutive linked reminders, failed-save input preservation/local feedback, cancel section switch, cancel leaving an unsaved draft, independent reminders, edit/complete/reopen, cancel view switch, due/future split, no page errors, 390px horizontal overflow check.
- `python scripts/contact_ui_check.py`: PASS. Preserves EML download attachment verification, missing attachment removal, actual-sent explicit confirmation and lock, reply/task progression, persistence, backup/corrupt-index recovery, and offline controls. View-switch expectations updated for the newly required cancellation prompt.
- `python scripts/application_ui_check.py`: PASS. Project edits, material scan/associations, escaped historical event content, multiple reminders, completion/edit, persistence, backup/restore/corrupt-index recovery, mobile and offline controls. Section navigation added to existing flow assertions.
- `node --check site/desk.js`, `node --check site/workflow.js`, owned-file `git diff --check`: PASS.

## Screenshots

Latest 1440px/390px screenshots are under `cache/ux_v8/workflow/after/`: applications-desktop.png, applications-mobile.png, prepare-desktop.png, prepare-mobile.png, today-mobile.png. Full original path checks also save screenshots under `cache/ux_v8/workflow/contact` and `cache/ux_v8/workflow/application`. Before images and observed state JSON remain in `cache/ux_v8/workflow`.

## Boundaries

- Native browser leave-page prompts depend on browser user-interaction rules; no private form data is stored in browser storage.
- Legacy outreach board remains independent and unchanged. Historical communication supplement is named separately from editable contact drafts.
- No actual email was sent, no official pages crawled, and no personal eligibility or admission availability was inferred.
- Generated HTML is deliberately not rebuilt here; root owns final integration/build.

## Root visual iteration: four contact panels

- Replaced stacked contact forms/anchor links with `mail` (default), `tasks`, `reply`, and `history` panels. Mentor name, actual project, and current stage stay visible; longer background and stage controls are folded under a native details element.
- `panel` is URL-addressable, survives refresh and management return links, and is retained after saves. Switching panels uses the same unsaved-change guard as view/target changes; cancellation leaves both original panel and typed inputs intact.
- Regression was observed red on the original stacked page (`mail is the only default prepare panel`), then green after implementation. New assertions cover default visibility, draft/task cancellation, refresh retention, management round trip, and save retention. Original contact and application suites were adapted to open the required panels and passed, retaining EML/attachment/sent-lock/reply-task/backup checks.
- Final visual evidence in `cache/ux_v8/workflow/after`: `prepare-mobile-viewport.png` is 390x844 and `prepare-desktop-viewport.png` is 1440x1000, both default mail. Additional tasks/reply/history mobile viewport images and a separately named full-page mail screenshot are included. Empty status spacing and mobile context padding are compacted.
- All three UI scripts passed in isolated temporary rendered sites/private stores. No backend/schema changes, build, commit, or further feature additions in this iteration.
