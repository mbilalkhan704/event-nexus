"""
Merges eval/test_raw/*.txt into eval/test_draft.jsonl (one JSON object per line, like dev.jsonl).
Questions are kept exactly as written; only blank lines and exact duplicates are dropped.
The gold fields stay empty until the gold is written.

    python src/test_draft.py
"""
import glob
import json
import os

items, seen = [], set()
for path in sorted(glob.glob("eval/test_raw/*.txt")):
    tester = os.path.splitext(os.path.basename(path))[0]
    kept = dropped = 0
    with open(path, encoding="utf-8") as f:
        for line in f:
            q = line.strip()
            if not q:
                continue
            if q.lower() in seen:
                dropped += 1
                continue
            seen.add(q.lower())
            items.append({"id": f"x{len(items) + 1:03d}", "tester": tester, "question": q,
                          "events": None, "refs": {}, "expect": None, "query_id": None,
                          "gold": None, "note": ""})
            kept += 1
    print(f"{tester}: {kept} kept, {dropped} exact duplicates dropped")

with open("eval/test_draft.jsonl", "w", encoding="utf-8") as f:
    for it in items:
        f.write(json.dumps(it, ensure_ascii=False) + "\n")
print(f"wrote {len(items)} questions to eval/test_draft.jsonl")