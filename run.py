#!/usr/bin/env python3
"""Run the Trident Investigation Agent.

Usage:
    python run.py
    python run.py --data ./my_csvs/
    python run.py --n-normal 500 --ring-size 12
"""
import sys
from pathlib import Path

# Ensure src/ is on the path regardless of install method
sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from investigation_agent.orchestrator import main

if __name__ == "__main__":
    main()
