"""Compatibility entry point for append-only club snapshots and results."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.log_club_bets import main

if __name__ == "__main__":
    main()
