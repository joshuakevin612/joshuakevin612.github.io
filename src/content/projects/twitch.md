---
title: Clipfarm
summary: "Turns the fastest-growing Twitch clips into captioned vertical YouTube Shorts, automatically."
year: 2026
role: "Solo developer"
stack: ["Python", "faster-whisper", "Ollama", "ffmpeg", "OpenCV", "Twitch API", "YouTube Data API", "SQLite"]
cover: ./twitch-hero.webp
repo: "https://github.com/joshuakevin612/clipfarm"
order: 5
---

Clipfarm is a hands-off pipeline that finds the clips taking off on Twitch and republishes them as captioned 9:16 Shorts, with no editing in between.

## The problem

Good clips have a short shelf life. Finding them, cutting them to vertical, captioning them and uploading them by hand takes longer than the window in which they are worth posting.

## The approach

Every four hours a scheduled job pulls the top recent clips for a configured list of streamers. Each clip is downloaded and transcribed with Whisper, then a local language model running in Ollama scores it and writes a hook and a title. Clips that score low or have too little speech are dropped.

The ones that pass are rendered vertically, with the facecam stacked over gameplay or the gameplay set on a blurred background, and captions burned in. They are uploaded to YouTube and recorded in SQLite so nothing is ever posted twice. A dry-run mode shows what would be posted without publishing anything.
