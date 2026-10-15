import pandas as pd
from config import DATA_CLEAN, get_driver, run

df = pd.read_parquet(DATA_CLEAN)
driver = get_driver()


def count(query):
    return run(driver, query)[0]["c"]


PLACEHOLDERS = "['unknown','not applicable','civilians','civilian','gunmen']"

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
     count("MATCH (a:Event)-[r:SAME_ACTOR_NEARBY|SAME_SOURCE|GTD_RELATED]->(b:Event) WHERE a.date > b.date RETURN count(r) AS c"), 0),
    ("SAME_ACTOR_NEARBY gaps stay within 30 days",
     count("MATCH ()-[r:SAME_ACTOR_NEARBY]->() WHERE r.gap_days > 30 RETURN count(r) AS c"), 0),
    ("No event is completely isolated",
     count("MATCH (e:Event) WHERE NOT (e)--() RETURN count(e) AS c"), 0),
    ("GTD_RELATED pairs",
     count("MATCH ()-[r:GTD_RELATED]->() RETURN count(r) AS c"), 118),
]

failed = 0
for name, got, want in checks:
    ok = got == want
    failed += not ok
    print("PASS" if ok else "FAIL", f"{name}: got {got}, expected {want}")

driver.close()
print("\nAll checks passed" if not failed else f"\n{failed} check(s) failed")