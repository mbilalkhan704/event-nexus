"""
Paired comparison of two test runs (fine-tuned against untrained), with the rules fixed in DECISIONS.md.

    python src/sign_test.py results/<tuned>.jsonl results/<base>.jsonl

Success rule (Cypher items only, expect = cypher): the fine-tuned execution accuracy beats the
untrained one by at least 15 points AND a one-sided exact sign test on the discordant items
(only items where exactly one model is right) gives p < 0.05.

Also reports: by question kind, the flagged subgroups, FAST and refuse counts, wrong refusals.
Subgroups are descriptive only. The LIMIT-50 subgroup needs Neo4j (it runs the gold without LIMIT).
"""
import json
import math
import sys
from collections import defaultdict

MIN_POINTS = 15.0
ALPHA = 0.05

FLAGS = {
    "empty gold by design (x013, x044)": ["x013", "x044"],
    "needs unlisted properties (x031, x032)": ["x031", "x032"],
    "ambiguous readings (x023, x047, x053)": ["x023", "x047", "x053"],
    "no-link probe (x037)": ["x037"],
    "single event, may route to FAST: Q1 (x004, x049)": ["x004", "x049"],
}


def load(path):
    out = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                r = json.loads(line)
                out[r["id"]] = r
    return out


def wilson(k, n, z=1.96):
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (max(0.0, c - h), min(1.0, c + h))


def sign_p(wins, losses):
    """One-sided exact sign test: P(X >= wins) for X ~ Binomial(wins + losses, 0.5)."""
    n = wins + losses
    if n == 0:
        return 1.0
    return sum(math.comb(n, k) for k in range(wins, n + 1)) / 2 ** n


def pair(ids, tuned, base):
    t = sum(1 for i in ids if tuned[i]["correct"])
    b = sum(1 for i in ids if base[i]["correct"])
    w = sum(1 for i in ids if tuned[i]["correct"] and not base[i]["correct"])
    l = sum(1 for i in ids if base[i]["correct"] and not tuned[i]["correct"])
    return t, b, w, l


def row(label, ids, tuned, base):
    t, b, w, l = pair(ids, tuned, base)
    n = len(ids)
    print(f"  {label:52} n={n:2}  tuned {t:2}  base {b:2}  tuned-only {w:2}  base-only {l:2}")


def limit50_ids(items):
    """Cypher list items whose full gold result (no LIMIT) has 50 or more rows."""
    try:
        import qa_core
        from config import get_driver
        driver = get_driver()
        found = []
        for it in items:
            if it["expect"] != "cypher" or it.get("kind") != "list":
                continue
            params = {k: v for k, v in it["refs"].items() if f"${k}" in it["gold"]}
            _, rows = qa_core.execute_readonly(driver, qa_core.strip_limit(it["gold"]), params)
            if len(rows) >= 50:
                found.append(it["id"])
        driver.close()
        return found
    except Exception as e:
        print(f"  (LIMIT-50 subgroup skipped: {e})")
        return None


def main():
    if len(sys.argv) != 3:
        sys.exit("usage: python src/sign_test.py <tuned results .jsonl> <base results .jsonl>")
    tuned, base = load(sys.argv[1]), load(sys.argv[2])
    with open("eval/test.jsonl", encoding="utf-8") as f:
        items = [json.loads(line) for line in f if line.strip()]
    ids_all = [it["id"] for it in items]
    if set(tuned) != set(ids_all) or set(base) != set(ids_all):
        sys.exit(f"both runs must cover all {len(ids_all)} test items "
                 f"(tuned {len(tuned)}, base {len(base)})")
    sha = {r.get("prompt_sha1") for r in list(tuned.values()) + list(base.values())}
    if len(sha) != 1:
        sys.exit(f"the two runs used different prompts: {sha}")

    kind = {it["id"]: it.get("kind", "") for it in items}
    cy = [it["id"] for it in items if it["expect"] == "cypher"]
    t, b, w, l = pair(cy, tuned, base)
    n = len(cy)
    diff = 100.0 * (t - b) / n
    p = sign_p(w, l)

    print(f"prompt {sha.pop()} | {n} Cypher items\n")
    print("HEADLINE (Cypher items)")
    print(f"  fine-tuned  {t}/{n} = {t / n:.3f}  95% CI ({wilson(t, n)[0]:.3f}, {wilson(t, n)[1]:.3f})")
    print(f"  untrained   {b}/{n} = {b / n:.3f}  95% CI ({wilson(b, n)[0]:.3f}, {wilson(b, n)[1]:.3f})")
    print(f"  difference  {diff:+.1f} points | net {w - l:+d} items "
          f"(fine-tuned right and base wrong: {w}; base right and fine-tuned wrong: {l})")
    print(f"  one-sided exact sign test: n discordant = {w + l}, p = {p:.4f}"
          f"  (two-sided, for information: {min(1.0, 2 * min(p, sign_p(l, w))):.4f})")
    ok_points, ok_p = diff >= MIN_POINTS, p < ALPHA
    print(f"  rule: at least {MIN_POINTS:.0f} points -> {'yes' if ok_points else 'NO'}; "
          f"p below {ALPHA} -> {'yes' if ok_p else 'NO'}")
    print(f"  VERDICT: {'success rule MET' if ok_points and ok_p else 'success rule NOT met: fine-tuning did not help by the pre-set rule'}\n")

    print("BY QUESTION KIND (Cypher items)")
    by = defaultdict(list)
    for i in cy:
        by[kind[i] or "-"].append(i)
    for k in sorted(by):
        row(k, by[k], tuned, base)

    print("\nFAST AND REFUSE (counts only)")
    for e in ("fast", "refuse"):
        ids = [it["id"] for it in items if it["expect"] == e]
        row(e, ids, tuned, base)

    print("\nWRONGLY REFUSED (answerable items, Cypher and FAST)")
    ans = [it["id"] for it in items if it["expect"] in ("cypher", "fast")]
    for name, run in (("fine-tuned", tuned), ("untrained", base)):
        print(f"  {name:12} {sum(1 for i in ans if run[i]['status'] == 'refused')}/{len(ans)}")

    print("\nFLAGGED SUBGROUPS (all items in the group, descriptive only)")
    for label, ids in FLAGS.items():
        row(label, [i for i in ids if i in tuned], tuned, base)
    lim = limit50_ids(items)
    if lim is not None:
        row("lists reaching LIMIT 50", lim, tuned, base)


if __name__ == "__main__":
    main()