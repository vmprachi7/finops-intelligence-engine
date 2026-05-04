#!/bin/bash
# ── Run this from the ROOT of the repo ───────────────────────
# cd finops-intelligence-engine
# bash run.sh

# Ensure Python can find the app/ module
export PYTHONPATH="${PYTHONPATH}:$(pwd)"

streamlit run app/main.py