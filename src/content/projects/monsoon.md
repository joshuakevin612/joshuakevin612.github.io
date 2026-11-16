---
title: Monsoon
summary: "A weather analytics dashboard for 30 Indian cities, with trends, anomaly flags and reviewed citizen reports."
year: 2026
role: "Solo developer"
stack: ["Python", "FastAPI", "PostgreSQL", "SQLAlchemy", "pandas", "React", "GSAP"]
cover: ./monsoon-hero.webp
shot: ./monsoon.webp
repo: "https://github.com/joshuakevin612/weather_bda"
order: 8
---

Monsoon is a weather big-data dashboard. It shows observations and trends, compares locations, and lets the public submit weather reports that staff review.

## The problem

Raw weather feeds are model output, not ground truth, and they say little about what is happening on the street. Reports from people nearby are useful but need checking before anyone trusts them.

## The approach

A FastAPI service keeps data in PostgreSQL through SQLAlchemy, with Alembic migrations. A separate worker collects Open-Meteo readings every 15 minutes for 30 seeded cities. Staff tools cover ingestion and moderation, and the API uses JWT auth with Argon2 password hashing and rate limiting.

Analytics use pandas and numpy. Anomaly detection scores readings with a modified z-score against a baseline window, and it reports insufficient data rather than guess when history is thin. Each kind of data carries its own trust label: model-derived weather, reviewed citizen reports, news and statistical flags.

The dashboard is plain JavaScript modules with React and GSAP animation components, served by a small Node server.
