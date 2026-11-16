---
title: DevHub
summary: "Search GitHub users and repos, save favourites and compare two developers or repositories side by side."
year: 2026
role: "Solo developer"
stack: ["Next.js", "React", "TypeScript", "Prisma", "PostgreSQL", "Tailwind CSS", "Zod"]
cover: ./devhub-hero.webp
shot: ./devhub.webp
repo: "https://github.com/joshuakevin612/Devhub"
live: "https://devhub-rho-ashy.vercel.app/"
order: 4
---

DevHub is a full-stack analytics app for GitHub. It breaks down any user or repository into languages, stars, forks, issues and contributors, and lets signed-in users save and compare them.

## The problem

GitHub profiles show raw numbers but make comparison hard. Judging two developers or two repositories means opening both and reading them side by side by hand. The public API also allows only 60 unauthenticated requests an hour, which a naive client burns through fast.

## The approach

The frontend and backend live in one Next.js 14 app. Pages are React client components, and the API is a set of Route Handlers that the pages call with an httpOnly cookie. Auth is custom: bcrypt for passwords and signed JWTs through jose, with no session table. Zod validates input, and Prisma stores users, favourites and cached responses in PostgreSQL.

Every GitHub call goes through one caching proxy. Fresh entries are served from the database. Stale entries are revalidated with an ETag, so a 304 costs no quota. If GitHub is rate limited or failing, the proxy falls back to any cached copy instead of showing an error.
