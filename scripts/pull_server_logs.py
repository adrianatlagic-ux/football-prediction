"""Fetch the server's bet and combo logs and merge them into the repository.

    python3 scripts/pull_server_logs.py --api https://football-prediction.fly.dev

The server logs every match itself, on time (src/scheduler.py); its disk is
lost on a redeploy, so GitHub fetches the logs whenever it runs and commits
them. Merging keeps every entry either side has: a match or ticket already
in the repository stays as it is, except that a logged "no tip" takes a
price tip logged later (the same rule as scripts/log_bets.py).
"""
import argparse
import json
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import log_bets  # noqa: E402
import log_combos  # noqa: E402


def fetch(api, name):
    with urllib.request.urlopen(f"{api}/logs/{name}", timeout=60) as r:
        return [json.loads(line) for line in r.read().decode("utf-8").splitlines() if line.strip()]


def merge_bets(repo, server):
    by_key = {log_bets._fixture_key(e): e for e in repo}
    added = 0
    for e in server:
        key = log_bets._fixture_key(e)
        old = by_key.get(key)
        if old is None:
            repo.append(e)
            by_key[key] = e
            added += 1
        elif log_bets._price_tip_upgrade(old.get("price_tip"), e.get("price_tip")):
            old["price_tip"] = e["price_tip"]
    return added


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api", default=log_bets.DEFAULT_API)
    args = parser.parse_args()

    repo_bets = log_bets._load_log()
    added = merge_bets(repo_bets, fetch(args.api, "bet_log"))
    log_bets.write_log(repo_bets)

    path = log_combos.LOG_PATH
    repo_combos = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
                   if line.strip()] if path.exists() else []
    have = {log_combos._key(e) for e in repo_combos}
    new = [e for e in fetch(args.api, "combo_log") if log_combos._key(e) not in have]
    if new:
        with path.open("a", encoding="utf-8") as fh:
            for e in new:
                fh.write(json.dumps(e, ensure_ascii=False) + "\n")
    print(f"{added} Wett-Eintraege, {len(new)} Kombis vom Server uebernommen.")


if __name__ == "__main__":
    main()
