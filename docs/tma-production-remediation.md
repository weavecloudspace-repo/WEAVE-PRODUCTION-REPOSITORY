# TMA production remediation and query review

Repository: `weavecloudspace-repo/WEAVE-PRODUCTION-REPOSITORY`
Branch: `feature/openrouter-ddgs-ai-optimization`
Starting commit: `480fe7cdaf6de56b4bd00fc2f904df2c0c520700`

## Changes and root causes

| Blocker | Confirmed cause | Correction |
| --- | --- | --- |
| Revision grading | Assignment completion/error markers survived revision creation; failures and exemptions were unique only by assignment/student. | Archive old lifecycle fields on the previous revision, reset the new lifecycle, and key failures/exemptions by tenant, assignment, revision and student. A failed old worker cannot update a newer revision's error state. |
| Teacher pagination | The service filtered an already paginated page; the router replaced the total with the current page length. | Resolve current curriculum/teaching scope in bulk and apply it to the SQL count and page queries. Keep deterministic creation-time/ID ordering and EXISTS-based duplicate prevention. Teacher listings bypass stale authorization caches. |
| Reporting scope | Level/subject authoring access was treated as access to every classroom's students. | Apply current classroom authorization inside live roster, deadline snapshot, participation history and cancellation/zero reconciliation queries. Administrators retain tenant scope. Creator identity remains audit data, not an access grant. |
| Deadline eligibility | Current enrollment, electives and curriculum were re-resolved when a delayed worker ran. Enrollment segments retain dates, but elective selections do not retain history. | Capture an immutable revision roster before the first subsequent eligibility-affecting mutation, or when the worker/report first reads a due assignment. Database triggers cover enrollment, student status, electives, classroom/curriculum/specialization and term changes. Scoring uses the recorded enrollment and subject identity. |
| Worker throughput | One assignment, 25 writes per minute, repeated scans through the full reporting roster. | Query pending snapshot students directly, exclude submissions/exemptions in SQL, use bounded batches and per-student savepoints, and rotate tenants/assignments by last processing time. Retry unresolved failures without overwriting scores. |
| Integration coverage | Critical service workflows had only mocked persistence coverage. | Add real PostgreSQL lifecycle, reporting, deadline, revision, result-integrity, retry, constraint, concurrency and query-budget tests. Tests use real services/repositories and mock external delivery only. |

A further concurrency test exposed stale SQLAlchemy identity-map state after waiting for a row lock. Assignment and attempt lock reads now refresh existing ORM instances. Simultaneous submissions replay the persisted result rather than attempting a second score write.

Published deadlines cannot be backdated or extended after expiry while the assignment still appears ACTIVE: otherwise an old snapshot could be reused for a different eligibility window. Staff close, cancel and revise an expired assignment instead. Future deadline edits and draft configuration retain their existing workflows.

## Frontend feedback

Publication failures now use the existing global error toast, with persistent, numbered messages. Successful readiness checks retain the publication confirmation dialog. Missing-teacher messages use classroom names. The inserted Windows-encoded bullet was corrected to UTF-8 and replaced with ASCII numbering. Frozen mobile navigation/sidebar files were not changed.

## N+1 query review

| Path | Optimization and measured protection |
| --- | --- |
| TMA configuration | Resolve all classrooms/curricula once and load current teaching ownership once. SELECT count stays constant as eligible subjects grow from 1 to 10, for administrators and teachers. |
| Student TMA discovery | Bulk-load current revisions, assessment components and subject-teacher ownership. SELECT count stays constant from 1 to 10 assignments. |
| TMA image ownership | Validate all referenced image IDs with one tenant-and-assignment-scoped query. |
| TMA AI text import | Reuse the transaction's authorized draft lock and calculate starting question position once. SELECT count stays constant from 2 to 10 imported questions. Existing atomicity, media cleanup and idempotency remain. |
| TMA cancellation | Lock owned score/result rows in bulk and use the existing component-score batch repository. Recompute totals without per-student reads; load grading scales once only when complete results need regrading. SELECT count stays constant from 2 to 10 students. |
| CBT AI expired credit recovery | Lock exact tenant/account/week buckets once, lock top-up buckets once, mutate shared bucket objects and flush at commit. Both 1 and 20 reservations use 3 SELECTs. Retain historical-week validation, reserved-credit checks, rollback and SKIP LOCKED reservation claims. |

Already joined CBT AI actor/quota reporting was retained. Provider image requests, tool calls, pacing and retry loops are not database N+1 queries and were not turned into unbounded concurrent work. Historical teacher lists still resolve each distinct term because specialization is term-specific; they do not re-authorize each assignment. Individual grading retains bounded per-student integrity checks and writes.

## Database changes

Migration: `backend/alembic/versions/20261102_tma_revision_safety.py`, following `20261102_tma_zero_reconcile` on the existing chain.

- Revision columns: `zero_grading_requested_at`, `zero_grading_completed_at`, `zero_grading_error`, `eligibility_tracking_started_at`, `eligibility_captured_at`.
- Assignment column: `zero_grading_last_processed_at` for fair scheduling.
- Failure column: non-null `revision_number`, backfilled from the recorded failure time and revision creation timeline. Unresolvable associations fail the transactional migration instead of inventing provenance.
- Replace assignment/student uniqueness with `uq_tma_zero_failure_revision_student`; add the tenant/assignment/revision foreign key. Existing failure, exemption and audit rows are retained.
- New `tma_deadline_eligibility` table, keyed by tenant/revision/student, recording enrollment, classroom and subject IDs. Foreign keys preserve revision and enrollment identity.
- Database capture functions and BEFORE INSERT/UPDATE/DELETE triggers on the eligibility source tables preserve the state before post-deadline mutations. The primary/unique keys also support the scoped lookups.

