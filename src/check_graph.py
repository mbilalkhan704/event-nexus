import pandas as pd
from config import DATA_CLEAN, get_driver, run
from build_graph import area_assignments

df = pd.read_parquet(DATA_CLEAN)
driver = get_driver()


def count(query):
    return run(driver, query)[0]["c"]


PLACEHOLDERS = "['unknown','not applicable','civilians','civilian','gunmen']"

AREA_BAD = "['unknown','karachi','sindh','pakistan','bilal colony','karachi east','karachi west','karachi south','karachi central']"

checks = [
    ("Events match the dataset",
     count("MATCH (e:Event) RETURN count(e) AS c"), len(df)),
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
]

failed = 0
for name, got, want in checks:
    ok = got == want
    failed += not ok
    print("PASS" if ok else "FAIL", f"{name}: got {got}, expected {want}")

driver.close()
print("\nAll checks passed" if not failed else f"\n{failed} check(s) failed")