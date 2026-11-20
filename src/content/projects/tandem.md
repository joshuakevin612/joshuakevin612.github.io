---
title: Tandem
summary: "A distributed job queue on Postgres that never loses an accepted job, proven by killing workers mid-run."
year: 2026
role: "Solo developer"
stack: ["Go", "PostgreSQL", "Redis", "Docker", "nginx", "Prometheus", "Grafana", "k6"]
cover: ./tandem-hero.webp
shot: ./tandem.webp
repo: "https://github.com/joshuakevin612/Tandem"
order: 14
---

Tandem is a small Celery. Clients submit jobs over HTTP, workers lease and run them from a Postgres-backed queue, and a scheduler reclaims the jobs of dead workers and fires cron schedules.

## The problem

A job queue is only useful if an accepted job is never silently dropped. Workers crash, networks stall, and two schedulers can both think they are in charge. The hard part is staying correct through all of that, not the happy path.

## The approach

The promise is at-least-once execution: once the API returns 202, the job is never lost or left stuck, even if a worker is killed mid-job. Exactly-once is explicitly not claimed. Duplicates are made safe instead, with lease fencing, so a worker that lost its lease cannot write a result, and idempotency keys, so a replayed submit returns the original job.

Every state transition is a single SQL statement, so the invariants live in Postgres rather than in application code. Workers lease jobs with `FOR UPDATE SKIP LOCKED` and heartbeat their leases. A reaper requeues the jobs of dead workers, failures retry with jittered backoff before landing in a dead-letter state, and cron schedules fire once even with two schedulers running. Redis adds a rate limit, a status cache and wake-ups, and the system keeps working without it.

## Proof

A chaos test runs against a real compose stack, SIGKILLing workers and schedulers while jobs flow, then checks eight invariants directly in the database. The repo documents one 10,000-job run where all eight passed, with the duplicate executions counted rather than hidden. Load tests and the dequeue query plan are recorded with their limits: one laptop, short runs, sanity numbers rather than capacity claims.

The web console, embedded in the Go binary, shows live job counts and states, the dead-letter queue and schedules.
