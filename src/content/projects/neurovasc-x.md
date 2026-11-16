---
title: NeuroVasc-X
summary: "Fuses vitals, ECG and CT scores into one stroke-risk estimate, with explanations. A research prototype."
year: 2026
role: "Team lead"
stack: ["Python", "Streamlit", "PyTorch", "XGBoost", "scikit-learn", "FHIR"]
cover: ./neurovasc-x-hero.webp
shot: ./neurovasc-x.webp
repo: "https://github.com/joshuakevin612/Silent-Stroke-Detection"
order: 3
---

NeuroVasc-X is a research prototype that scores silent stroke risk from three inputs and shows the result on one dashboard. It is not a clinical tool.

## The problem

Silent strokes often go unnoticed. Warning signs are spread across vitals, heart rhythm and brain imaging, and each is usually read on its own.

## The approach

Each input has its own model. An XGBoost or random forest model scores tabular risk factors such as age, glucose and smoking status. A small 1D CNN reads ECG waveforms. A ResNet18 scores CT images. A fusion step combines the three scores into a composite risk and a tier.

Every model degrades gracefully. If weights or libraries are missing, the engine falls back to a labelled baseline, so the app still runs. Training scripts exist for each model, along with an evaluation script.

Two extras go beyond the score. An interpretability module gives per-feature contributions and Grad-CAM heatmaps. A FHIR exporter builds a standard Observation payload from a result. It sends nothing anywhere.
