# Graph schema

The graph is built backwards from 15 questions (lookup, cross-event patterns, multi-hop chains, provenance, similarity). Of these, 12 are about connections between events. Every structure below exists to answer at least one of them.

## Map

```
Event -[ATTRIBUTED_TO {claimed, uncertain}]-> Group
Event -[HAS_ATTACK_TYPE]-> AttackType
Event -[USED_WEAPON]-> WeaponType
Event -[TARGETED]-> TargetType
Event -[TARGETED_ORG]-> TargetOrg
Event -[OCCURRED_IN {method}]-> Area
Event -[OCCURRED_AT]-> Locality -[PART_OF]-> Area
Event -[REPORTED_BY {dbsource}]-> Source

Event -[SAME_ACTOR_NEARBY | SAME_SOURCE | SAME_MO_LOCAL | FOLLOWED_BY | SIMILAR_TO | GTD_RELATED]- Event
```

## Nodes

| Node | Key | Source | Phase |
|---|---|---|---|
| `Event` | `eventid` | Cleaned table. Properties: `date`, `date_approx`, `summary_clean`, `location`, `city_raw`, `nkill`, `nwound`, `success`, `suicide`, `multiple`, `doubtterr`, `actor_known`, `dup_group`. Readable text copies for display: `gname`, `attack_type`, `weapon_type`, `weapon_subtype`, `weapon_detail`, `target_type`, `target_subtype`, `target_org`, `target_desc`, `motive`. Phase 5: `embedding` (384 dimensions) and `cluster` (integer, unset when the event is noise) | 3 (embedding and cluster in 5) |
| `Group` | `name` | `gname`, only when `actor_known` | 3 |
| `AttackType` | `name` | `attacktype1_txt` | 3 |
| `WeaponType` | `name` | `weaptype1_txt` (the subtype stays a property on the edge) | 3 |
| `TargetType` | `name` | `targtype1_txt` | 3 |
| `TargetOrg` | `name` | `corp1` | 3 |
| `Source` | `citation` | `scite1` to `scite3` | 3 |
| `Area` | `name` | Town or neighbourhood level place, used for linking and counting. Extracted from the location text and the summary; a name must appear in 2 or more events. Sub-areas roll up into their town through a hand-written map | 4 |
| `Locality` | `name` | The specific place a text names, kept only when it rolls up into a bigger Area (for example Gulshan-e-Maymar, Manghopir, Qasba Colony) | 4 |

## Event-to-attribute relationships

| Relationship | Properties | Notes |
|---|---|---|
| `ATTRIBUTED_TO` | `claimed`, `uncertain` | Confidence lives on the link, not on the group |
| `HAS_ATTACK_TYPE`, `USED_WEAPON`, `TARGETED`, `TARGETED_ORG` | | |
| `OCCURRED_IN` | `method` (location_pattern, city_field, summary_pattern or summary_gazetteer) | Event to Area. At most one per event |
| `REPORTED_BY` | `dbsource` | |
| `OCCURRED_AT` | | Event to Locality. Shows the specific place when it is known |
| `PART_OF` | | Locality to Area (Gulshan-e-Maymar is part of Gadap) |

**Unknown means no edge.** An event whose weapon, target, organisation or group is "Unknown" simply has no edge of that kind. The text value stays on the event for display.

**Two levels of place.** The Area is the town-level group used for linking and counting. The Locality is the specific sub-area the text names, kept whenever it differs from the Area. A detail view shows both, for example "Gadap, Gulshan-e-Maymar".

## Derived cross-event links

Each link stores `rule`, `strength` and `evidence` (which attributes matched). Symmetric links are stored once, from the earlier event to the later one, and queried without direction.

