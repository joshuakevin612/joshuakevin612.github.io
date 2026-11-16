---
title: CodeRed-Z
summary: "Recommends ambulance-to-hospital assignments and checks capacity before dispatch, on synthetic data."
year: 2026
role: "Team lead, backend"
stack: ["Python", "FastAPI", "SQLAlchemy", "scikit-learn", "React", "WebSockets", "PostgreSQL"]
cover: ./codered-z-hero.webp
shot: ./codered-z.webp
repo: "https://github.com/joshuakevin612/CodeRed-Z"
order: 1
---

CodeRed-Z is an emergency-response coordination demo built for IBM Z Datathon 2026. It simulates incidents, recommends which ambulance should take which patient to which hospital, and streams every change to a live dashboard. All patients, hospitals and travel times are synthetic.

## The problem

Dispatchers choose a hospital under pressure. The nearest one may have no trauma or ICU capacity left, and two ambulances can be sent to the same last bed.

## The approach

A FastAPI backend holds the state. The optimizer handles patients by triage priority and keeps only hospitals with the right capability and remaining capacity. It scores them on travel time plus a congestion penalty, and explains each pick. Patients it cannot place are reported.

A recommendation reserves nothing. When a dispatcher confirms, the reservation service rechecks everything inside a transaction and is idempotent. On PostgreSQL it uses row locks to protect the last slot. The SQLite fallback for local demos does not give that guarantee.

A scikit-learn model forecasts hospital demand 15 minutes ahead, with a heuristic fallback. A React dashboard fetches snapshots, then follows a WebSocket feed. It compares results against a nearest-hospital baseline and includes scenarios such as a hospital outage.
