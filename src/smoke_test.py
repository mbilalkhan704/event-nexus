import os
import pandas as pd
from dotenv import load_dotenv
from neo4j import GraphDatabase
from sentence_transformers import SentenceTransformer
from google import genai
import time
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

def ask_llm(prompt, retries=4):
    for attempt in range(retries):
        try:
            reply = client.models.generate_content(
                model="gemini-flash-latest", contents=prompt
            )
            return reply.text
        except Exception as e:
            wait = 2 ** attempt
            print(f"   Gemini attempt {attempt + 1} failed ({type(e).__name__}), retrying in {wait}s")
            time.sleep(wait)
    return None


def ask_local(prompt):
    r = ollama.chat(model="llama3.2:1b", messages=[{"role": "user", "content": prompt}])
    return r["message"]["content"]


client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

try:
    # 4. LLM: read the node back, ask the API, fall back to the local model
    records, _, _ = driver.execute_query(
        "MATCH (e:SmokeTest {eventid: $eventid}) RETURN e.summary AS s",
        eventid=eventid, database_=DB,
    )
    prompt = "Summarise this incident in one sentence:\n" + records[0]["s"]
    answer = ask_llm(prompt)
    if answer is None:
        print("   Gemini unavailable, trying the local model")
        answer = ask_local(prompt)
    print("4. LLM    ->", answer)
finally:
    # 5. Cleanup runs even if a step above fails
    driver.execute_query("MATCH (e:SmokeTest) DETACH DELETE e", database_=DB)
    driver.close()
    print("5. Cleanup -> done")
    