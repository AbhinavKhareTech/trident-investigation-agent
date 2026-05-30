"""Allow running as: python -m investigation_agent"""
import sys
from pathlib import Path

# Ensure src/ is importable regardless of install method
_src = str(Path(__file__).resolve().parents[1])
if _src not in sys.path:
    sys.path.insert(0, _src)

from investigation_agent.orchestrator import main

if __name__ == "__main__":
    main()
