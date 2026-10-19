import json
import numpy as np
import pandas as pd
import umap
from sklearn.cluster import HDBSCAN
from config import CLUSTER_RULES as R, DATA_CLEAN, get_driver, run

df = pd.read_parquet(DATA_CLEAN)
z = np.load("data/processed/event_embeddings.npz")
V = z["vectors"]
assert (df["eventid"].to_numpy() == z["eventids"]).all()

def project(dims, min_dist):
    return umap.UMAP(n_components=dims, n_neighbors=R["umap_neighbors"],
                     min_dist=min_dist, metric="cosine",
                     random_state=R["random_state"]).fit_transform(V)

U5 = project(R["cluster_dims"], 0.0)     # for clustering
U2 = project(2, 0.1)                     # for the map only
lab = HDBSCAN(min_cluster_size=R["min_cluster_size"], copy=True).fit_predict(U5)

# graph: cluster is a property; noise (-1) stays unset
rows = [{"eventid": int(e), "cluster": int(c)}
        for e, c in zip(df["eventid"], lab) if c >= 0]
driver = get_driver()
run(driver, "MATCH (e:Event) REMOVE e.cluster")          # makes reruns clean
run(driver, """
    UNWIND $rows AS r
    MATCH (e:Event {eventid: r.eventid})
    SET e.cluster = r.cluster
""", rows=rows)

# map file for the UI (display data stays out of the graph)
points = [{"eventid": int(e), "x": round(float(x), 4), "y": round(float(y), 4),
           "cluster": int(c) if c >= 0 else None}
          for e, (x, y), c in zip(df["eventid"], U2, lab)]
with open("data/processed/event_map.json", "w") as f:
    json.dump(points, f)

sizes = pd.Series(lab[lab >= 0]).value_counts()
print("clusters:", len(sizes), "| noise:", f"{(lab < 0).mean():.0%}")
print(run(driver, "MATCH (e:Event) WHERE e.cluster IS NOT NULL RETURN count(e) AS n")[0]["n"],
      "events with a cluster in the graph;", len(points), "points in event_map.json")
driver.close()
