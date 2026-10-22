"""Shows which test items differ between eval/test.prev.jsonl and eval/test.jsonl."""
import json


def load(path):
    with open(path, encoding="utf-8") as f:
        return {d["id"]: d for d in (json.loads(line) for line in f if line.strip())}


a, b = load("eval/test.prev.jsonl"), load("eval/test.jsonl")
changed = 0
for i in sorted(set(a) | set(b)):
    if a.get(i) != b.get(i):
        changed += 1
        for k in sorted(set(a.get(i, {})) | set(b.get(i, {}))):
            old, new = a.get(i, {}).get(k), b.get(i, {}).get(k)
            if old != new:
                print(i, k, "\n   old:", str(old)[:160], "\n   new:", str(new)[:160])
print("items changed:", changed)