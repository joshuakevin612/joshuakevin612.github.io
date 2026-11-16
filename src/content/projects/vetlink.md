---
title: VetLink
summary: "A QR pet tag that opens an emergency card with allergies and a call button for the owner."
year: 2026
role: "Team lead"
stack: ["HTML", "CSS", "JavaScript", "Firebase"]
cover: ./vetlink-hero.webp
shot: ./vetlink.webp
live: "https://joshuakevin612.github.io/VetLink/"
repo: "https://github.com/joshuakevin612/VetLink"
order: 12
---

VetLink is a smart pet tag system. A QR code on the tag opens an emergency card in any phone browser, so a finder can see key health details and call the owner without installing an app.

## The problem

A name and a phone number on a tag tell a finder very little. Allergies, medications and medical conditions are not visible, and a vet or shelter may need them quickly.

## The approach

Owners sign in with email and password, then register each pet on a dashboard. The full record stays in the owner's account. A separate public record holds only the emergency card: name, allergies, medications, conditions and the emergency contact number.

The QR code points to a profile page for that pet. The page loads the public card and shows a call button for the contact. Each scan is logged, and owners can review scans and mark a pet as lost.

The site is plain HTML, CSS and JavaScript with Firebase modules loaded from a CDN, so there is no build step.
