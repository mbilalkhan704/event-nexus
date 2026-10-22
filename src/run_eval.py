"""
Score a model on an eval split.

    python src/run_eval.py --client fake --split dev --limit 5      # no model, checks the plumbing
    python src/run_eval.py --client <name> --split dev [--fewshot]
    python src/run_eval.py --client <name> --split dev --resume results/dev_<name>_XXXX.jsonl

Each item is appended to results/<split>_<client>_<time>.jsonl as it finishes (no result rows),
so an interrupted run can continue with --resume. Resume skips finished items and refuses to
continue if the prompt changed. The summary is written at the end.
"""
import argparse
import hashlib
import json
import math
import os
import sys
from collections import Counter, defaultdict
from datetime import datetime

import clients
import qa_core
from config import get_driver


def load(path):
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def wilson(k, n, z=1.96):
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (round(c - h, 3), round(c + h, 3))


def is_correct(item, res, driver):
    if item["expect"] == "refuse":
        return res.status == "refused"
    if item["expect"] == "fast":
        return res.status == "fast" and res.text.lower() == item["gold"].lower()
    if res.status != "ok":
        return False
    params = {k: v for k, v in item["refs"].items() if f"${k}" in item["gold"]}
    kind = item.get("kind")
    if kind == "single":
        return qa_core.same_single(res.keys, res.rows, item["refs"]["ref"])
    gold_keys, gold_rows = qa_core.execute_readonly(driver, item["gold"], params)
    if kind == "list":
        f_keys, f_rows = qa_core.execute_readonly(driver, qa_core.strip_limit(item["gold"]), params)
        key_cols = item.get("key_cols") or [k for k in f_keys if k.startswith("_")]
        return qa_core.same_list(res.keys, res.rows, f_keys, f_rows, key_cols, item.get("unordered", False))
    return qa_core.same_result(res.keys, res.rows, gold_keys, gold_rows)


def frac(k, n):
    return f"{k}/{n} = {k / n:.3f}  CI {wilson(k, n)}" if n else "n/a"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--client", default="fake")
    ap.add_argument("--split", default="dev")
    ap.add_argument("--fewshot", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--resume", default="", help="existing results .jsonl to continue")
    args = ap.parse_args()

    items = load(f"eval/{args.split}.jsonl")
    if args.limit:
        step = max(1, len(items) // args.limit)
        items = items[::step][:args.limit]
    order = {it["id"]: i for i, it in enumerate(items)}
    fewshot = None
    if args.fewshot:
        fewshot = [(qa_core.build_user_message(e["question"], e["events"]), e["reply"])
                   for e in load("eval/fewshot.jsonl")]
    client = clients.get_client(args.client, fewshot)
    prompt = qa_core.load_prompt()
    prompt_sha1 = hashlib.sha1(prompt.encode("utf-8")).hexdigest()[:12]
    driver = get_driver()
    names = qa_core.load_names(driver)

    os.makedirs("results", exist_ok=True)
    records = []
    if args.resume:
        path = args.resume
        stem = path[:-len(".jsonl")] if path.endswith(".jsonl") else path
        records = [r for r in load(path) if r["id"] in order]
        if any(r.get("prompt_sha1") != prompt_sha1 for r in records):
            sys.exit("the prompt changed since that run; start a fresh run")
    else:
        stem = f"results/{args.split}_{args.client}_{datetime.now():%Y%m%d_%H%M%S}"
    out_path = stem + ".jsonl"
    done = {r["id"] for r in records}
    if done:
        print(f"resuming: {len(done)} items already done")
    out = open(out_path, "a", encoding="utf-8")

    for n, item in enumerate(items, 1):
        if item["id"] in done:
            continue
        res = qa_core.answer(item["question"], item["events"], client, driver, names,
                             item["refs"], system_prompt=prompt)
        ok = is_correct(item, res, driver)
        rec = {"id": item["id"], "query_id": item["query_id"], "expect": item["expect"],
               "question": item["question"], "kind": res.kind, "status": res.status,
               "correct": ok, "seconds": res.seconds, "raw": (res.raw or "")[:1500],
               "text": res.text[:1500], "problems": res.problems, "error": res.error,
               "qtype": item.get("kind", ""),
               "prompt_sha1": prompt_sha1}
        records.append(rec)
        out.write(json.dumps(rec, ensure_ascii=False) + "\n")
        out.flush()
        print(f"[{n}/{len(items)}] {item['id']} {item['query_id']:6} {rec['status']:9} {'OK' if ok else '--'}")
    out.close()
    driver.close()

    records.sort(key=lambda r: order[r["id"]])
    per_q = defaultdict(lambda: [0, 0])
    for r in records:
        per_q[r["query_id"]][0] += r["correct"]
        per_q[r["query_id"]][1] += 1
    by = lambda e: [r for r in records if r["expect"] == e]
    cy, fa, rf = by("cypher"), by("fast"), by("refuse")
    cypher_outputs = [r for r in records if r["kind"] == "CYPHER"]
    summary = {
        "client": client.name, "fewshot": bool(fewshot), "split": args.split, "items": len(items),
        "date": datetime.now().isoformat(timespec="seconds"),
        "prompt_sha1": prompt_sha1,
        "execution_accuracy": [sum(r["correct"] for r in cy), len(cy)],
        "valid_query_rate": [sum(r["status"] == "ok" for r in cypher_outputs), len(cypher_outputs)],
        "refusals_made_when_needed": [sum(r["correct"] for r in rf), len(rf)],
        "wrongly_refused": [sum(r["status"] == "refused" for r in cy + fa), len(cy + fa)],
        "fast_accuracy": [sum(r["correct"] for r in fa), len(fa)],
        "per_query": {q: v for q, v in sorted(per_q.items())},
        "promotion_candidates": sorted(q for q, (k, n_) in per_q.items()
                                       if n_ and k < 4 and q not in ("Q8", "Q10", "Q14", "Q15", "REFUSE", "AGG")),
        "statuses": dict(Counter(r["status"] for r in records)),
        "mean_seconds": round(sum(r["seconds"] for r in records) / max(1, len(records)), 2),
    }
    per_t = defaultdict(lambda: [0, 0])
    for r in records:
        per_t[r.get("qtype") or "-"][0] += r["correct"]
        per_t[r.get("qtype") or "-"][1] += 1
    summary["per_type"] = {t: v for t, v in sorted(per_t.items())}
    with open(stem + ".summary.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)

    print(f"\nclient {client.name} | few-shot {bool(fewshot)} | prompt {prompt_sha1} | {len(items)} questions")
    print("execution accuracy      ", frac(*summary["execution_accuracy"]))
    print("valid-query rate        ", frac(*summary["valid_query_rate"]))
    print("refusals when needed    ", frac(*summary["refusals_made_when_needed"]))
    print("wrongly refused         ", frac(*summary["wrongly_refused"]))
    print("FAST accuracy           ", frac(*summary["fast_accuracy"]))
    print("statuses                ", summary["statuses"])
    print("per query (correct/total):", {q: f"{k}/{n_}" for q, (k, n_) in summary["per_query"].items()})
    print("promotion candidates (< 4 of 5):", summary["promotion_candidates"] or "none")
    print("wrote", out_path)


if __name__ == "__main__":
    main()