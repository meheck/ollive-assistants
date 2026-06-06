---
title: Ollive OSS Assistant
emoji: 🤖
colorFrom: blue
colorTo: indigo
sdk: gradio
sdk_version: 6.16.0
app_file: app.py
pinned: false
license: apache-2.0
short_description: Open-source assistant (Qwen2.5-1.5B) on CPU
---

# Ollive — Open-Source Assistant

A lightweight multi-turn personal assistant running the open-source
**Qwen2.5-1.5B-Instruct** model on CPU, with short-term conversational memory.

This Space is the public deployment of the open-source assistant from the
[Ollive take-home project](https://github.com/). The same assistant code also
powers a local app and an OSS-vs-frontier evaluation harness in the main repo.

- **Model:** `Qwen/Qwen2.5-1.5B-Instruct`
- **Hardware:** CPU (free tier) — the model is small enough to serve without a GPU
- **Memory:** sliding-window short-term context (per session)
