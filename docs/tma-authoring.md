# Tutor Marked Assignment authoring

Admins enter at `/admin/tma`; teachers enter at `/teacher/tma`. Both roles share the same editor. The sidebar entry is present in desktop and mobile menus. Mobile drawers and the five-button bottom dock keep their existing layout.

Creating an assignment selects a level, a subject filtered to that level, the current term, a non-examinable/non-hybrid assessment component and an optional expected closing time. Saving opens the assignment editor. The closing time is informational; access ends through the manual Close action. Component eligibility is rechecked during activation and score writing, including for existing assignments.

The new authenticated `/api/v1/tma/configuration` endpoint returns tenant-scoped choices and checks the existing teacher authoring guard for each level/subject. It does not grant any additional write permissions.

## Authoring API coverage

The UI consumes assignment create/list/get/update; question list/create/update/delete; readiness and activation; media upload/list/signed URL/delete; AI generate/regenerate/import; submissions with search, class, status and pagination; close/cancel/cancellation status/retry; revision history and corrected revision creation. Student attempt APIs belong to the separate student interface.

Questions support text, images, a minimum of four options and exactly one correct answer. Edits include the backend question version; conflicts require reloading. Only a lead teacher or admin sees management actions. Collaborators can add questions, edit their own questions and adjust the closing estimate.

The Questions, Submissions and History sections use touch-sized controls, wrapping action rows, single-column mobile cards and viewport-constrained shared dialogs. Destructive lifecycle actions explain their consequences before confirmation. Cancellation is polled while pending; failed cancellations expose retry.

## Mathematics

The display parser follows the CBT convention: source text stays unchanged, while inline `\(…\)`/`$…$`, display `\[…\]`/`$$…$$`, fractions, roots and selected bare commands are recognized. Currency remains text. Unicode symbols can be inserted at the cursor. KaTeX renders recognized equations with untrusted commands disabled, expansion limits and local bundled fonts. No remote rendering service or script is used.

AI generation uses the existing wallet and charging pipeline. Generated questions are previewed individually before import. The generation key is retained for a retry of an uncertain request. Wallet purchasing and school credit administration remain separate from assignment authoring.

## Verification boundaries

The focused backend suite, frontend unit/mobile shell checks, changed-file lint, API contract checker and production build were run. Authenticated browser acceptance remains pending: the preview reaches the login screen, but a local backend must be running for login and actual create/edit/AI workflows. No live assignments, credit charges or lifecycle actions were performed during verification. Real iOS/Android device testing is still required before claiming mobile visual acceptance.

The backend's existing teacher-list pagination filters after fetching a tenant page, so a page may contain fewer than 24 visible assignments and its total is not a global count. The UI uses page navigation rather than displaying that count as an overall total.

No migration or deployment configuration change is required. Deploy the backend configuration endpoint before or alongside the frontend. Rolling back the frontend removes the entry points without deleting assignments or student data.

## Redis caching

Staff configuration and image metadata use 60-second TTLs; assignment lists and question payloads use 15 seconds; revision history uses 30 seconds. Keys include tenant, actor type/ID, resource and normalized filters/pagination. Current teacher authorization is checked before cached staff records are returned. Assignment details, student attempts/answers/results, submissions, readiness, cancellation status and signed image URLs remain live reads. No browser cache is added.

The central model registry installs transaction-aware TMA invalidation listeners. Flushed assignment, question, revision, media and related academic/curriculum/class/teacher/enrollment changes queue tenant-generation invalidation. The existing cache event pipeline deletes the generation key after a successful commit; TMA services flush it immediately after their own commits, including cancellation worker paths. The Core SQL media-delete path queues invalidation explicitly. A rollback discards queued TMA invalidation; a savepoint rollback preserves outer transaction events.

Generation keys use random namespaces. An older in-flight request cannot populate the namespace used after invalidation, even when reads and writes overlap. Previous entries expire under their short TTLs. Redis failures use the database path. Cache tests cover isolation, parameter identity, invalidation, rollback, race behavior and database fallback; an external Redis instance has not been exercised in this implementation session.

## Search performance (November 2026)

The authoring overview loads configuration and term options on page entry, independently from the assignment-list search. Search controls remain mounted while pages update, and stale list requests are aborted when filters change. Assignment search is debounced for 250 ms. The submissions roster uses a 300 ms debounce and keeps the previous rows visible while its replacement is loading. API reads accept an optional caller AbortSignal without weakening the existing route-change and timeout guards.

Admin assignment pages also use a bounded, component-local 15-second cache (up to 30 filter/page combinations) and are cleared after local mutations. Teacher pages intentionally **do not use this browser cache**: their current teaching authorizations must be revalidated by the server. In the backend, configuration and assignment-list response caching is only enabled for administrators; teacher reads are uncached to avoid disclosing revoked scopes. PostgreSQL `pg_trgm` GIN indexes accelerate subject/level substring search and student admission number/full-name lookup; the full-name search expression matches its immutable index expression. The indexes are installed online by migration `20261104_tma_search_trigram` and should be checked with representative `EXPLAIN (ANALYZE, BUFFERS)` plans after migration.