| Link | Rule | Phase |
|---|---|---|
| `SAME_ACTOR_NEARBY` | Same known group within 30 days. `gap_days` stored. Sizing: 236 pairs within 7 days, 632 within 30, 1,446 within 90 | 3 |
| `SAME_SOURCE` | Share a citation shared by 2 to 10 events. Strength is the number of shared citations. Sizing: 411 citations shared by 2+ events, covering 664 events (40%); the largest is shared by 7 | 3 |
| `SAME_MO_LOCAL` | Same Area, same attack type, weapon type and target type (Unknown never counts), within 30 days. Properties: `gap_days`, `same_locality`. 184 links | 4 |
| `FOLLOWED_BY` | The next event in the same Area, if it comes within 7 days. Directed earlier to later, with `gap_days` and `same_locality`. Forms chains, not all pairs. 280 links; the longest chain has 13 links (20 January to 24 February 2014) | 4 |
| `SIMILAR_TO` | Top 5 embedding neighbours by raw cosine, kept when the score is at least 0.85 and the pair is mutual (each event is in the other's top 5). `dup_group` pairs excluded. Stored once, earlier to later. Properties: `strength` (cosine), `gap_days`, `same_area` (only when both events share an Area). 928 links covering 784 events, maximum 5 per event | 5 |
| `GTD_RELATED` | GTD's own related pairs (118 in-scope pairs, 111 with different text). **Evaluation only** | 3 |

## Design principles

1. **Unknown is not a link.** Unknown values and generic group labels ("Unknown", "Gunmen") never create edges.
2. **Confidence lives on edges,** not nodes.
3. **`GTD_RELATED` never feeds the system.** It is not used to build links, retrieve results or train models.
4. **`multiple` is a property only,** not a link rule or model feature.
5. **Every derived link can explain itself** through its `rule`, `strength` and `evidence`.
6. **Two levels of place.** Linking uses the Area; the Locality keeps the detail.
7. **Clusters are a property, not a link.** `Event.cluster` is left unset for noise, and cluster numbers are not stable across parameter changes, so queries never hard-code them.

## Rule parameters

All windows and thresholds live in `src/config.py` so tuning never means rewriting rules:

```python
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
```

## Constraints and indexes

| Type | On | Phase |
|---|---|---|
| Uniqueness | `Event.eventid`, `Group.name`, `AttackType.name`, `WeaponType.name`, `TargetType.name`, `TargetOrg.name`, `Source.citation`, `Area.name`, `Locality.name` | 3 (Area and Locality in 4) |
| Range index | `Event.date` | 3 |
| Vector index | `Event.embedding` (index name event_embedding) (384 dimensions, cosine) | 5 |
| Full-text index | `Event.summary_clean` | 8 |

## Example queries

These illustrate the intended use. They are verified in Phase 7.

Campaign links within a week:

```cypher
MATCH (a:Event)-[r:SAME_ACTOR_NEARBY]->(b:Event)
WHERE r.gap_days <= 7
RETURN a.eventid, b.eventid, r.gap_days
```

Why are two events linked?

```cypher
MATCH (a:Event {eventid: $a})-[r]-(b:Event {eventid: $b})
RETURN type(r), r.rule, r.strength, r.evidence
```

Where did an event happen, down to the specific place? (run in Phase 4)

```cypher
MATCH (e:Event)-[:OCCURRED_AT]->(l:Locality {name: 'Gulshan-e-Maymar'})
MATCH (e)-[:OCCURRED_IN]->(a:Area)
RETURN e.eventid, e.date, a.name AS area, l.name AS locality, e.location LIMIT 3
```

The longest escalation chains (run in Phase 4):

```cypher
MATCH p = (a:Event)-[:FOLLOWED_BY*]->(b:Event)
WHERE NOT ()-[:FOLLOWED_BY]->(a) AND NOT (b)-[:FOLLOWED_BY]->()
RETURN a.eventid, b.eventid, length(p) AS links ORDER BY links DESC LIMIT 5
```

Similar events close in place and time? (run in Phase 5)

```cypher
MATCH (a:Event)-[r:SIMILAR_TO]-(b:Event)
WHERE r.same_area AND r.gap_days <= 30 AND a.eventid < b.eventid
RETURN a.eventid, b.eventid, r.strength, r.gap_days
ORDER BY r.strength DESC LIMIT 5
```

## Naming conventions

Node labels are PascalCase, relationship types are UPPER_SNAKE_CASE, and properties are snake_case.

## Loaded graph (Phases 3 to 5)

| Nodes | Count | Relationships | Count |
|---|---|---|---|
| Event | 1,664 | REPORTED_BY | 3,542 |
| Source | 2,965 | HAS_ATTACK_TYPE | 1,649 |
| TargetOrg | 380 | TARGETED | 1,632 |
| Area | 95 | USED_WEAPON | 1,625 |
| Locality | 43 | OCCURRED_IN | 1,239 |
| Group | 39 | TARGETED_ORG | 1,194 |
| TargetType | 19 | SIMILAR_TO | 928 |
| AttackType | 7 | SAME_ACTOR_NEARBY | 632 |
| WeaponType | 7 | SAME_SOURCE | 607 |
| | | ATTRIBUTED_TO | 326 |
| | | FOLLOWED_BY | 280 |
| | | OCCURRED_AT | 225 |
| | | SAME_MO_LOCAL | 184 |
| | | GTD_RELATED | 118 |
| | | PART_OF | 43 |

`TargetOrg` ignores the placeholders "Not Applicable" and "Civilian(s)" and merges known spelling variants (see `ORG_PLACEHOLDERS` and `ORG_ALIASES` in `src/config.py`). 1,239 of 1,664 events (74%) have an Area, and 225 of them also have a Locality. Place names, spelling aliases and roll-ups live in `src/areas.py`. Each Event also carries a 384-dimension `embedding` property, indexed by the vector index `event_embedding`. 928 SIMILAR_TO links connect 784 events (47%), with a maximum of 5 links per event. 1,324 events (80%) have a `cluster`; the other 340 are noise and have none (31 clusters). Rebuild with `python src/build_graph.py --reset`, then `python src/embed_graph.py`, `python src/similar_links.py` and `python src/cluster_events.py`, because the reset also removes the embeddings, SIMILAR_TO and clusters. `python src/embed_events.py` creates the cached vectors and only needs rerunning if the data or the embedding model changes. Verify with `python src/check_graph.py` (28 checks).