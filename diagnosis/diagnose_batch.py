"""Run diagnosis on all 500 records using the tuned config."""

import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from diagnosis.db import init_db
from diagnosis.rules import diagnose_all

CONFIG_PATH = Path(__file__).parent / "best_config.json"
OUTPUT_PATH = Path(__file__).parent / "diagnosis_results.json"


def run():
    config = json.loads(CONFIG_PATH.read_text())
    print(f"Config: {config}")

    conn = init_db()
    results = diagnose_all(conn, config)

    OUTPUT_PATH.write_text(json.dumps(results, indent=2))
    print(f"\nDiagnosed {len(results)} records → {OUTPUT_PATH}")

    causes = Counter(r["diagnosed_cause"] for r in results)
    print("\n── Diagnosis Summary ──")
    for cause in sorted(causes, key=causes.get, reverse=True):
        subset = [r for r in results if r["diagnosed_cause"] == cause]
        avg_conf = sum(r["confidence"] for r in subset) / len(subset)
        print(f"  {cause:25s} {causes[cause]:4d}  (avg confidence: {avg_conf:.2f})")

    conn.close()
    return results


if __name__ == "__main__":
    run()
