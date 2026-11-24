# Storage audit — 2026-11-25

Baseline 625ccae1f142ec3931215d520a031bf33396d339. Changes on local isolated audit/1808-contract-v3-local only.

Implemented: PostgreSQL JSONB session adapter; hash-only token persistence; session restore; pgvector retrieval and keyword evidence threshold; Redis policy result cache with hashed key and 60-second TTL; dependency-aware health; async HTTP handlers run blocking adapter work in threadpool. Compose host port bound to loopback and configurable for isolated testing.

Verified with Python 3.11: 28/28 unittest tests, 6/6 mutation checks, original 340-case mock evaluation (.957 extraction, 1.000 policy, zero reported violations), compileall, compose config, diff check. Session restore was exercised with SQLite; pgvector/Redis unit coverage uses doubles. No claim of real PostgreSQL/Redis execution. The original eval does not exercise the new hybrid retrieval implementation. The new real-service verification script is written but not run.

Attempted `docker compose -p rider1808audit pull postgres redis`: exit 18; registry-1.docker.io HTTPS connection timeout; both images absent locally. No Compose containers started. Do not alter global daemon configuration or replace license-constrained dependencies to bypass the block without review.

Next: on a reachable registry, from this checkout use `AGENT_PORT=18077 docker compose -p rider1808audit up --build -d` and `python3 scripts/verify_storage_compose.py --project rider1808audit --port 18077`. This checks live DB rows, pgvector dimension, Redis key and app restart. Then rerun full eval through deployed API and fault injection.

Known blockers: single process lock only, multi-worker consistency and failure atomicity unverified; mock Vault is memory-only, restored tokens cannot be resolved after restart and sequential mock token collisions remain possible; original dialogue kept in memory, further privacy review needed; turn count not restored; outbox/HMAC and full OpenAPI still open. Health probes establish connectivity only. No production readiness or bid update authorized.
