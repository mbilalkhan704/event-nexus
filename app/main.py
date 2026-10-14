import os
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from neo4j import GraphDatabase

load_dotenv()
app = FastAPI(title="EventNexus")

driver = GraphDatabase.driver(
    os.getenv("NEO4J_URI"),
    auth=(os.getenv("NEO4J_USER"), os.getenv("NEO4J_PASSWORD")),
)
DB = os.getenv("NEO4J_DATABASE")


@app.get("/api/health")
def health():
    records, _, _ = driver.execute_query("RETURN 1 AS ok", database_=DB)
    return {"api": "ok", "neo4j": records[0]["ok"] == 1}


PAGE = """
<!doctype html>
<html>
<head><meta charset="utf-8"><title>EventNexus</title></head>
<body style="font-family: sans-serif; padding: 2rem;">
  <h1>EventNexus</h1>
  <p id="status">Checking backend...</p>
  <script>
    fetch("/api/health")
      .then(r => r.json())
      .then(d => {
        document.getElementById("status").textContent =
          "API: " + d.api + " | Neo4j connected: " + d.neo4j;
      })
      .catch(() => {
        document.getElementById("status").textContent = "Backend not reachable";
      });
  </script>
</body>
</html>
"""


@app.get("/", response_class=HTMLResponse)
def home():
    return PAGE

