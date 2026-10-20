import json
import pandas as pd
from config import DATA_CLEAN, GRAPH_RULES, get_driver, run
from build_graph import area_assignments

df = pd.read_parquet(DATA_CLEAN)
driver = get_driver()


def count(query):
    return run(driver, query)[0]["c"]


PLACEHOLDERS = "['unknown','not applicable','civilians','civilian','gunmen']"

AREA_BAD = "['unknown','karachi','sindh','pakistan','bilal colony','karachi east','karachi west','karachi south','karachi central']"

with open("data/processed/event_map.json") as f:
    event_map = json.load(f)
map_clustered = sum(p["cluster"] is not None for p in event_map)

checks = [
    ("Events match the dataset",
     count("MATCH (e:Event) RETURN count(e) AS c"), len(df)),
    ("nkillter is set wherever GTD has a value",
     count("MATCH (e:Event) WHERE e.nkillter IS NOT NULL RETURN count(e) AS c"), int(df["nkillter"].notna().sum())),
    ("nwoundte is set wherever GTD has a value",
     count("MATCH (e:Event) WHERE e.nwoundte IS NOT NULL RETURN count(e) AS c"), int(df["nwoundte"].notna().sum())),
    ("Attackers killed never exceed total killed",
     count("MATCH (e:Event) WHERE e.nkillter > e.nkill RETURN count(e) AS c"), 0),
    ("Attackers wounded never exceed total wounded",
     count("MATCH (e:Event) WHERE e.nwoundte > e.nwound RETURN count(e) AS c"), 0),
    ("ATTRIBUTED_TO equals known-actor events",
     count("MATCH ()-[r:ATTRIBUTED_TO]->() RETURN count(r) AS c"), int(df["actor_known"].sum())),
    ("No node is named like a placeholder",
     count(f"MATCH (n) WHERE toLower(coalesce(n.name, n.citation, '')) IN {PLACEHOLDERS} RETURN count(n) AS c"), 0),
    ("No self-links",
     count("MATCH (e:Event)-[r]->(e) RETURN count(r) AS c"), 0),
    ("Derived links point forward in time",
     count("MATCH (a:Event)-[r:SAME_ACTOR_NEARBY|SAME_SOURCE|GTD_RELATED|SAME_MO_LOCAL|FOLLOWED_BY]->(b:Event) WHERE a.date > b.date RETURN count(r) AS c"), 0),
    ("SAME_ACTOR_NEARBY gaps stay within 30 days",
     count("MATCH ()-[r:SAME_ACTOR_NEARBY]->() WHERE r.gap_days > 30 RETURN count(r) AS c"), 0),
    ("No event is completely isolated",
     count("MATCH (e:Event) WHERE NOT (e)--() RETURN count(e) AS c"), 0),
    ("GTD_RELATED pairs",
     count("MATCH ()-[r:GTD_RELATED]->() RETURN count(r) AS c"), 118),
    ("OCCURRED_IN equals events with an area",
     count("MATCH ()-[r:OCCURRED_IN]->() RETURN count(r) AS c"), len(area_assignments(df))),
    ("Each event has at most one Area",
     count("MATCH (e:Event)-[:OCCURRED_IN]->(:Area) WITH e, count(*) AS n WHERE n > 1 RETURN count(e) AS c"), 0),
    ("Events with a Locality also have an Area",
     count("MATCH (e:Event)-[:OCCURRED_AT]->() WHERE NOT (e)-[:OCCURRED_IN]->() RETURN count(e) AS c"), 0),
    ("Every Locality is part of an Area",
     count("MATCH (l:Locality) WHERE NOT (l)-[:PART_OF]->(:Area) RETURN count(l) AS c"), 0),
    ("No Area or Locality is named like a placeholder",
     count(f"MATCH (n) WHERE (n:Area OR n:Locality) AND toLower(n.name) IN {AREA_BAD} RETURN count(n) AS c"), 0),
    ("FOLLOWED_BY gaps stay within 7 days",
     count("MATCH ()-[r:FOLLOWED_BY]->() WHERE r.gap_days > 7 RETURN count(r) AS c"), 0),
    ("SAME_MO_LOCAL gaps stay within 30 days",
     count("MATCH ()-[r:SAME_MO_LOCAL]->() WHERE r.gap_days > 30 RETURN count(r) AS c"), 0),
    ("SAME_MO_LOCAL events share an Area",
     count("MATCH (a:Event)-[r:SAME_MO_LOCAL]->(b:Event) WHERE NOT EXISTS { MATCH (a)-[:OCCURRED_IN]->(x)<-[:OCCURRED_IN]-(b) } RETURN count(r) AS c"), 0),
    ("Every event has an embedding",
     count("MATCH (e:Event) WHERE e.embedding IS NOT NULL RETURN count(e) AS c"), len(df)),
    ("Embeddings have 384 dimensions",
     count("MATCH (e:Event) WHERE size(e.embedding) <> 384 RETURN count(e) AS c"), 0),
    ("Vector index is online",
     count("SHOW VECTOR INDEXES YIELD name, state WHERE name = 'event_embedding' AND state = 'ONLINE' RETURN count(*) AS c"), 1),
    ("SIMILAR_TO points forward in time",
     count("MATCH (a:Event)-[r:SIMILAR_TO]->(b:Event) WHERE a.date > b.date RETURN count(r) AS c"), 0),
    ("SIMILAR_TO scores stay at or above the cut-off",
     count(f"MATCH ()-[r:SIMILAR_TO]->() WHERE r.strength < {GRAPH_RULES['similar_min_score']} RETURN count(r) AS c"), 0),
    ("No SIMILAR_TO between duplicate records",
     count("MATCH (a:Event)-[:SIMILAR_TO]->(b:Event) WHERE a.dup_group = b.dup_group RETURN count(*) AS c"), 0),
    ("No event has more SIMILAR_TO links than the top-k",
     count(f"MATCH (e:Event)-[:SIMILAR_TO]-() WITH e, count(*) AS d WHERE d > {GRAPH_RULES['similar_top_k']} RETURN count(e) AS c"), 0),
    ("SIMILAR_TO same_area is only set when both events share an Area",
     count("MATCH (a:Event)-[r:SIMILAR_TO]->(b:Event) WHERE r.same_area AND NOT EXISTS { MATCH (a)-[:OCCURRED_IN]->(x)<-[:OCCURRED_IN]-(b) } RETURN count(r) AS c"), 0),
    ("SIMILAR_TO same_area is set whenever both events share an Area",
     count("MATCH (a:Event)-[r:SIMILAR_TO]->(b:Event) WHERE r.same_area IS NULL AND EXISTS { MATCH (a)-[:OCCURRED_IN]->(x)<-[:OCCURRED_IN]-(b) } RETURN count(r) AS c"), 0),
    ("Noise events have no cluster (no negative cluster ids)",
     count("MATCH (e:Event) WHERE e.cluster < 0 RETURN count(e) AS c"), 0),
    ("Clustered events match the map file",
     count("MATCH (e:Event) WHERE e.cluster IS NOT NULL RETURN count(e) AS c"), map_clustered),
    ("Map file covers every event",
     len(event_map), len(df)),
]

failed = 0
for name, got, want in checks:
    ok = got == want
    failed += not ok
    print("PASS" if ok else "FAIL", f"{name}: got {got}, expected {want}")

driver.close()
print("\nAll checks passed" if not failed else f"\n{failed} check(s) failed")
