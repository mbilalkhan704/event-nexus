"""
Checks the test-set scorer: qa_core.same_list / same_single / strip_limit, then
run_eval.is_correct on every item in eval/test.jsonl (each gold must score correct against itself,
and simple wrong answers must score wrong). Needs the database.

    python src/test_scorer.py
"""
import json
import random
import sys
from types import SimpleNamespace

import qa_core
import run_eval
from config import get_driver

fails = []


def check(name, got, want=True):
    ok = got == want
    print("PASS" if ok else "FAIL", name)
    if not ok:
        fails.append(name)


# ---------- synthetic ----------
K = ["_ref", "date"]


def rows(ids):
    return [[i, "2010-01-01"] for i in ids]


F5, F80 = rows(range(1, 6)), rows(range(1, 81))
check("strip_limit", qa_core.strip_limit("MATCH (e) RETURN e\nLIMIT 50"), "MATCH (e) RETURN e")
check("list: same rows, other order", qa_core.same_list(K, rows([5, 4, 3, 2, 1]), K, F5, ["_ref"]))
check("list: one row missing", qa_core.same_list(K, rows([1, 2, 3, 4]), K, F5, ["_ref"]), False)
check("list: duplicate row", qa_core.same_list(K, rows([1, 2, 3, 4, 4]), K, F5, ["_ref"]), False)
check("list: row outside F", qa_core.same_list(K, rows([1, 2, 3, 4, 9]), K, F5, ["_ref"]), False)
check("list: extra column tolerated",
      qa_core.same_list(["x", "_ref", "y"], [["a", i, "b"] for i in range(1, 6)], K, F5, ["_ref"]))
check("list: column name ignored", qa_core.same_list(["id"], [[i] for i in range(1, 6)], K, F5, ["_ref"]))
check("long list: first 50 of 80", qa_core.same_list(K, F80[:50], K, F80, ["_ref"]))
check("long list: last 50 of 80 (a different valid 50)", qa_core.same_list(K, F80[-50:], K, F80, ["_ref"]))
check("long list: 49 rows", qa_core.same_list(K, F80[:49], K, F80, ["_ref"]), False)
check("long list: 51 rows", qa_core.same_list(K, F80[:51], K, F80, ["_ref"]), False)
check("long list: 50 with one outside F", qa_core.same_list(K, F80[:49] + rows([999]), K, F80, ["_ref"]), False)
KP = ["_ref_a", "_ref_b"]
check("pairs: swapped, unordered", qa_core.same_list(KP, [[2, 1], [4, 3]], KP, [[1, 2], [3, 4]], KP, unordered=True))
check("pairs: columns are matched by value, so a swapped column order still passes",
      qa_core.same_list(KP, [[2, 1], [4, 3]], KP, [[1, 2], [3, 4]], KP))
check("pairs: a wrong pairing fails", qa_core.same_list(KP, [[1, 4], [3, 2]], KP, [[1, 2], [3, 4]], KP), False)
check("empty gold, empty answer", qa_core.same_list(K, [], K, [], ["_ref"]))
check("empty gold, rows returned", qa_core.same_list(K, F5, K, [], ["_ref"]), False)
check("non-empty gold, empty answer", qa_core.same_list(K, [], K, F5, ["_ref"]), False)
check("single: right event", qa_core.same_single(["_ref", "x"], [[7, "a"]], 7))
check("single: wrong event", qa_core.same_single(["_ref", "x"], [[8, "a"]], 7), False)
check("single: two rows", qa_core.same_single(["_ref"], [[7], [7]], 7), False)

# ---------- live: every test item against its own gold ----------
driver = get_driver()
with open("eval/test.jsonl", encoding="utf-8") as f:
    items = [json.loads(line) for line in f if line.strip()]
random.seed(1)


def ok_res(keys, rows_):
    return SimpleNamespace(status="ok", keys=keys, rows=rows_, text="")


def score(it, res):
    return run_eval.is_correct(it, res, driver)


for it in items:
    i = it["id"]
    if it["expect"] == "refuse":
        check(f"{i} refusal scores correct", score(it, SimpleNamespace(status="refused", keys=[], rows=[], text="")))
        check(f"{i} a query instead of a refusal scores wrong", score(it, ok_res([], [])), False)
        continue
    if it["expect"] == "fast":
        check(f"{i} right FAST call scores correct", score(it, SimpleNamespace(status="fast", keys=[], rows=[], text=it["gold"])))
        wrong = "Q8" if it["gold"] != "Q8" else "Q14"
        check(f"{i} wrong FAST call scores wrong", score(it, SimpleNamespace(status="fast", keys=[], rows=[], text=wrong)), False)
        continue
    params = {k: v for k, v in it["refs"].items() if f"${k}" in it["gold"]}
    keys, got = qa_core.execute_readonly(driver, it["gold"], params)
    kind = it.get("kind")
    check(f"{i} [{kind}] gold scores correct against itself", score(it, ok_res(keys, got)))
    if got:
        check(f"{i} empty answer scores wrong", score(it, ok_res(keys, [])), False)
    if kind == "list" and len(got) >= 2:
        shuffled = got[:]
        random.shuffle(shuffled)
        check(f"{i} shuffled rows score correct", score(it, ok_res(keys, shuffled)))
        check(f"{i} one row dropped scores wrong", score(it, ok_res(keys, got[:-1])), False)
        check(f"{i} duplicated row scores wrong", score(it, ok_res(keys, got[:-1] + [got[0]])), False)
        if "_ref" in keys:
            bogus = [list(r) for r in got]
            bogus[0][keys.index("_ref")] = -1
            check(f"{i} event outside the full result scores wrong", score(it, ok_res(keys, bogus)), False)
        if it.get("truncated"):
            fk, fr = qa_core.execute_readonly(driver, qa_core.strip_limit(it["gold"]), params)
            check(f"{i} a different valid {len(got)} of the full result scores correct",
                  score(it, ok_res(fk, fr[-len(got):])))
    if kind == "single":
        wrong = [list(got[0])]
        wrong[0][keys.index("_ref")] = -1
        check(f"{i} wrong event scores wrong", score(it, ok_res(keys, wrong)), False)
driver.close()

print(f"\n{len(fails)} failed" if fails else "\nAll scorer tests passed")
sys.exit(1 if fails else 0)