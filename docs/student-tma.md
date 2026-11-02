# Student Tutor Marked Assignments

The subject detail page discovers eligible assignments using the live student listing.
It matches both the curriculum subject and academic term, and offers Start TMA,
Continue TMA, or View TMA result according to the server's attempt status.
Availability refreshes on entry, focus, visibility changes and every 30 seconds
while visible.

The start screen centers its action within the remaining dashboard content area.
It keeps the short introduction above the button and puts detailed guidance in
an optional guide dialog below. The existing dashboard shell, mobile drawer and
five-button bottom navigation retain their existing geometry. When an attempt
starts or resumes, a student-only event uses the existing collapse/close state
to minimize the desktop sidebar and close an open mobile drawer, as requested.
The quiz omits the duplicate subject page header.

Starting is an explicit action. Existing attempts resume through their server ID,
restoring saved selections by question and option IDs without changing the
backend's stable shuffled order. Each question has a single-choice response,
math rendering, optional signed images, previous/next controls and a question
navigator. Leave and Submit TMA sit beneath the question grid; Submit TMA is
shown only at the last question. The confirmation uses
plain unanswered-count text without a colored warning strip.

The quiz uses a solid theme-colored subject header with an integrated progress
meter above one bordered question panel. Answer choices use native radio controls, and Previous/Next sit
outside the panel. The desktop picker can collapse without hiding the question;
the card remains centered at a readable width and the picker stays on the right.
On mobile, a raised floating Questions launcher opens the same navigator from the right,
replacing the bottom grid. The launcher uses existing dock clearance. Choosing
a number closes the panel and focuses the question. Review & submit and Submit
TMA share the same confirmation action. Question states need no color legend. Quiz and picker
headers use the existing theme color, with compact answer rows in one card.

Answers are saved immediately through a serial, coalescing queue. A slow earlier
request cannot finish after a newer save and overwrite it. Failed choices remain
pending in memory with a retry action. They are never reported as saved until the
server acknowledges them. Saving and failure feedback appears only when needed;
there is no persistent success label. Leave and submission flush the queue first;
internal links wait for pending saves, and closing/reloading warns while answers
remain unsaved. Browser history navigation can leave the page; already queued
writes continue, but only acknowledged answers are guaranteed on return.
An offline reload cannot recover unsaved choices. No student answers, attempts,
results or signed image URLs are persisted in browser caches or Redis.

Submission requires confirmation, identifies unanswered questions, and uses the
existing backend grading endpoint. Answers lock once submission begins. If the
response is uncertain, retrying submission checks the same idempotent attempt.
The UI displays the returned score without calculating a grade or requesting
staff question data. The dashboard snapshot is invalidated after submission.

The student assignment response now includes an optional attempt_id for the
current student's matching revision. This is an additive API change without a
migration. Deploy the backend before or alongside the frontend for direct resume
and result reopening. An older backend can still start/resume explicitly, but
cannot reopen submitted results from the listing without that ID.

Student APIs used: assignment listing and start, attempt resume, answer PUT,
submit, result GET, and attempt-authorized signed image URLs. Tenant, student,
eligibility, assignment state and single-attempt enforcement remain in the
existing backend services. Pausing does not require an API or timer: the attempt
remains in progress until submission. Students can resume only while the
assignment and current term remain open. The closing estimate is informational.

Validation includes focused frontend state/presentation regressions, existing
student subject tests, TMA backend unit tests, lint, frontend/backend contracts and
a production build. Browser component review used synthetic data at desktop and
390px mobile width. Authenticated API/browser acceptance and real iOS/Android
device testing remain unverified; no real answers or grades were created for QA.

Rollback the student frontend and the additive response field independently; no
student records are deleted and no grading policy or deployment settings change.
