# Repository Agent Rules

This file applies to every AI agent, automation, and contributor working in this repository. Its purpose is to protect production stability, user data, tenant isolation, and reviewability.

## Core principles

1. Inspect the relevant code, tests, configuration, branch state, and existing conventions before changing anything.
2. Make the smallest change that fully satisfies the request.
3. Preserve unrelated behavior. Do not perform opportunistic refactors, broad renames, or repository-wide formatting.
4. Never claim a test, CI run, merge, or deployment succeeded without verifying it.
5. Clearly report anything that could not be verified.

## Git and branch safety

- Do not commit directly to `master` or `staging` unless the user explicitly requests it.
- Use a dedicated branch for each logical task.
- Keep unrelated work out of the branch and commit.
- Review the complete diff before committing.
- Prefer one focused commit when practical to avoid unnecessary deployments.
- Open changes against `staging` first unless the user specifies another target.
- Promote `staging` to `master` only after required checks pass and the user authorizes the merge.
- Never force-push shared branches, rewrite shared history, bypass branch protection, or merge while required checks are failing, pending, or unknown.
- Never discard uncommitted user work. Stage only files that belong to the current task.

## Scope control

Agents must not:

- Change business logic while fixing linting, formatting, typing, tests, or CI.
- Remove compatibility code without inspecting all callers.
- Introduce new dependencies, services, abstractions, or infrastructure unless required by the task.
- Delete files simply because they appear unused.
- Modify unrelated routes, models, schemas, components, environment variables, or deployment settings.

## Database and migration safety

- Treat production and tenant data as irreplaceable.
- Do not remove tables, columns, constraints, indexes, enum values, migration history, or existing records without explicit approval.
- Do not run destructive database commands against staging or production.
- Prefer additive, backward-compatible migrations.
- Review every generated migration before committing it.
- Every migration must account for existing rows, deployment order, downgrade behavior, and rollback risk.
- Changes to keys, uniqueness rules, ownership relationships, or lifecycle states require focused tests and explicit justification.

## Multi-tenant isolation

Tenant isolation is a release-critical security boundary.

- Every tenant-owned read, write, update, delete, export, import, cache entry, notification, and worker job must enforce tenant scope.
- Verify that actor memberships belong to the selected tenant.
- Preserve the distinction between global accounts and tenant memberships.
- Include tenant context in cache keys for tenant-owned data.
- Do not weaken tenant filters to resolve missing-data or authorization problems.
- Treat any possible cross-tenant exposure as a release blocker.

## Authentication and authorization

- Backend authorization is mandatory even when the frontend hides an action.
- Never disable permission checks to make a route work.
- Never trust role, tenant, actor, plan, price, limit, or entitlement values supplied only by the frontend.
- Do not expose credentials, session values, access codes, one-time codes, or authorization headers in logs, responses, tests, or pull requests.
- Authentication-sensitive changes should test invalid identity, wrong role, wrong tenant, expired session, and invalid input where applicable.

## Payments and subscriptions

- The backend is the source of truth for prices, plans, limits, and entitlements.
- Verify payment-provider responses, expected amounts, tenant ownership, and idempotency before recording success.
- Do not change live pricing, billing cadence, limits, webhooks, or entitlement behavior without explicit approval.
- Payment changes require regression tests for duplicate events, invalid amounts, failed verification, and unknown plans.

## Email, notifications, and workers

- Never allow automated tests or development environments to send real bulk messages.
- Mock external providers in tests.
- Preserve environment-specific provider routing and retry behavior unless the task explicitly changes it.
- Worker jobs must be idempotent and tenant-aware.
- Prevent duplicate invitations, notifications, campaigns, and one-time-code messages.
- Do not modify email providers, queues, monitoring, or worker infrastructure outside the requested scope.

## API contract safety

Inspect both backend routes and frontend consumers before changing an API.

Do not silently change route paths, HTTP methods, request fields, response shapes, status codes, pagination, error formats, enum values, or date/time semantics. When a contract change is required, update backend code, frontend consumers, tests, and compatibility handling together.

## Frontend and mobile safety

Shared shell, theme, navigation, modal, keyboard, viewport, scrolling, and safe-area changes must consider:

- iOS browser mode
- iOS standalone PWA mode
- Android browser mode
- Android standalone PWA mode
- Desktop browsers

Do not fix one platform by breaking another. Preserve accessibility, keyboard support, scrolling, safe-area behavior, fixed navigation, and frontend authentication state.

## Frozen mobile navigation and sidebar layouts (explicit owner approval required)

**This is a user-approved layout freeze, not a request to fix the remaining Safari appearance.** The current installed iOS PWA bottom navigation is stable and must be preserved. The current mobile sidebars in PWA and browser mode are also accepted as-is, even if native Safari browser chrome still looks imperfect. Do not reinterpret unrelated bug reports, design work, CI cleanup, or "mobile improvements" as permission to redesign these areas.

### Protected iOS standalone PWA bottom navigation

- Preserve the **existing five-button design and exact placement** as a non-scrolling bottom flex row inside the dashboard's main frame. `DashboardLayout.jsx` renders `<BottomNav />` **after** `#dashboard-scroll-viewport` inside `[data-dashboard-main-frame="true"]`; do not relocate it.
- Preserve the iOS standalone rules in `mobilePwaStability.css` that make `[data-dashboard-main-frame="true"] > [data-mobile-bottom-nav="true"]` a `position: relative`, `flex: 0 0 auto` row and keep the surrounding shell and scroll viewport behavior intact.
- **Never revert to `position: fixed`, `position: absolute`, new bottom/transform offsets, independent viewport anchors, or extra safe-area/footer spacers for the iOS dock.** Do not restore height-vs-viewport positioning logic or double-reserve scroll clearance.
- Preserve the dock's current appearance, tab ordering, dimensions, interaction, brand/theme integration, and behavior through login, logout, keyboard dismissal, navigation, and PWA resume. Do not change CSS selectors or ancestors in ways that indirectly reposition it.

