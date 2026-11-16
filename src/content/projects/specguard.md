---
title: SpecGuard
summary: "Checks Python functions against written requirements with generated tests and retested fixes."
year: 2026
role: "Team lead: backend, frontend animation and polish"
stack: ["Python", "FastAPI", "React", "TypeScript", "SQLite", "Docker", "Tailwind CSS"]
cover: ./specguard-hero.webp
shot: ./specguard.webp
repo: "https://github.com/joshuakevin612/SpecGuard"
order: 6
---

SpecGuard checks whether a Python function does what its written requirements say. It turns the spec into tests, runs them, and reports where the code falls short.

## The problem

A function can pass the tests its author thought of and still miss the requirement. Writing tests from a spec is slow, and ambiguous wording often goes unnoticed until something breaks.

## The approach

A FastAPI backend runs a verification pipeline. It parses the spec, plans test cases, generates tests with a language model and validates them before running. The model provider is swappable. A mock provider with bundled demos works without any API keys, and NVIDIA or Nebius endpoints handle arbitrary specs. Results land in SQLite, and the React frontend shows the report, a proposed fix and a button to retest the original tests against it.

Untrusted code is the main risk. The runner can execute locally for trusted code, or inside a Docker image for isolation. The README says public hosting would need a separate worker under gVisor. It also states the limits plainly: generated tests are finite evidence, not proof, and only synchronous top-level functions with JSON inputs and outputs are supported.
