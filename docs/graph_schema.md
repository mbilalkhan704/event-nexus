# Graph schema

The graph is built backwards from 15 questions (lookup, cross-event patterns, multi-hop chains, provenance, similarity). Of these, 12 are about connections between events. Every structure below exists to answer at least one of them.

## Map

```
Event -[ATTRIBUTED_TO {claimed, uncertain}]-> Group
Event -[HAS_ATTACK_TYPE]-> AttackType
Event -[USED_WEAPON]-> WeaponType
Event -[TARGETED]-> TargetType
Event -[TARGETED_ORG]-> TargetOrg
Event -[OCCURRED_IN {method, confidence}]-> Area
Event -[REPORTED_BY {dbsource}]-> Source

Event -[SAME_ACTOR_NEARBY | SAME_SOURCE | SAME_MO_LOCAL | FOLLOWED_BY | SIMILAR_TO | GTD_RELATED]- Event
```

## Nodes

| Node | Key | Source | Phase |
|---|---|---|---|
| `Event` | `eventid` | Cleaned table. Properties: `date`, `date_approx`, `summary_clean`, `location`, `nkill`, `nwound`, `success`, `suicide`, `multiple`, `doubtterr`, `actor_known`, `dup_group`; later `embedding` and `cluster` | 3 |
| `Group` | `name` | `gname`, only when `actor_known` | 3 |
| `AttackType` | `name` | `attacktype1_txt` | 3 |
| `WeaponType` | `name` | `weaptype1_txt` (the subtype stays a property on the edge) | 3 |
| `TargetType` | `name` | `targtype1_txt` | 3 |
| `TargetOrg` | `name` | `corp1` | 3 |
| `Source` | `citation` | `scite1` to `scite3` | 3 |
| `Area` | `name` | Neighbourhoods extracted from `location` and the summary | 4 |

## Event-to-attribute relationships

| Relationship | Properties | Notes |
|---|---|---|
| `ATTRIBUTED_TO` | `claimed`, `uncertain` | Confidence lives on the link, not on the group |
| `HAS_ATTACK_TYPE`, `USED_WEAPON`, `TARGETED`, `TARGETED_ORG` | | |
| `OCCURRED_IN` | `method` (pattern or GLiNER), `confidence` | |
| `REPORTED_BY` | `dbsource` | |

**Unknown means no edge.** An event whose weapon, target, organisation or group is "Unknown" simply has no edge of that kind. The text value stays on the event for display.

## Derived cross-event links

Each link stores `rule`, `strength` and `evidence` (which attributes matched). Symmetric links are stored once, from the earlier event to the later one, and queried without direction.

| Link | Rule | Phase |
|---|---|---|
| `SAME_ACTOR_NEARBY` | Same known group within 30 days. `gap_days` stored. Sizing: 236 pairs within 7 days, 632 within 30, 1,446 within 90 | 3 |
| `SAME_SOURCE` | Share a citation shared by 2 to 10 events. Strength is the number of shared citations. Sizing: 411 citations shared by 2+ events, covering 664 events (40%); the largest is shared by 7 | 3 |
| `SAME_MO_LOCAL` | Same attack type, weapon type and target type, same Area, within 30 days | 4 |
| `FOLLOWED_BY` | Same Area, within 7 days, directed earlier to later, with `gap_days` | 4 |
| `SIMILAR_TO` | Top 5 embedding neighbours per event, with a similarity score and a cut-off set in Phase 5 | 5 |
| `GTD_RELATED` | GTD's own related pairs (118 in-scope pairs, 111 with different text). **Evaluation only** | 3 |

## Design principles

1. **Unknown is not a link.** Unknown values and generic group labels ("Unknown", "Gunmen") never create edges.
2. **Confidence lives on edges,** not nodes.
3. **`GTD_RELATED` never feeds the system.** It is not used to build links, retrieve results or train models.
4. **`multiple` is a property only,** not a link rule or model feature.
5. **Every derived link can explain itself** through its `rule`, `strength` and `evidence`.

## Rule parameters

All windows and thresholds live in `src/config.py` so tuning never means rewriting rules:

```python
GRAPH_RULES = {
    "same_actor_window_days": 30,
    "same_mo_window_days": 30,
    "followed_by_window_days": 7,
    "source_max_events": 10,
    "similar_top_k": 5,
}
```

## Constraints and indexes

| Type | On | Phase |
|---|---|---|
| Uniqueness | `Event.eventid`, `Group.name`, `AttackType.name`, `WeaponType.name`, `TargetType.name`, `TargetOrg.name`, `Source.citation`, `Area.name` | 3 (Area in 4) |
| Range index | `Event.date` | 3 |
| Vector index | `Event.embedding` (384 dimensions, cosine) | 5 |
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

## Naming conventions

Node labels are PascalCase, relationship types are UPPER_SNAKE_CASE, and properties are snake_case.