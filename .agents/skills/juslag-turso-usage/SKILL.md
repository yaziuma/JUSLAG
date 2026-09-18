---
name: juslag-turso-usage
description: Review JUSLAG Turso storage or viewer changes for query cost, sync usage, cache behavior, and usage alerts. Use when designing or changing Turso queries, sync, or public read paths; not for strategy modeling or unrelated SQLite work.
---

# JUSLAG Turso Usage Review

Apply this skill when a JUSLAG change adds or modifies a Turso-backed read, synchronization job, or public viewer path. Follow the [integrated roadmap](../../../docs/implementation_roadmap_20260918.md); this review does not authorize Cloud provisioning, deployment, paid upgrades, or live trading.

## Review the actual workload

1. Identify which calls reach Turso Cloud and which use a local database. Count calls per page load, scheduled run, retry, and sync cycle. A local query is not automatically a Cloud rows-read charge; verify the selected SDK and product's billing semantics rather than assuming either way.
2. For frequent or potentially unbounded SQL, inspect `EXPLAIN QUERY PLAN` against representative data volumes and verify the relevant index paths. `LIMIT` on a query with `JOIN`, `DISTINCT`, or `ORDER BY` does not by itself prove that little data is scanned. Flag full scans, repeated nested scans, temporary sort B-trees, and `ORDER BY RANDOM()` where growth could matter. Compare plausible indexed alternatives with measured results; do not mandate a particular rewrite.
3. Measure Cloud-side usage for representative requests and expected daily frequency: rows read/written, bytes synced, request count, and latency as exposed by the current plan and tooling. Include failed requests, retry loops, initial bootstrap, cache misses, and a growth scenario. Do not infer billed rows from returned row count or DB size alone.
4. For a public or externally reachable path, trace whether unauthenticated traffic can trigger database work. Review authentication, rate limiting, and caching at the actual hosting layer. Do not transplant Next.js `force-dynamic`/ISR settings or a User-Agent blocklist into JUSLAG unless that stack and threat model actually apply. Browser-visible credentials are not protected by StatiCrypt alone.
5. Establish a usage budget and early alert from the account's current quota and overage settings. Check the current official pricing/API at implementation time; never hard-code a historical free-tier allowance. Define who receives an alert and how to disable or degrade the Turso read path without stopping daily research. Account for delayed usage reporting when validating an alert.

## Evidence and decision

Record the query or sync path, test data size, query plan, measured usage, expected invocation rate, cache freshness rule, budget/alert threshold, and rollback switch. If Cloud usage cannot be observed, the plan cannot be confirmed cost-safe; keep the existing file/Pages route active until measured.

The [Zenn incident](https://zenn.dev/tukiyubi/articles/9608da84dbb7a5) is a motivating case, not a universal Turso benchmark: a public Next.js/Cloudflare site combined expensive queries, disabled caching, and bot traffic. For mechanics and current limits consult [SQLite EXPLAIN QUERY PLAN](https://www.sqlite.org/eqp.html), [Turso pricing](https://turso.tech/pricing), and the [Turso Cloud documentation](https://docs.turso.tech/).
