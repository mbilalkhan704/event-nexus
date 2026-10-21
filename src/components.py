"""
Connected components of the event-to-event links (the five rule-based link
types; GTD_RELATED is excluded). Writes data/processed/components.json.

Why: two events in different components have no path of any length, so path
questions can answer "no link of any length" at once instead of searching.
The file is not part of the graph. Rerun it after every graph rebuild.

    python src/components.py          # build the file
    python src/components.py --pairs  # also print Q10 timing queries
"""
import json
import sys
import networkx as nx
from config import VALIDATOR_RULES, get_driver, run

MAX_PATH_HOPS = VALIDATOR_RULES["max_path_hops"]

LINK_TYPES = ["SAME_ACTOR_NEARBY", "SAME_SOURCE", "SAME_MO_LOCAL", "FOLLOWED_BY", "SIMILAR_TO"]
OUT = "data/processed/components.json"

_PATTERN = "(a:Event)-[:" + "|".join(LINK_TYPES) + "]-(b:Event)"
EDGE_QUERY = f"MATCH {_PATTERN} WHERE a.eventid < b.eventid RETURN a.eventid AS a, b.eventid AS b"
# Distinct linked pairs (a pair joined by two link types counts once)
COUNT_QUERY = (f"MATCH {_PATTERN} WHERE a.eventid < b.eventid "
               "RETURN count(DISTINCT [a.eventid, b.eventid]) AS c")


def build_nx_graph(driver):
    ids = [r["id"] for r in run(driver, "MATCH (e:Event) RETURN e.eventid AS id")]
    G = nx.Graph()
    G.add_nodes_from(ids)
    G.add_edges_from((r["a"], r["b"]) for r in run(driver, EDGE_QUERY))
    return G


def order_components(G):
    """Largest first; ties broken by the smallest event id, so ids are stable."""
    return sorted(nx.connected_components(G), key=lambda c: (-len(c), min(c)))


def write_file(G, comps):
    data = {
        "link_types": LINK_TYPES,
        "events": G.number_of_nodes(),
        "edges": G.number_of_edges(),
        "components": len(comps),
        "isolated": sum(len(c) == 1 for c in comps),
        "largest": [len(c) for c in comps[:5]],
        "component_of": {str(e): i for i, c in enumerate(comps) for e in c},
    }
    with open(OUT, "w") as f:
        json.dump(data, f)
    return data


def load_components(driver):
    """Return {eventid: component id}. Raise if the file is missing or stale."""
    with open(OUT) as f:
        data = json.load(f)
    events = run(driver, "MATCH (e:Event) RETURN count(e) AS c")[0]["c"]
    edges = run(driver, COUNT_QUERY)[0]["c"]
    if (data["events"], data["edges"]) != (events, edges):
        raise RuntimeError(
            f"{OUT} is stale: file has {data['events']} events and {data['edges']} links, "
            f"graph has {events} and {edges}. Run python src/components.py")
    return {int(k): v for k, v in data["component_of"].items()}


def same_component(component_of, a, b):
    """True when both events share a component. Raises on an unknown event id."""
    for e in (a, b):
        if e not in component_of:
            raise KeyError(f"unknown event id {e}")
    return component_of[a] == component_of[b]


def timing_pairs(G, comps, wanted=(6, 7, 21)):
    """Return {label: (a, b, true distance or None)}: one example pair per
    wanted distance (hubs tried first), the two farthest-apart hubs, and one
    pair from two different components."""
    big = G.subgraph(comps[0])
    by_degree = sorted(big.nodes, key=lambda n: (-big.degree(n), n))
    found = {}
    for src in by_degree:
        for dst, d in sorted(nx.single_source_shortest_path_length(big, src).items()):
            if d in wanted and d not in found:
                found[d] = (src, dst, d)
        if len(found) == len(wanted):
            break
    pairs = {f"distance {d}": found[d] for d in wanted if d in found}
    hubs = by_degree[:20]
    best = max(((a, b) for a in hubs for b in hubs if a < b),
               key=lambda p: nx.shortest_path_length(big, p[0], p[1]))
    pairs["two hubs, farthest apart"] = (*best, nx.shortest_path_length(big, *best))
    if len(comps) > 1:
        pairs["different components"] = (min(comps[0]), min(comps[1]), None)
    return pairs


def print_timing_queries(pairs):
    print(f"\nQ10 timing queries (bound {MAX_PATH_HOPS}). Run each twice and note both ms figures.")
    for label, (a, b, d) in pairs.items():
        if d is None:
            expect = "no rows (different components)"
        elif d <= MAX_PATH_HOPS:
            expect = f"1 row (hops {d})"
        else:
            expect = f"no rows (true distance {d}, beyond the bound)"
        print(f"\n-- {label}: {a} and {b}; expected: {expect}")
        print(f"MATCH (a:Event {{eventid: {a}}}) MATCH (b:Event {{eventid: {b}}}) "
              f"MATCH p = shortestPath((a)-[:{'|'.join(LINK_TYPES)}*..{MAX_PATH_HOPS}]-(b)) "
              "RETURN length(p) AS hops;")


if __name__ == "__main__":
    driver = get_driver()
    G = build_nx_graph(driver)
    driver.close()
    comps = order_components(G)
    data = write_file(G, comps)
    print("events:", data["events"], "| distinct links:", data["edges"])
    print("components:", data["components"], "| isolated events:", data["isolated"])
    print("largest components:", data["largest"])
    print("written:", OUT)
    if "--pairs" in sys.argv:
        print_timing_queries(timing_pairs(G, comps))

        