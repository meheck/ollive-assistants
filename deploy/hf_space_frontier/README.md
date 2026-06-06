---
title: Ollive Frontier Assistant
emoji: ✨
colorFrom: indigo
colorTo: purple
sdk: gradio
sdk_version: 6.16.0
app_file: app.py
pinned: false
short_description: Frontier assistant (Gemini 2.5 Flash)
---

# Ollive — Frontier Assistant

A multi-turn personal assistant backed by a hosted frontier model
(**Google Gemini 2.5 Flash**), with short-term conversational memory.

Counterpart to the open-source assistant Space; both share the same assistant
interface and system prompt so they can be compared head-to-head in the eval
harness.

- **Model:** `gemini-2.5-flash` (hosted API)
- **Key:** read from the `GEMINI_API_KEY` Space Secret (never committed)
- **Memory:** sliding-window short-term context (per session)

> This Space is private: it uses the owner's Gemini key, so usage is restricted
> to the owner.
