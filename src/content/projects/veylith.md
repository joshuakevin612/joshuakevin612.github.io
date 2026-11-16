---
title: Veylith
summary: "A security scanner for GitHub repos, built around a typed scanner contract. Early scaffold stage."
year: 2026
role: "Team lead, in progress"
stack: ["Python", "FastAPI", "Next.js", "TypeScript", "PostgreSQL", "SQLAlchemy", "Docker"]
cover: ./veylith-hero.webp
shot: ./veylith.webp
repo: "https://github.com/joshuakevin612/Veylith"
order: 13
---

Veylith is a planned continuous security scanner for GitHub repositories. A user signs in with GitHub, picks repositories, and each push is meant to be scanned for leaked secrets, vulnerable dependencies and insecure code patterns. The repo is an early scaffold, not a working product.

## The problem

Small teams rarely run security checks on every push. Existing scanners are heavy to set up, and results are scattered across tools.

## The approach

The plan is a Next.js dashboard and a FastAPI backend, with Postgres as both database and job queue. Workers would claim scans with `SELECT ... FOR UPDATE SKIP LOCKED`, so no Redis is needed. Code would be fetched as a tarball at the exact commit SHA, with no clone.

The scanners are written from scratch. OSV.dev serves only as the vulnerability database. They sit behind one typed contract. Each returns findings with a rule, severity, file, line, redacted snippet and a stable fingerprint, so the same problem is recognised across scans.

What exists today: the project layout, the scanner contract, a health endpoint, OpenAPI-generated TypeScript types, Alembic setup, tests and CI. The scanners themselves are not built yet.
