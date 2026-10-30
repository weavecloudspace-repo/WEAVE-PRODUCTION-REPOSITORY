# CBT AI: Qwen-only visual generation (feature branch)

## Request contract

The existing `POST /ai/questions/generate` endpoint remains backward-compatible:
it waits for completion and returns **one entire batch**, never a partial list.

New preferred async endpoints (authenticated tenant teacher/admin):

1. `POST /ai/questions/generate/jobs` with the existing
   `AIGenerateQuestionsRequest` JSON and a stable `Idempotency-Key` header.
   Returns HTTP **202** and `{job_id, status: "queued", result_available: false}`.
2. `GET /ai/questions/jobs/{job_id}` returns stage/status, **no question data**.
3. `GET /ai/questions/jobs/{job_id}/result` returns the same
   `AIGenerateQuestionsResponse` as the legacy endpoint, once COMPLETE.
   Before completion it returns a retryable conflict, not partial questions.

**Frontend integration**: On the CBT teacher/admin authoring screen, POST once,
store the job ID, poll the status endpoint until completed/failed, then GET
the completed result and display all questions together. Preserve the job ID
across page refreshes; never generate a fresh Idempotency-Key on a retry.

The existing CBTAI actor scope (tenant_id + actor_type + actor_id) restricts
job-status and result access. The durable idempotency record protects duplicate
charges; the Redis replay retains a completed response for 24 hours.

## Models and boundaries

- Questions: configured GPT-OSS 120b OpenRouter text model.
- **Text only**: 100% text, no image model calls.
- **Allow images**: 60% text-only / 40% image-bearing (e.g., 9+6 for 15).
- Images: `qwen/qwen-image-2.1-turbo` on `POST /api/v1/images`, ONLY.
- `provider.allow_fallbacks=false` disables OpenRouter's provider failover.
- DDGS web tools may retrieve **text facts** when explicitly enabled
  (`WEB_RESEARCH_ENABLED`); DDGS image retrieval is never invoked.
- No contact sheets, web-image downloads, or Qwen Vision validation.
- The examination prompt is assembled server-side and prohibits revealing
  correct answers as embedded text, but this is **not a guarantee**.
  A teacher must review all questions and images before publishing.
- Generated PNG/JPEG/WebP assets undergo binary validation/normalization,
  then the existing 24 MiB batch budget and GZip response path.

## Rate limits, concurrency, errors

OpenRouter image requests use two independent Redis controls:

- `OPENROUTER_IMAGE_MAX_CONCURRENT=2` global in-flight reservations
  (leases expire after the HTTP timeout + 60 seconds).
- `OPENROUTER_IMAGE_MIN_INTERVAL_SECONDS=5` start-rate pacing per
  API-key/model across workers and tenants.
- `OPENROUTER_IMAGE_MAX_QUEUE_WAIT_SECONDS=180` bounds queue waiting.
- `OPENROUTER_429_MAX_RETRIES=2` and
  `OPENROUTER_429_MAX_BACKOFF_SECONDS=15` limit same-model 429 retries,
  with `Retry-After` honored when practical; exhausted quotas fail fast.

If one image fails or the final batch violates the visual policy,
the whole request fails. No different image model or DDGS fallback is tried.
Failed batches do not settle teacher credits; OpenRouter may nonetheless bill
for individual successful image calls before another image fails.

## Deployment

**Required new service**: run a dedicated ARQ worker with

```bash
arq app.core.queue.ai_worker.WorkerSettings
```

Configure it with the same `DATABASE_URL`, `REDIS_URL`,
`OPENROUTER_API_KEY`, and relevant settings as the FastAPI service.
The worker calls `connect_redis()` on startup and refuses production work
without runtime Redis.

Do NOT use the heavy school academic queue for AI generation.
Do NOT direct CBT clients to the async endpoints until the new worker is live.
For now the legacy synchronous endpoint remains available.

**Operational follow-up**: add alerts for stuck jobs and track image generation
latency and provider 429s. The worker's `job_timeout` is 1200s and
`max_tries=1` to avoid automatic duplicate billable image generation.
The API cannot recover a job permanently lost after dequeue without a
separate recovery action; manual reconciliation or a watchdog is required.
