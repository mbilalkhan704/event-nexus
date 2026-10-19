import numpy as np
from config import get_driver, run

z = np.load("data/processed/event_embeddings.npz")
rows = [{"eventid": int(i), "vec": v.tolist()}
        for i, v in zip(z["eventids"], z["vectors"])]

driver = get_driver()

for k in range(0, len(rows), 400):
    run(driver, """
        UNWIND $rows AS r
        MATCH (e:Event {eventid: r.eventid})
        CALL db.create.setNodeVectorProperty(e, 'embedding', r.vec)
    """, rows=rows[k:k + 400])

run(driver, """
    CREATE VECTOR INDEX event_embedding IF NOT EXISTS
    FOR (e:Event) ON (e.embedding)
    OPTIONS {indexConfig: {`vector.dimensions`: 384,
                           `vector.similarity_function`: 'cosine'}}
""")
run(driver, "CALL db.awaitIndexes(300)")

print(run(driver, "MATCH (e:Event) WHERE e.embedding IS NOT NULL RETURN count(e) AS n")[0]["n"], "events with embedding")
print([dict(r) for r in run(driver, "SHOW VECTOR INDEXES YIELD name, state, populationPercent")])

# spot check: query with event 200001170001's own vector
q = z["vectors"][0].tolist()
for r in run(driver, """
    CALL db.index.vector.queryNodes('event_embedding', 4, $q)
    YIELD node, score RETURN node.eventid AS id, score
""", q=q):
    print(r["id"], round(r["score"], 3))

driver.close()
