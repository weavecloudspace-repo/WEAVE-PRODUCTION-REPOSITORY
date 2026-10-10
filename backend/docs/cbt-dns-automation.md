# CBT DNS-01 cloud integration

WEAVE Cloud owns DNS-01 TXT creation, tracking and cleanup. The CBT node owns its
ACME account, certificate private keys, certificate installation, and the ACME
renewal scheduler; this repository does not obtain certificates for the node.

## Stable hostname

A pairing response adds `hostname` using:

`<ascii-server-name>-<server-id-12>.school-<tenant-uuid-32>.<cbt|cbt-staging>.weavecloudspace.com`

The hostname prefix is persisted at pairing, and historical servers are
backfilled in the Alembic migration. The school UUID is immutable; two schools
can share a server name. Revoking and re-pairing creates a new server identity
and therefore a new hostname. Never resolve these names publicly to a private
school LAN IP. Local networks must resolve the FQDN to the server's LAN IP.

## Configuration and secret handling

Bunny DNS must already manage the `weavecloudspace.com` zone. Set:

- `BUNNY_DNS_ZONE_ID`: numeric Bunny zone ID for `weavecloudspace.com`.
- `BUNNY_DNS_API_KEY`: rotated secret held only in cloud API + general worker.
- `ENV`: staging emits `cbt-staging`; production emits `cbt`.

Missing credentials fail closed with HTTP 503 on challenge creation. Never put
the Bunny key on the CBT node, in source, in CI, or in chat. Both environments
access the same parent Bunny zone; application hostname allowlisting provides
isolation, but **does not constitute DNS-provider credential isolation**.

## Machine-authenticated API

Bearer credential issued during pairing is required. POST
`/api/v1/cbt/certificates/dns-challenges` takes:

```json
{"request_id":"<UUID>","value":"<43-character-base64url-DNS01-digest>"}
```

The FQDN is derived exclusively from the paired machine's persisted hostname.
The response contains a challenge ID and `_acme-challenge` FQDN, not the Bunny
API key. GET the returned ID for provider-created/expired/removed state; it is
**not** an authoritative public-DNS propagation check. DELETE the ID after
issuance. Retrying the same request ID with the same digest is idempotent.
Different values with the same ID fail with 409.

Records expire after 20 minutes; the existing general ARQ worker sweeps
expired records approximately every 10 minutes. Provider failures leave
challenge records to be retried on a later sweep. No automatic issuance occurs
without the CBT-side implementation and LAN DNS.

## Deployment safeguards

- Rotate any key previously shared in chat before configuring Railway.
- Verify the correct zone ID before enabling either environment.
- Run Alembic migrations before the new code starts.
- Run a live staging record creation, public DNS TXT lookup, deletion, and
  negative authorization tests before production rollout.
- Merge to master only after required checks and live staging validation pass.
