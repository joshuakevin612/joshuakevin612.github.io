---
title: Clyra
summary: "Medication continuity and handover records with audit trails, on synthetic data only."
year: 2026
role: "Team lead: backend, auth, integration, frontend animation and polish"
stack: ["Python", "FastAPI", "PostgreSQL", "Alembic", "React", "TypeScript", "Vite", "Playwright"]
cover: ./clyra-hero.webp
shot: ./clyra.webp
repo: "https://github.com/joshuakevin612/Clyra"
order: 2
---

Clyra is a research prototype for medication continuity and safe handover between care teams. It is not a clinical tool, and every record in it is synthetic.

## The problem

When a patient moves between teams, medication details get lost or altered. A handover needs a record that cannot be quietly rewritten and shows who saw what.

## The approach

The backend is FastAPI on PostgreSQL, with Alembic migrations. Several rules are enforced in the database itself. Logs are append-only, medication content is immutable once written, and the runtime connects through a restricted role. Passwords use argon2id.

A telemetry module ingests batched observations idempotently. It flags missing, spiking, repeated, delayed and conflicting readings. Then it produces a plain-text handover summary with the reasoning for each flag. A separate evidence-import contract (EI-1.0) is also documented in the repo.

The React and TypeScript frontend is checked with Vitest and Playwright, using mocked APIs. The changelog records 70 backend tests, 31 frontend tests and 11 browser checks passing. Nothing is deployed yet.