No assignments, attempts, scores, questions or audit history are deleted by the migration. No pricing, payment, tenant identity or deployment infrastructure configuration changed. The new worker settings are application defaults, not edits to live environment variables:

- `TMA_ZERO_BATCH_SIZE=200` (1..500)
- `TMA_ZERO_BATCHES_PER_POLL=8` (1..32)
- `TMA_ZERO_POLL_BUDGET_SECONDS=90` (1..100)

Deploy while API/worker writers are stopped, apply the migration, deploy matching API and worker code, and then resume writers. Old workers cannot use the renamed assignment-wide failure constraint. Downgrade deliberately refuses to discard or merge revision history; rollback uses a forward repair while retaining the additive audit schema.

Past deadlines that predate reliable tracking cannot be reconstructed. They fail closed and remain visible as pending reconciliation; administrators must review/cancel/revise them. Tracking begins at migration/publication, not at a fabricated historical date. Test timings are local PostgreSQL results, not a production latency guarantee.

## Verification

Final local results (all executed successfully):

| Check | Result |
| --- | --- |
| Backend unit suite | 1,704 passed; 0 failed/skipped |
| PostgreSQL integration suite | 47 passed; 0 failed/skipped, including 33 TMA/CBT AI cases |
| Frontend full suite | 523 passed; 0 failed/skipped |
| Ruff | Passed for the backend |
| Pyright | 0 errors, 0 warnings for the changed production areas |
| Alembic | One head, development database at head, no new upgrade operations detected |
| API contracts | 379 frontend contracts validated against 551 FastAPI routes |
| Frontend ESLint | Passed with 4 existing hook warnings |
| Production frontend build | Passed; existing chunk/Browserslist/plugin warnings remain |

The 1,200-student integration case completed in six batches of at most 200; the final run took 97 seconds including its student setup and database assertions. This is a local integration timing, not an isolated worker benchmark.

Reproduction uses `backend/.tma_test_runner.py tests/unit -q` and `backend/.tma_test_runner.py tests/integration -q` through the backend virtual-environment Python. The launcher explicitly checks for the user-selected local `weave_dev_database` and sets the repository test URL accordingly. Async tests required execution outside the restricted sandbox because even event-loop initialization stalled inside it.

Validation includes:

- Full backend unit suite and full PostgreSQL integration suite, using the repository pytest configuration.
- Dedicated PostgreSQL TMA tests for 100/1,200 students, duplicate polling, submitted-score protection, partial write rollback/retry, snapshot uniqueness, revision/exemption isolation, teacher reassignment, cross-tenant access, direct HTTP authorization, term closure, concurrent workers/reassignment, concurrent revision creation, simultaneous submissions, cancellation/grading races and unrelated-score preservation.
- PostgreSQL query budgets for TMA configuration/discovery/import/cancellation and CBT AI credit recovery.
- Ruff, changed-production-code Pyright, Alembic single-head/current-head and drift checks.
- Frontend tests, ESLint, frontend/backend route contracts and production Vite build.

The user explicitly selected `weave_dev_database`. Final database tests use newly generated tenant records; ordinary fixtures roll back, and independent-connection tests remove only their own uniquely identified seed graph. A failed early fixture cleanup was corrected and its one remaining generated tenant was removed after identity verification. A separate empty local test database was initially created for migration validation before the user selected the development database; it was not dropped.

Hosted CI was not verified: the GitHub app status tool required a connection link that was unavailable in this session, and no GitHub CLI was installed. No hosted CI success is claimed. Hosted CI and deployment are separate from local checks. No PR or merge was requested. No new branch was created and no staging/master merge was performed. A real browser/device walkthrough, live AI provider execution and production deployment are not claimed as verified.

## Main files

- TMA services/repositories: `assignment_service.py`, `authorization.py`, `reporting_service.py`, `reporting_repository.py`, `cancellation_service.py`, `cancellation_reconciliation_service.py`, `zero_reconciliation_service.py`, `deadline_zero_service.py`, `deadline_eligibility_repository.py`, `grading_service.py`, `lifecycle_service.py`, `configuration_service.py`, `attempt_service.py`, `question_service.py`, `ai_service.py`, `repository.py`, `models.py`, `router.py` under `backend/app/modules/tma/`.
- Shared batch reads: `backend/app/modules/student_academics/repository.py` and `assessment_repository.py`.
- CBT AI batching: `backend/app/modules/cbt/ai/quota/repository.py` and `service.py`.
- Worker/settings: `backend/app/core/queue/heavy_worker.py`, `backend/app/config/settings.py`.
- New PostgreSQL tests: `backend/tests/integration/tma/conftest.py`, `test_production_blockers.py`, `test_query_batching.py`.
- New unit guard tests: `backend/tests/unit/test_tma_revision_safety.py`; existing TMA/AI quota tests updated for bulk interfaces and regression cases.
- Toast UI/tests: `frontend/src/features/tma/TmaPage.jsx`, `frontend/test/unit/tma-publication-toast.test.js`.
