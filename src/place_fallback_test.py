"""
Place-fallback test (hand-written Cypher, no model).

Needs two plain-text files, one name per line, written BEFORE you look at any results:
  eval/place_names_real.txt      10 road or landmark names taken from events that have no Area
  eval/place_names_invented.txt  5 invented names

    python src/place_fallback_test.py

Runs the fallback query from rule 6 (location OR summary_clean CONTAINS, up to 5 events per name)
through the validator and the read-only executor. For each returned event it shows the text and asks
whether the text names the place as where the incident happened (y/n). Judgments are saved to
results/place_fallback.json (names, event ids and 0/1 only, no GTD text).

Pass: at least 80% of returned events correct AND at least 40 events returned;
      every invented name returns no rows. If it fails, names in neither list are refused.
"""
import json
import os

import qa_core
import validator
from config import get_driver

QUERY = ("MATCH (e:Event) "
         "WHERE toLower(e.location) CONTAINS toLower('{n}') "
         "OR toLower(e.summary_clean) CONTAINS toLower('{n}') "
         "RETURN e.eventid AS _ref, e.date AS date, e.location AS location, "
         "e.summary_clean AS summary, '{n}' AS place_match LIMIT 5")


def read_names(path):
    with open(path, encoding="utf-8") as f:
        return [ln.strip() for ln in f if ln.strip()]


def run_name(driver, names, name):
    if "'" in name or '"' in name or "\\" in name:
        raise SystemExit(f"remove quotes and backslashes from the name: {name}")
    chk = validator.validate_cypher(QUERY.format(n=name), 0, names)
    if not chk.ok:
        raise SystemExit(f"validator rejected '{name}': {chk.problems}")
    keys, rows = qa_core.execute_readonly(driver, chk.query)
    return [dict(zip(keys, r)) for r in rows]


def main():
    real = read_names("eval/place_names_real.txt")
    fake = read_names("eval/place_names_invented.txt")
    if len(real) != 10 or len(fake) != 5:
        raise SystemExit(f"expected 10 real and 5 invented names, got {len(real)} and {len(fake)}")
    driver = get_driver()
    names = qa_core.load_names(driver)

    judgments, total, correct = [], 0, 0
    for name in real:
        rows = run_name(driver, names, name)
        print(f"\n=== {name}: {len(rows)} event(s) ===")
        for r in rows:
            print(f"\n  {r['date']} | {r['location']}\n  {r['summary']}")
            ans = ""
            while ans not in ("y", "n"):
                ans = input("  event text names this place as where it happened? (y/n): ").strip().lower()
            judgments.append({"name": name, "eventid": r["_ref"], "correct": int(ans == "y")})
            total += 1
            correct += ans == "y"

    invented = {n: len(run_name(driver, names, n)) for n in fake}
    driver.close()

    share = correct / total if total else 0.0
    fake_ok = all(c == 0 for c in invented.values())
    passed = share >= 0.80 and total >= 40 and fake_ok
    print("\n--- result ---")
    print(f"events returned: {total} (need >= 40)")
    print(f"judged correct:  {correct}/{total} = {share:.3f} (need >= 0.80)")
    print(f"invented names returning rows: {invented} (all must be 0)")
    print("PASS: keep the fallback" if passed else "FAIL: names in neither list are refused")

    os.makedirs("results", exist_ok=True)
    with open("results/place_fallback.json", "w", encoding="utf-8") as f:
        json.dump({"real": real, "invented": invented, "events": total, "correct": correct,
                   "passed": passed, "judgments": judgments}, f, indent=2)


if __name__ == "__main__":
    main()
    