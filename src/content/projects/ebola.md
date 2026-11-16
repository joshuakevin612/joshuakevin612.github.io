---
title: Ebola Outbreak Prediction
summary: "Scores patient Ebola risk with a Random Forest and forecasts outbreak cases with ARIMA and LSTM."
year: 2026
role: "Solo developer"
stack: ["Python", "scikit-learn", "statsmodels", "TensorFlow", "Streamlit", "React", "Vite", "pandas"]
cover: ./ebola-hero.webp
shot: ./ebola.webp
repo: "https://github.com/joshuakevin612/ebola-outbreak-prediction"
order: 11
---

Ebola Outbreak Prediction is a research prototype with two workspaces: a patient risk score and a case forecaster. It is not a clinical or public-health tool.

## The problem

Ebola response depends on two questions. Which patients look high risk, and where are case counts heading? Each is usually answered with separate tools, and neither is easy to inspect or compare.

## The approach

The patient model is a scikit-learn Random Forest pipeline trained on a 10,000-row balanced dataset. The interface takes symptoms, exposure history, profile and vitals, and returns a model score.

Forecasting covers the 2014 to 2016 West Africa outbreak and the 2018 to 2020 North Kivu and Ituri outbreak. Each series is split chronologically, so models are tested on later data than they train on. A moving-average baseline sits beside ARIMA, so a model has to beat a simple guess. Single-series and pooled LSTMs are available when TensorFlow loads.

There are two interfaces. A React and Vite app serves both workspaces, with the Python code running behind the dev server over stdio. A Streamlit dashboard offers the forecasting side on its own.
