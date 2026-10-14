import os
from dotenv import load_dotenv
from neo4j import GraphDatabase

load_dotenv()

uri = os.getenv("NEO4J_URI")
user = os.getenv("NEO4J_USER")
password = os.getenv("NEO4J_PASSWORD")
database = os.getenv("NEO4J_DATABASE")

driver = GraphDatabase.driver(uri, auth=(user, password))
driver.verify_connectivity()
print("Connected to Neo4j")

records, summary, keys = driver.execute_query("RETURN 1 AS ok", database_=database)
print("Query result:", records[0]["ok"])

records, _, _ = driver.execute_query(
    "CALL dbms.components() YIELD name, versions RETURN name, versions",
    database_=database
)
print("Server:", records[0]["name"], records[0]["versions"])

driver.close()