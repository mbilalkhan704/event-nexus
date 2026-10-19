import numpy as np
import pandas as pd
from config import DATA_CLEAN, GRAPH_RULES, get_driver, run
import build_graph as bg

MIN_COS = GRAPH_RULES["similar_min_score"]
K = GRAPH_RULES["similar_top_k"]

df = pd.read_parquet(DATA_CLEAN)
z = np.load("data/processed/event_embeddings.npz")
assert (df["eventid"].to_numpy() == z["eventids"]).all()

V = z["vectors"]
S = V @ V.T
np.fill_diagonal(S, -1)
dg = df["dup_group"].to_numpy()
S[dg[:, None] == dg[None, :]] = -1          # drop duplicate records before ranking

driver = get_driver()
area = {r["id"]: r["area"] for r in run(driver,
    "MATCH (e:Event)-[:OCCURRED_IN]->(a:Area) RETURN e.eventid AS id, a.name AS area")}

ids, dates = df["eventid"].to_numpy(), df["date"].to_numpy()
pairs = {}
for i in range(len(V)):
    for j in np.argsort(-S[i])[:K]:
        if S[i, j] >= MIN_COS:
            pairs[(min(i, j), max(i, j))] = float(S[i, j])
sel = [{int(j) for j in np.argsort(-S[i])[:K] if S[i, j] >= MIN_COS}
       for i in range(len(V))]
pairs = {(i, j): float(S[i, j]) for i in range(len(V))
         for j in sel[i] if i < j and i in sel[j]}      # mutual top-5 only

rows = []
for (a, b), s in pairs.items():
    first, second = sorted((a, b), key=lambda k: (dates[k], k))   # earlier -> later, row order breaks ties
    gap = int((dates[second] - dates[first]) / np.timedelta64(1, "D"))
    props = {"rule": "similar_to", "strength": round(s, 4), "gap_days": gap,
             "evidence": [f"cosine: {s:.3f}", f"gap_days: {gap}"]}
    ea, eb = area.get(int(ids[first])), area.get(int(ids[second]))
    if ea is not None and ea == eb:
        props["same_area"] = True
        props["evidence"].append(f"area: {ea}")
    rows.append({"a": int(ids[first]), "b": int(ids[second]), "props": props})

run(driver, "MATCH ()-[r:SIMILAR_TO]->() DELETE r")
bg.load_links(driver, "SIMILAR_TO", rows)

print("pairs:", len(rows), "| same_area:", sum("same_area" in r["props"] for r in rows),
      "| within 30 days:", sum(r["props"]["gap_days"] <= 30 for r in rows))
print(run(driver, "MATCH ()-[r:SIMILAR_TO]-() RETURN count(r)/2 AS n")[0]["n"], "SIMILAR_TO in graph")
print(run(driver, """MATCH (e:Event)-[:SIMILAR_TO]-() WITH e, count(*) AS d
    RETURN max(d) AS max_degree, count(e) AS events_linked""")[0].data())
driver.close()
