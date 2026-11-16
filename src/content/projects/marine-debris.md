---
title: Marine Debris Detection
summary: "A YOLOv8 detector that finds trash and marine life in underwater footage, with an AI-written pollution report."
year: 2026
role: "Solo developer"
stack: ["Python", "YOLOv8", "Ultralytics", "Streamlit", "OpenCV", "Pillow", "Gemini API"]
cover: ./marine-debris-hero.webp
shot: ./marine-debris.webp
repo: "https://github.com/joshuakevin612/marine_debris_detection"
order: 10
---

Marine Debris Detection finds debris in underwater images and turns the results into a short report. A web app takes an image, draws the detections and summarises what was found.

## The problem

Ocean cleanup surveys produce hours of footage that someone has to review by hand. Counting and classifying each item is slow, and the results are hard to compare between dives.

## The approach

A YOLOv8 nano model was fine-tuned on the TrashCan dataset from Roboflow. It has 22 classes, covering types of trash such as bottles, nets and bags, as well as animals, plants and the ROV itself. Training ran for 50 epochs on a local GPU and reached a validation mAP50 of 0.90 in the run logs.

The Streamlit app loads the trained weights, runs detection on an uploaded image and shows the annotated result with a count per class. Those counts, not the pixels, go to Gemini, which writes the environmental report. Sending only counts keeps the prompt small and the output grounded in what the detector found.

Detection runs locally, and report calls retry with backoff when the free API tier is rate limited.
