#!/bin/bash
# Wrapper for launchd — activates venv cleanly before running
cd /Users/ryanjenkinson/Desktop/compliance-monitor
source .venv/bin/activate
python3 run.py >> logs/run.log 2>&1
