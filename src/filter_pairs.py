"""
Overlap filter: drops any training pair whose question has MiniLM cosine >= 0.85 to a dev or test
question (DECISIONS.md, Test set row), reports the count, and writes train/pairs.jsonl.

    python src/filter_pairs.py                       # dev only until the test set exists
    python src/filter_pairs.py --test eval/test.jsonl

Always reads train/pairs_raw.jsonl, so it can be rerun when the test set arrives.
"""
import argparse
import json
import os
from collections import Counter

from sentence_transformers import SentenceTransformer

THRESHOLD = 0.85


def load(path):
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--test", default="eval/test.jsonl")
    args = ap.parse_args()

    pairs = load("train/pairs_raw.jsonl")
    refs = [("dev", it["question"]) for it in load("eval/dev.jsonl")]
    if os.path.exists(args.test):
        refs += [("test", it["question"]) for it in load(args.test)]
    else:
        print(f"WARNING: {args.test} not found; filtering against dev only. Rerun once the test set exists.")

    model = SentenceTransformer("models/minilm-embedder")
    P = model.encode([p["question"] for p in pairs], normalize_embeddings=True, batch_size=64)
    R = model.encode([q for _, q in refs], normalize_embeddings=True, batch_size=64)
    sims = P @ R.T
    best, arg = sims.max(axis=1), sims.argmax(axis=1)

    keep, removed = [], Counter()
    for p, b, a in zip(pairs, best, arg):
        if b >= THRESHOLD:
            removed[refs[a][0]] += 1
        else:
            keep.append(p)

    with open("train/pairs.jsonl", "w", encoding="utf-8") as f:
        for p in keep:
            f.write(json.dumps(p, ensure_ascii=False) + "\n")
    report = {"threshold": THRESHOLD, "raw": len(pairs), "kept": len(keep), "removed": sum(removed.values()),
              "removed_by_split": dict(removed), "compared_against": dict(Counter(s for s, _ in refs))}
    with open("train/overlap_report.json", "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)

    by_type = Counter(p["type"] for p in keep)
    print(f"raw {len(pairs)} | removed {sum(removed.values())} {dict(removed)} | kept {len(keep)}")
    print("by type:", dict(by_type), f"| FAST share {by_type['fast'] / max(1, len(keep)):.1%}")
    print("by query:", dict(sorted(Counter(p['query_id'] for p in keep).items())))
    print("need at least about 300 kept" + ("" if len(keep) >= 300 else "  ** BELOW 300 **"))


if __name__ == "__main__":
    main()
    