import numpy as np, pandas as pd
from config import DATA_CLEAN, get_driver, run

df = pd.read_parquet(DATA_CLEAN)
z = np.load("data/processed/event_embeddings.npz")
V = z["vectors"]
pos = {int(e): k for k, e in enumerate(z["eventids"])}
txt = df.set_index("eventid")["summary_clean"]

driver = get_driver()
q = "MATCH (a:Event)-[:%s]-(b:Event) RETURN a.eventid AS a, b.eventid AS b"
gtd = {frozenset((r["a"], r["b"])) for r in run(driver, q % "GTD_RELATED")}
sim = {frozenset((r["a"], r["b"])) for r in run(driver, q % "SIMILAR_TO")}
driver.close()

pairs = []
for p in gtd:
    a, b = tuple(p)
    if txt[a] != txt[b]:
        pairs.append((a, b))

cos = np.array([V[pos[a]] @ V[pos[b]] for a, b in pairs])
M = V @ V.T
bg = np.sort(M[np.triu_indices_from(M, k=1)])
pct = np.searchsorted(bg, cos) / len(bg)

print(len(gtd), "GTD pairs;", len(pairs), "with different text")
print("PRIMARY percentile rank: mean %.3f | median %.3f" % (pct.mean(), np.median(pct)))
print("share >= 90th pct: %.2f | >= 99th pct: %.2f" % ((pct >= .9).mean(), (pct >= .99).mean()))
print("share with cosine >= 0.85: %.2f" % (cos >= .85).mean())
print("share that are SIMILAR_TO edges: %.2f" % np.mean([frozenset(p) in sim for p in pairs]))