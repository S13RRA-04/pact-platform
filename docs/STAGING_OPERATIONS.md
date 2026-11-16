# Staging operations

Run `docker compose -f docker-compose.staging.yml up -d --build` on the protected staging container host after creating `.env.staging` from `.env.example`. The file must contain the staging PostgreSQL URL, session secret, private R2 credentials, and ClamAV settings; never commit it.

Container health changes should alert through the staging platform. Alert when any container is unhealthy for two checks, when `/api/admin/worker-health` reports `degraded`, or when `max_release_lag_seconds` exceeds 120. Route alerts to the approved operations channel.

The scan worker writes uploads under the private `quarantine/` prefix, performs content disarm and ClamAV scanning, deletes the quarantine object after a clean result, and only then creates an approval request. Failed objects stay inaccessible and require an audited operator review.

The digest worker builds durable delivery records in `notification_digests`. This prototype records delivery in the outbox; connecting an email provider remains a separate backend integration and must respect user preferences.

The R2 workflow requires a GitHub `staging` environment with the four `PACT_R2_TEST_*` secrets. The bucket must be private, isolated from production, and credentials must be restricted to object read/write/delete for that bucket.
