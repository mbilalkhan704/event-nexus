import os
import pandas as pd
from dotenv import load_dotenv
from neo4j import GraphDatabase
from sentence_transformers import SentenceTransformer
import ollama

load_dotenv()
DB = os.getenv("NEO4J_DATABASE")

# 1. Data: read one real Karachi event that has a summary
cols = ["eventid", "iyear", "imonth", "iday", "city", "gname", "summary"]
df = pd.read_parquet("data/processed/gtd_full.parquet", columns=cols)
mask = df["city"].eq("Karachi").fillna(False) & df["summary"].notna()
row = df[mask].iloc[0]
eventid = int(row["eventid"])
summary = str(row["summary"])
print("1. Data   ->", eventid, row["city"], row["gname"])

# 2. Neo4j: write the event as a node
driver = GraphDatabase.driver(
    os.getenv("NEO4J_URI"),
    auth=(os.getenv("NEO4J_USER"), os.getenv("NEO4J_PASSWORD")),
)
driver.execute_query(
    "MERGE (e:SmokeTest {eventid: $eventid}) "
    "SET e.city = $city, e.actor = $actor, e.summary = $summary",
    eventid=eventid, city=str(row["city"]), actor=str(row["gname"]),
    summary=summary, database_=DB,
)
print("2. Neo4j  -> node written")

# 3. Embedding: embed the summary and store it on the node
embedder = SentenceTransformer("models/minilm-embedder")
vec = embedder.encode(summary).tolist()
driver.execute_query(
    "MATCH (e:SmokeTest {eventid: $eventid}) SET e.embedding = $vec",
    eventid=eventid, vec=vec, database_=DB,
)
records, _, _ = driver.execute_query(
    "MATCH (e:SmokeTest {eventid: $eventid}) RETURN size(e.embedding) AS n",
    eventid=eventid, database_=DB,
)
print("3. Embed  -> stored vector of size", records[0]["n"])

try:
    # 4. LLM: read the node back and ask the local model (Ollama must be running)
    records, _, _ = driver.execute_query(
        "MATCH (e:SmokeTest {eventid: $eventid}) RETURN e.summary AS s",
        eventid=eventid, database_=DB,
    )
    prompt = "Summarise this incident in one sentence:\n" + records[0]["s"]
    r = ollama.chat(model="llama3.2:1b", messages=[{"role": "user", "content": prompt}])
    print("4. LLM    ->", r["message"]["content"])
finally:
    # 5. Cleanup runs even if a step above fails
    driver.execute_query("MATCH (e:SmokeTest) DETACH DELETE e", database_=DB)
    driver.close()
    print("5. Cleanup -> done")