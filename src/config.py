import os
from dotenv import load_dotenv
from neo4j import GraphDatabase

load_dotenv()

DB = os.getenv("NEO4J_DATABASE")
DATA_CLEAN = "data/processed/karachi_events_clean.parquet"

GRAPH_RULES = {
    "same_actor_window_days": 30,
    "same_mo_window_days": 30,
    "followed_by_window_days": 7,
    "source_max_events": 10,
    "similar_top_k": 5,
    "similar_min_score": 0.85,
}

CLUSTER_RULES = {
    "umap_neighbors": 15,
    "cluster_dims": 5,
    "min_cluster_size": 10,
    "random_state": 42,
}

ORG_PLACEHOLDERS = {"not applicable", "civilians", "civilian"}
ORG_ALIASES = {
    "Muttahida Qaumi Movement": "Muttahida Qaumi Movement (MQM)",
    "Muttahida Quami Movement (MQM)": "Muttahida Qaumi Movement (MQM)",
    "Muttahida Qaumi Movement (MQM): Haqiqi": "Muhajir Qaumi Movement: Haqiqi (MQM-H)",
    "Awami National Party": "Awami National Party (ANP)",
    "Pakistan People's Party": "Pakistan People's Party (PPP)",
    "Pakistan Police": "Pakistani Police",
}

VALIDATOR_RULES = {"max_limit": 100, "list_limit": 50, "timeout_s": 10, "max_path_hops": 6}
FAST_DEFAULTS = {"q14_k": 5, "q15_k": 10, "q15_min_cosine": 0.85, "q15_limit": 50}


def get_driver():
    return GraphDatabase.driver(
        os.getenv("NEO4J_URI"),
        auth=(os.getenv("NEO4J_USER"), os.getenv("NEO4J_PASSWORD")),
    )


def run(driver, query, **params):
    records, _, _ = driver.execute_query(query, database_=DB, **params)
    return records