### Protected mobile sidebars in browser and PWA

- Preserve the existing `MobileDrawer.jsx` + `Sidebar.jsx` structure, full-height panel, close button, separate scrolling menu, Help & Support behavior, current tenant branding, and light/dark theme behavior for both mobile browser and installed PWA.
- Do not introduce an extra pinned sidebar footer, separate bottom overlay, clipping container, competing scroll region, or safe-area spacer; do not change the drawer's width, height, positioning, corner geometry, or stacking without explicit approval.
- Preserve the current mobile Safari browser-only document/page canvas, drawer backdrop, and native toolbar interactions in `iosSafariBrowserTheme.css` and `themeChromeSync.js`. **The owner accepts the current Safari result for now: do not make further experimental fixes to the browser bottom strip or native toolbar tint.** Safari browser chrome is OS-controlled.
- Do not apply browser-only drawer changes to standalone PWA or apply PWA navbar positioning overrides to browser mode. Keep desktop navigation and sidebar untouched.

### Change authorization and verification

- Treat these locations as **protected invariants** for every subsequent task. Before editing `DashboardLayout.jsx`, `BottomNav.jsx`, `MobileDrawer.jsx`, `Sidebar.jsx`, `mobilePwaStability.css`, `mobileDashboard.css`, `mobilePlatformFixes.css`, `iosSafariBrowserTheme.css`, or `themeChromeSync.js`, check whether the change can impact the frozen layouts. If so, keep the protected behavior untouched.
- **Only a new, explicit instruction from the repository owner requesting a specific change to the protected navigation/sidebar layout overrides this freeze.** Explain its expected visual/behavioral impact and obtain approval before making it. General authorization to implement an unrelated feature, refactor, or bug fix is not sufficient.
- If a necessary change conflicts with this freeze, stop and request that specific authorization; do not silently work around these rules through global CSS, DOM rearrangement, viewport meta tags, theming, or safe-area adjustments.
- Whenever authorized changes touch these areas, add or maintain regression coverage for iOS browser, iOS standalone PWA (including repeated login/logout and keyboard transitions), Android, desktop, drawer scrolling/closing, and light/dark + tenant branding; require the normal staging-to-master CI gates and real-device verification before declaring the visual issue resolved.

## Configuration and sensitive data

- Never commit credentials or private configuration.
- Use environment variables and safe placeholders in example files.
- Do not print sensitive values in logs, exceptions, CI output, snapshots, or pull-request descriptions.
- If sensitive data is discovered, identify the affected file without repeating the value and recommend rotation.
- Do not alter production environment variables, domains, health checks, build commands, start commands, regions, scaling, or service configuration without explicit approval.

## Dependencies

Before adding or upgrading a dependency:

1. Confirm it is required.
2. Check whether equivalent functionality already exists.
3. Verify runtime and framework compatibility.
4. Avoid unrelated major upgrades.
5. Update the correct lockfile.
6. Run relevant tests and builds.

Do not remove a dependency without checking runtime imports, scripts, workers, build configuration, and deployment usage.

## Testing and CI

Every change must be validated according to its risk.

- Run the tests directly related to modified code.
- Run relevant formatting, linting, typing, build, and frontend-backend contract checks.
- Add a regression test for each bug fix where practical.
- Never delete, skip, weaken, or replace meaningful tests merely to make CI green.
- If a check cannot run, report the exact reason and the remaining risk.
- Do not merge until required checks are green and the merge is authorized.

## Deployment hygiene

- Avoid unnecessary commits that trigger repeated Vercel or Railway deployments.
- Do not delete or reconfigure production services, databases, caches, workers, projects, or domains without explicit approval.
- A merged commit is not proof of a successful deployment. Verify deployment status separately when requested.
- Schema changes must include a safe deployment order and rollback plan.

## Required workflow

For each repository task:

1. Confirm the exact scope and protected areas involved.
2. Inspect the relevant implementation and tests.
3. Select the smallest safe change.
4. Work on the correct branch.
5. Modify only necessary files.
6. Review the entire diff.
7. Run relevant checks.
8. Commit with a focused message.
9. Push and open the correct pull request when applicable.
10. Inspect CI.
11. Merge only when authorized and green.
12. Verify the target branch and deployment when requested.

## Required completion report

Every agent must report:

- Branch name
- Commit SHA
- Pull request and target branch, when applicable
- Files changed
- Behavior changed
- Tests and checks run
- CI status
- Merge status
- Deployment status, if checked
- Migration, configuration, security, compatibility, and rollback considerations
- Anything not verified

## Stop conditions

Do not proceed without explicit authorization when a task would require production data loss, destructive schema changes, shared-history rewriting, disabling security controls, bypassing failing CI, changing live billing behavior, sending real bulk messages, exposing sensitive information, or deleting production infrastructure.

## Protected repository areas

Use heightened review for:

- FastAPI authentication and membership selection
- SQLAlchemy tenant-scoped queries
- Alembic migrations
- Student, teacher, parent, tenant-admin, and superadmin identity flows
- Redis keys and invalidation
- ARQ general and heavy workers
- Bulk student import and parent invitation flows
- Paystack payments and webhooks
- Email provider routing
- Calendar, attendance, results, enrollment, and promotion lifecycles
- React authentication and API client behavior
- Mobile browser and PWA shell behavior
- Vercel and Railway configuration

Protect correctness, user data, tenant isolation, security, and production stability over speed. Prefer a narrow, verified change over a broad or clever one.
