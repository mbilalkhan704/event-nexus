"""
Adds 10 aggregation (AGG) questions to eval/dev.jsonl: counts, totals, group-by tables and top-1
rankings. Every gold query is validated and executed; tables have 1 to 49 rows, top-1 questions
have no tie at the cut. Safe to rerun (old AGG items are replaced).

    python src/make_dev_agg.py
    python src/filter_pairs.py --test eval/test_draft.jsonl     # rerun afterwards
"""
import json
import re
from collections import Counter

import qa_core
import validator
from config import get_driver
from gold import agg_by, agg_count, agg_killed, yr

DEV = "eval/dev.jsonl"
TTP = "Tehrik-i-Taliban Pakistan (TTP)"
driver = get_driver()
NAMES = qa_core.load_names(driver)


def y(n):
    d_from, d_to = yr(n)
    return {"d_from": d_from, "d_to": d_to}


# each entry: (topn, [(question, gold), ...]); the first candidate without a problem is used
SPECS = [
    (0, [("How many incidents were there in 2011?", agg_count(**y(2011)))]),
    (0, [("What is the total number of people killed in 2016?", agg_killed("sum", **y(2016)))]),
    (0, [("How many incidents are attributed to the TTP?", agg_count(group=TTP))]),
    (0, [("How many bombings happened in Lyari?", agg_count(area="Lyari", attack="Bombing/Explosion"))]),
    (0, [("How many incidents in 2012 have no known perpetrator?", agg_count(unattributed=True, **y(2012)))]),
    (0, [("How many incidents were there in each year from 2008 to 2012?",
          agg_by("year", d_from="2008-01-01", d_to="2012-12-31"))]),
    (0, [("Break down all incidents by attack type.", agg_by("attack_type", order="top"))]),
    (1, [(f"Which neighbourhood saw the most attacks in {n}?", agg_by("area", "top", 1, **y(n)))
         for n in (2014, 2010, 2016, 2012, 2018)]),
    (1, [(f"What was the most common weapon type in {a}?", agg_by("weapon_type", "top", 1, area=a))
         for a in ("North Karachi", "Orangi", "Landhi", "Malir")]),
    (1, [(f"Which group carried out the most attacks between {a} and {b}?",
          agg_by("group", "top", 1, d_from=f"{a}-01-01", d_to=f"{b}-12-31"))
         for a, b in ((2010, 2015), (2005, 2009), (2016, 2020))]),
]


def problem(gold, topn):
    chk = validator.validate_cypher(gold, 0, NAMES)
    if not chk.ok:
        raise SystemExit(f"GOLD FAILS THE VALIDATOR: {chk.problems}\n{gold}")
    keys, rows = qa_core.execute_readonly(driver, chk.query)
    if not rows:
        return "no rows"
    if topn:
        longer = re.sub(r"LIMIT\s+\d+\s*$", f"LIMIT {topn + 1}", chk.query)
        k2, r2 = qa_core.execute_readonly(driver, longer)
        i = k2.index("incidents")
        if len(r2) > topn and r2[topn - 1][i] == r2[topn][i]:
            return "tie at the cut"
        return None
    if len(rows) >= 50:
        return f"{len(rows)} rows reach the LIMIT"
    if len(rows) == 1 and len(keys) == 1 and rows[0][0] in (0, None):
        return "result is zero"
    return None


with open(DEV, encoding="utf-8") as f:
    items = [json.loads(line) for line in f if line.strip()]
items = [it for it in items if it["query_id"] != "AGG"]
next_id = max(int(it["id"][1:]) for it in items) + 1

new = []
for n, (topn, cands) in enumerate(SPECS, 1):
    last = "no candidates"
    for question, gold in cands:
        last = problem(gold, topn)
        if last is None:
            new.append({"id": f"d{next_id + len(new):03d}", "query_id": "AGG", "phrasing": n,
                        "question": question, "events": 0, "refs": {}, "expect": "cypher",
                        "gold": gold, "topn": topn or None})
            break
    else:
        raise SystemExit(f"AGG {n}: no valid candidate; last problem: {last}")

with open(DEV, "w", encoding="utf-8") as f:
    for it in items + new:
        f.write(json.dumps(it, ensure_ascii=False) + "\n")
driver.close()
print(f"added {len(new)} AGG items; dev now has {len(items) + len(new)}")
print("by expected output:", dict(Counter(it["expect"] for it in items + new)))
for it in new:
    print(it["id"], it["question"])