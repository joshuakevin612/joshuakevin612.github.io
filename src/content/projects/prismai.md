---
title: Prism
summary: "A local developer assistant that diagnoses issues with NVIDIA Nemotron and proposes patches to approve."
year: 2026
role: "Team lead"
stack: ["Python", "FastAPI", "React", "TypeScript", "GSAP", "Docker", "Vite"]
cover: ./prismai-hero.webp
shot: ./prismai.webp
repo: "https://github.com/joshuakevin612/PrismAi"
order: 7
---

Prism is a developer assistant that runs on your own machine. It gathers context from the workspace, diagnoses a problem with NVIDIA Nemotron, and proposes exact patches and Docker commands.

## The problem

Assistants that act on a codebase need a lot of access, and that is hard to trust. Pasting context by hand is tedious, but handing a model free rein over files and commands is risky.

## The approach

A local FastAPI backend collects context from files, the terminal, running processes, the screen and attached GitHub pull requests. It selects what is relevant within a budget and redacts the text before it goes to the model. Screenshots stay local.

Nothing runs without approval. Every proposed action needs a sign-off, and file edits, dependency installs and command networking ask first by default. Credentials and known sensitive paths cannot be collected or patched. Approved commands run in a Docker sandbox, not on the host.

The React interface is served from the same origin as the API, and the backend is paired to the browser through a private link. The repository includes regression tests, a secrets check and CI workflows.
