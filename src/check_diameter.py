import networkx as nx
from collections import Counter
from config import get_driver, run

driver = get_driver()
ids = [r["id"] for r in run(driver, "MATCH (e:Event) RETURN e.eventid AS id")]
edges = run(driver, """
MATCH (a:Event)-[:SAME_ACTOR_NEARBY|SAME_SOURCE|SAME_MO_LOCAL|FOLLOWED_BY|SIMILAR_TO]-(b:Event)
WHERE a.eventid < b.eventid
RETURN a.eventid AS a, b.eventid AS b
""")
driver.close()

G = nx.Graph()
G.add_nodes_from(ids)
G.add_edges_from((r["a"], r["b"]) for r in edges)

comps = sorted(nx.connected_components(G), key=len, reverse=True)
print("events:", G.number_of_nodes(), "| distinct edges:", G.number_of_edges())
print("components:", len(comps), "| isolated events:", sum(len(c) == 1 for c in comps))
print("largest components:", [len(c) for c in comps[:5]])

dist = Counter()
for c in comps:
    if len(c) > 1:
        for _, lengths in nx.all_pairs_shortest_path_length(G.subgraph(c)):
            for d in lengths.values():
                if d > 0:
                    dist[d] += 1
dist = {d: n // 2 for d, n in sorted(dist.items())}
print("connected pairs by shortest-path length:", dist)
print("connected pairs:", sum(dist.values()), "of", len(ids) * (len(ids) - 1) // 2)
print("longest shortest path:", max(dist))
