"""Compatibility entry point: grade recorded pre-match club tips locally.

Legacy records can be supplied with --logs. Late or unidentified snapshots
are excluded explicitly; they are never treated as pre-match predictions.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.audit_club_bets import main

if __name__ == "__main__":
    main()
