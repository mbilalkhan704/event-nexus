# EventNexus query library

One entry per graph question: the question in plain words, its parameters, example ways a user might ask it, and the Cypher. Built from `docs/graph_schema.md`.

## Conventions

### Users never see or type event IDs
- Users describe events in words ("the most severe incident in the last 5 years", "the second one", "that attack"). They never type an ID.
- Every query that returns events returns their ids in columns that **start with an underscore** (`_ref`, `_ref_a`, `_refs` ...). These are internal. The app removes them before anything goes to the UI or to the answer-writing LLM.
- To show an event, the app calls the label lookup (Q0c) with the internal refs and builds a readable label such as "12 March 2013, Lyari: bombing, 6 killed", plus the news citations as evidence. The place in a label is the locality and area; if the event has no Area (for example a road), the location text is used, and failing that "Karachi".
- To reach an event, the app uses one of three routes: **(1)** the event finder (Q0b) from a description, **(2)** a hidden list of the previous answer's results ("the second one"), **(3)** a click on a graph node. Queries that need an event take it as `$ref`, `$ref_a`, `$ref_b`, always filled by the app.
- If the finder returns several matches for a vague description, the app shows a short list of labels and asks which one.

### Dates
- Dates are strings `'YYYY-MM-DD'`.
- The data covers **2000-01-17 to 2020-12-22** (Q0a). **Relative periods are anchored to the end of the data, not to today**: "last 5 years" means the 5 years before `data_end`. The app computes `date_from` and `date_to` and the answer must say so ("The data ends in December 2020, so I used 2016 to 2020").
- Requests that fall wholly outside the data range are refused with that reason.

### Places outside the lists
- A place that is in neither the Area nor the Locality list (a road, court, landmark, university) is searched as text in `e.location` and `e.summary_clean`, and the query returns `'text' AS place_match`.
- The app always shows the stored `location` and `summary` text of every event such a query returns (it fetches them with Q0c from the underscore ids), so the user can see how the text states the place.
- The answer says the match is on text and may be incomplete. If nothing is found it says "no event text mentions X, and the data has no coordinates to search by".
- Test result: 12 of 12 returned events were correct, but only 12 events came back from 10 names, so the pre-set count rule failed; the fallback is kept by a later decision (see `DECISIONS.md`).

### Severity
- **Most severe = most victims killed; ties, and events with no deaths, are ranked by victims wounded.**
- Victims killed = `nkill` - `nkillter`; victims wounded = `nwound` - `nwoundte`. GTD's totals include the perpetrators, so ranking by the raw totals would rank clashes in which only attackers died as severe. `nkillter` and `nwoundte` are the perpetrator counts.
- Unknown is not zero. Events with no `nkill` are skipped in severity rankings. If the perpetrator count is unknown, the total is used and the result is flagged (`attacker_deaths_known` is false). If `nwound` is unknown, victims wounded is unknown and counts as 0 for ordering only.
- Ties are possible, so severity questions return the top N and not exactly one event. Answers state this definition.

### Everything else
- Pass **every** parameter a query uses. Use `null` for "no filter".
- Time windows are plain numbers of days; the caller converts units (15 days → `15`, 2 months → `60`, 1 year → `365`).
- `GTD_RELATED` is never used (evaluation only).
- Symmetric links are stored once, so they are matched without direction and de-duplicated with `a.eventid < b.eventid`.
- "Unknown" text values never count as a shared attribute.
- **Stored links have fixed windows:** `SAME_ACTOR_NEARBY` and `SAME_MO_LOCAL` exist only for pairs within 30 days, and `FOLLOWED_BY` within 7 days. Longer windows need the computed variants (Q3b, Q4b).

---

## Tier 0. Helpers (used by the app, not user questions)

### Q0a. Data range

```cypher
MATCH (e:Event)
RETURN min(e.date) AS data_start, max(e.date) AS data_end, count(e) AS events;
```

### Q0b. Event finder: find events by description

Resolves "the most severe incident in the last 5 years", "the Lyari bombing in March 2013", "recent TTP attacks". Also answers ranking questions directly.

Parameters: `$date_from`, `$date_to`, `$area`, `$group`, `$attack_type`, `$weapon_type`, `$target_type` (each or null), `$order` (`'severity'`, `'newest'` or `'oldest'`), `$limit`

Example phrasings: "Tell me the most severe incident in the last 5 years." / "What was the deadliest bombing in Lyari?" / "Show the most recent attacks by TTP." / "Which attack in 2013 hurt the most people?"

```cypher
MATCH (e:Event)
WHERE ($date_from   IS NULL OR e.date >= date($date_from))
  AND ($date_to     IS NULL OR e.date <= date($date_to))
  AND ($attack_type IS NULL OR e.attack_type = $attack_type)
  AND ($weapon_type IS NULL OR e.weapon_type = $weapon_type)
  AND ($target_type IS NULL OR e.target_type = $target_type)
  AND ($area  IS NULL OR EXISTS { (e)-[:OCCURRED_IN]->(:Area {name: $area}) })
  AND ($group IS NULL OR EXISTS { (e)-[:ATTRIBUTED_TO]->(:Group {name: $group}) })
  AND ($order <> 'severity' OR e.nkill IS NOT NULL)
OPTIONAL MATCH (e)-[:OCCURRED_IN]->(a:Area)
WITH e, a,
     CASE WHEN e.nkill  IS NULL THEN null ELSE e.nkill  - coalesce(e.nkillter, 0) END AS victims_killed,
     CASE WHEN e.nwound IS NULL THEN null ELSE e.nwound - coalesce(e.nwoundte, 0) END AS victims_wounded
RETURN e.eventid AS _ref, e.date AS date, a.name AS area, e.location AS location,
       e.attack_type AS attack_type,
       victims_killed, victims_wounded,
       e.nkill AS killed_total, e.nkillter AS attackers_killed,
       e.nkillter IS NOT NULL AS attacker_deaths_known,
       e.summary_clean AS summary,
       COLLECT { MATCH (e)-[:REPORTED_BY]->(s:Source) RETURN s.citation } AS sources
ORDER BY CASE WHEN $order = 'severity' THEN victims_killed END DESC,
         CASE WHEN $order = 'severity' THEN coalesce(victims_wounded, 0) END DESC,
         CASE WHEN $order = 'oldest' THEN e.date END ASC,
         e.date DESC
LIMIT $limit;
```

### Q0c. Label lookup (turns internal refs into readable labels)

Parameters: `$refs` (list of internal ids)

```cypher
MATCH (e:Event) WHERE e.eventid IN $refs
OPTIONAL MATCH (e)-[:OCCURRED_IN]->(a:Area)
OPTIONAL MATCH (e)-[:OCCURRED_AT]->(l:Locality)
RETURN e.eventid AS _ref, e.date AS date, a.name AS area, l.name AS locality,
       e.location AS location, e.attack_type AS attack_type,
       CASE WHEN e.nkill  IS NULL THEN null ELSE e.nkill  - coalesce(e.nkillter, 0) END AS victims_killed,
       CASE WHEN e.nwound IS NULL THEN null ELSE e.nwound - coalesce(e.nwoundte, 0) END AS victims_wounded,
       e.nkillter AS attackers_killed,
       e.summary_clean AS summary;
```

---

## Tier 1. Lookup

### Q1. Details of one event and the sources behind it

`$ref` comes from the finder, the previous answer, or a graph click.

Parameters: `$ref`

Example phrasings (the app resolves "which event" first): "Tell me more about the second one." / "What are the sources for that attack?" / "Give me the full details of the deadliest incident."

```cypher
MATCH (e:Event {eventid: $ref})
OPTIONAL MATCH (e)-[:OCCURRED_IN]->(a:Area)
OPTIONAL MATCH (e)-[:OCCURRED_AT]->(l:Locality)
RETURN e.eventid AS _ref, e.date AS date, e.date_approx AS date_approx,
       e.summary_clean AS summary, e.location AS location,
       a.name AS area, l.name AS locality,
       e.attack_type AS attack_type, e.weapon_type AS weapon_type,
       e.target_type AS target_type, e.target_org AS target_org,
       CASE WHEN e.nkill  IS NULL THEN null ELSE e.nkill  - coalesce(e.nkillter, 0) END AS victims_killed,
       CASE WHEN e.nwound IS NULL THEN null ELSE e.nwound - coalesce(e.nwoundte, 0) END AS victims_wounded,
       e.nkill AS killed_total, e.nkillter AS attackers_killed,
       [(e)-[r:ATTRIBUTED_TO]->(g:Group) | {group: g.name, claimed: r.claimed, uncertain: r.uncertain}] AS attribution,
       COLLECT { MATCH (e)-[:REPORTED_BY]->(s:Source) RETURN s.citation } AS sources;
```

### Q2. Events attributed to group G

Parameters: `$group`, `$date_from`, `$date_to`

Example phrasings: "List all TTP attacks." / "What did Lashkar-e-Jhangvi do after 2013?" / "Events by MQM between 2010 and 2012."

```cypher
MATCH (e:Event)-[r:ATTRIBUTED_TO]->(g:Group {name: $group})
WHERE ($date_from IS NULL OR e.date >= date($date_from))
  AND ($date_to   IS NULL OR e.date <= date($date_to))
OPTIONAL MATCH (e)-[:OCCURRED_IN]->(a:Area)
RETURN e.eventid AS _ref, e.date AS date, e.attack_type AS attack_type,
       a.name AS area, r.claimed AS claimed, r.uncertain AS uncertain
ORDER BY e.date;
```

---

## Tier 2. Cross-event patterns

### Q3. Campaigns: events by the same group close together in time (stored links, up to 30 days)

Parameters: `$group` (or null), `$max_gap_days` (at most 30 here), `$date_from`, `$date_to`

Example phrasings: "Which TTP attacks happened within 15 days of each other?" / "Show attack waves by any group." / "Campaigns in 2014."

```cypher
MATCH (a:Event)-[r:SAME_ACTOR_NEARBY]-(b:Event)
WHERE a.eventid < b.eventid
  AND r.gap_days <= $max_gap_days
  AND ($date_from IS NULL OR (a.date >= date($date_from) AND b.date >= date($date_from)))
  AND ($date_to   IS NULL OR (a.date <= date($date_to)   AND b.date <= date($date_to)))
MATCH (a)-[:ATTRIBUTED_TO]->(g:Group)
WHERE $group IS NULL OR g.name = $group
RETURN g.name AS group, a.eventid AS _ref_a, b.eventid AS _ref_b,
       r.gap_days AS gap_days, r.strength AS strength, r.evidence AS evidence
ORDER BY g.name, gap_days;
```

### Q3b. Same, for any window (computed, not from stored links)

Use for windows above 30 days (for example "within 2 months" = 60). No `strength` or `evidence`.

Parameters: `$group` (or null), `$max_gap_days`, `$date_from`, `$date_to`

```cypher
MATCH (a:Event)-[:ATTRIBUTED_TO]->(g:Group)<-[:ATTRIBUTED_TO]-(b:Event)
WHERE a.eventid < b.eventid
  AND ($group IS NULL OR g.name = $group)
  AND abs(duration.inDays(a.date, b.date).days) <= $max_gap_days
  AND ($date_from IS NULL OR (a.date >= date($date_from) AND b.date >= date($date_from)))
  AND ($date_to   IS NULL OR (a.date <= date($date_to)   AND b.date <= date($date_to)))
RETURN g.name AS group, a.eventid AS _ref_a, b.eventid AS _ref_b,
       abs(duration.inDays(a.date, b.date).days) AS gap_days
ORDER BY g.name, gap_days;
```

### Q4. Local modus operandi: same attack, weapon and target type in the same neighbourhood (stored links, up to 30 days)

Parameters: `$area`, `$attack_type`, `$weapon_type`, `$target_type` (each or null), `$max_gap_days` (at most 30 here), `$date_from`, `$date_to`

Example phrasings: "Repeated bombings in Orangi." / "Same method used twice in Lyari within 10 days." / "Where were police shot the same way more than once?"

```cypher
MATCH (a:Event)-[r:SAME_MO_LOCAL]-(b:Event)
WHERE a.eventid < b.eventid
  AND r.gap_days <= $max_gap_days
  AND ($date_from IS NULL OR (a.date >= date($date_from) AND b.date >= date($date_from)))
  AND ($date_to   IS NULL OR (a.date <= date($date_to)   AND b.date <= date($date_to)))
MATCH (a)-[:OCCURRED_IN]->(ar:Area)
WHERE ($area        IS NULL OR ar.name = $area)
  AND ($attack_type IS NULL OR a.attack_type = $attack_type)
  AND ($weapon_type IS NULL OR a.weapon_type = $weapon_type)
  AND ($target_type IS NULL OR a.target_type = $target_type)
RETURN ar.name AS area, a.eventid AS _ref_a, b.eventid AS _ref_b,
       a.attack_type AS attack_type, a.weapon_type AS weapon_type, a.target_type AS target_type,
       r.gap_days AS gap_days, r.same_locality AS same_locality, r.evidence AS evidence
ORDER BY ar.name, gap_days;
```

### Q4b. Same, for any window (computed)

Parameters: same as Q4, with `$max_gap_days` of any size.

```cypher
MATCH (a:Event)-[:OCCURRED_IN]->(ar:Area)<-[:OCCURRED_IN]-(b:Event)
WHERE a.eventid < b.eventid
  AND a.attack_type = b.attack_type AND a.attack_type <> 'Unknown'
  AND a.weapon_type = b.weapon_type AND a.weapon_type <> 'Unknown'
  AND a.target_type = b.target_type AND a.target_type <> 'Unknown'
  AND abs(duration.inDays(a.date, b.date).days) <= $max_gap_days
  AND ($area        IS NULL OR ar.name = $area)
  AND ($attack_type IS NULL OR a.attack_type = $attack_type)
  AND ($weapon_type IS NULL OR a.weapon_type = $weapon_type)
  AND ($target_type IS NULL OR a.target_type = $target_type)
  AND ($date_from IS NULL OR (a.date >= date($date_from) AND b.date >= date($date_from)))
  AND ($date_to   IS NULL OR (a.date <= date($date_to)   AND b.date <= date($date_to)))
RETURN ar.name AS area, a.eventid AS _ref_a, b.eventid AS _ref_b,
       a.attack_type AS attack_type, a.weapon_type AS weapon_type, a.target_type AS target_type,
       abs(duration.inDays(a.date, b.date).days) AS gap_days
ORDER BY ar.name, gap_days;
```

### Q5. Events reported by the same article

Returns the facts only: gap in days, whether the events share an area, and GTD's own `multiple` flag **for display**. The query does not decide whether the events form "one coordinated attack"; the reader or the answer-writing LLM judges that from these facts. Any future rule for it would be recorded in `DECISIONS.md` and must not use `multiple`, which is display-only.

Parameters: `$ref` (or null for all pairs)

Example phrasings: "Which attacks were reported by the same news article?" / "Were these two bombings covered together?" / "What else was reported alongside that attack?"

```cypher
MATCH (a:Event)-[r:SAME_SOURCE]-(b:Event)
WHERE a.eventid < b.eventid
  AND ($ref IS NULL OR a.eventid = $ref OR b.eventid = $ref)
RETURN a.eventid AS _ref_a, b.eventid AS _ref_b,
       r.strength AS shared_citations, r.evidence AS evidence,
       abs(duration.inDays(a.date, b.date).days) AS gap_days,
       EXISTS { (a)-[:OCCURRED_IN]->(:Area)<-[:OCCURRED_IN]-(b) } AS same_area,
       a.multiple AS multiple_a, b.multiple AS multiple_b
ORDER BY shared_citations DESC, gap_days;
```

### Q6. Groups hitting the same target type close together in time

Parameters: `$window_days` (any number; null = no time limit), `$target_type` (or null), `$date_from`, `$date_to`

Example phrasings: "Which groups attacked police within 15 days of each other?" / "Groups that targeted the same kind of victim within 2 months." / "Same target type, same year."

```cypher
MATCH (e1:Event)-[:ATTRIBUTED_TO]->(g1:Group),
      (e2:Event)-[:ATTRIBUTED_TO]->(g2:Group),
      (e1)-[:TARGETED]->(t:TargetType)<-[:TARGETED]-(e2)
WHERE g1.name < g2.name
  AND ($window_days IS NULL OR abs(duration.inDays(e1.date, e2.date).days) <= $window_days)
  AND ($target_type IS NULL OR t.name = $target_type)
  AND ($date_from IS NULL OR (e1.date >= date($date_from) AND e2.date >= date($date_from)))
  AND ($date_to   IS NULL OR (e1.date <= date($date_to)   AND e2.date <= date($date_to)))
RETURN t.name AS target_type, g1.name AS group_a, g2.name AS group_b,
       count(*) AS event_pairs,
       collect(DISTINCT e1.eventid)[0..5] AS _refs_a,
       collect(DISTINCT e2.eventid)[0..5] AS _refs_b
ORDER BY event_pairs DESC;
```

### Q7. Neighbourhoods attacked by several groups, in order of first appearance

Parameters: `$min_groups` (2 or more), `$date_from`, `$date_to`

Example phrasings: "Which areas were hit by more than one group?" / "Who attacked Lyari first, and who came after?" / "Contested neighbourhoods since 2010."

```cypher
MATCH (e:Event)-[:OCCURRED_IN]->(a:Area), (e)-[:ATTRIBUTED_TO]->(g:Group)
WHERE ($date_from IS NULL OR e.date >= date($date_from))
  AND ($date_to   IS NULL OR e.date <= date($date_to))
WITH a, g, min(e.date) AS first_seen, count(e) AS events, collect(e.eventid)[0..5] AS _example_refs
ORDER BY first_seen
WITH a, collect({group: g.name, first_seen: first_seen, events: events, _example_refs: _example_refs}) AS groups
WHERE size(groups) >= $min_groups
RETURN a.name AS area, size(groups) AS group_count, groups
ORDER BY group_count DESC;
```

---

## Tier 3. Chains and multi-hop

### Q8. Everything reachable from one event within 3 steps, with the reason for each step

Shortest path to each reached event. On the busiest event (degree 24) it reaches 182 events within 3 hops.

Parameters: `$ref`, `$limit`

Example phrasings: "What is connected to that attack?" / "Show everything within three links of the deadliest incident and why."

```cypher
MATCH p = (x:Event {eventid: $ref})
          -[:SAME_ACTOR_NEARBY|SAME_SOURCE|SAME_MO_LOCAL|FOLLOWED_BY|SIMILAR_TO*1..3]-
          (y:Event)
WHERE y <> x
WITH y, p ORDER BY length(p)
WITH y, head(collect(p)) AS best
RETURN y.eventid AS _ref, y.date AS date, length(best) AS hops,
       [n IN nodes(best) | n.eventid] AS _via_refs,
       [r IN relationships(best) | {type: type(r), rule: r.rule, strength: r.strength, evidence: r.evidence}] AS reasons
ORDER BY hops, date
LIMIT $limit;
```

### Q9. Escalation sequences: chains of 3+ events in one neighbourhood, each within 7 days of the last

Parameters: `$area` (or null), `$date_from`, `$date_to`, `$limit`

Example phrasings: "Show escalation chains in Orangi." / "Longest runs of attacks in the same area." / "Escalations in 2014."

```cypher
MATCH p = (a:Event)-[:FOLLOWED_BY*2..]->(b:Event)
WHERE NOT EXISTS { ()-[:FOLLOWED_BY]->(a) }
  AND NOT EXISTS { (b)-[:FOLLOWED_BY]->() }
  AND ($date_from IS NULL OR a.date >= date($date_from))
  AND ($date_to   IS NULL OR b.date <= date($date_to))
MATCH (a)-[:OCCURRED_IN]->(ar:Area)
WHERE $area IS NULL OR ar.name = $area
RETURN ar.name AS area, length(p) + 1 AS events, a.date AS start_date, b.date AS end_date,
       [n IN nodes(p) | n.eventid] AS _refs
ORDER BY events DESC
LIMIT $limit;
```

### Q10. Shortest explanation path between two events

No rows means no path within 6 hops.

Parameters: `$ref_a`, `$ref_b`

Example phrasings: "How are these two attacks connected?" / "Find the link between the first and the third one."

```cypher
MATCH (a:Event {eventid: $ref_a}), (b:Event {eventid: $ref_b})
WHERE a <> b
MATCH p = shortestPath((a)-[:SAME_ACTOR_NEARBY|SAME_SOURCE|SAME_MO_LOCAL|FOLLOWED_BY|SIMILAR_TO*..6]-(b))
RETURN length(p) AS hops,
       [n IN nodes(p) | n.eventid] AS _via_refs,
       [r IN relationships(p) | {type: type(r), rule: r.rule, strength: r.strength, evidence: r.evidence}] AS reasons;
```

### Q11. Group co-activity network

Groups linked through shared neighbourhoods, shared target organisations, and (optionally) shared target types. Target type is coarse: it links 304 of the 741 possible group pairs, so it is **off by default**.

Parameters: `$min_shared` (for example 2), `$include_target_type` (true or false)

Example phrasings: "Which groups operate in the same areas?" / "Show how groups overlap." / "Groups that attack the same organisations."

```cypher
CALL {
  MATCH (g1:Group)<-[:ATTRIBUTED_TO]-(:Event)-[:OCCURRED_IN]->(x:Area)<-[:OCCURRED_IN]-(:Event)-[:ATTRIBUTED_TO]->(g2:Group)
  WHERE g1.name < g2.name
  RETURN g1.name AS group_a, g2.name AS group_b, 'area' AS via,
         count(DISTINCT x) AS shared, collect(DISTINCT x.name)[0..5] AS examples
  UNION ALL
  MATCH (g1:Group)<-[:ATTRIBUTED_TO]-(:Event)-[:TARGETED_ORG]->(x:TargetOrg)<-[:TARGETED_ORG]-(:Event)-[:ATTRIBUTED_TO]->(g2:Group)
  WHERE g1.name < g2.name
  RETURN g1.name AS group_a, g2.name AS group_b, 'target_org' AS via,
         count(DISTINCT x) AS shared, collect(DISTINCT x.name)[0..5] AS examples
  UNION ALL
  MATCH (g1:Group)<-[:ATTRIBUTED_TO]-(:Event)-[:TARGETED]->(x:TargetType)<-[:TARGETED]-(:Event)-[:ATTRIBUTED_TO]->(g2:Group)
  WHERE g1.name < g2.name AND $include_target_type
  RETURN g1.name AS group_a, g2.name AS group_b, 'target_type' AS via,
         count(DISTINCT x) AS shared, collect(DISTINCT x.name)[0..5] AS examples
}
WITH group_a, group_b, via, shared, examples
WHERE shared >= $min_shared
RETURN group_a, group_b, via, shared, examples
ORDER BY shared DESC;
```

---

## Tier 4. Provenance

### Q12. Why are these two events linked?

Direct links first, then shared sources. Empty `links` and no shared sources means no direct link: use Q10 for an indirect explanation. `GTD_RELATED` is excluded on purpose.

Parameters: `$ref_a`, `$ref_b`

Example phrasings: "Why are these two attacks linked?" / "What connects the first and second incident?"

```cypher
MATCH (a:Event {eventid: $ref_a}), (b:Event {eventid: $ref_b})
OPTIONAL MATCH (a)-[r]-(b)
WHERE type(r) <> 'GTD_RELATED'
WITH a, b,
     collect(CASE WHEN r IS NULL THEN NULL
                  ELSE {type: type(r), rule: r.rule, strength: r.strength,
                        evidence: r.evidence, gap_days: r.gap_days} END) AS links
RETURN a.eventid AS _ref_a, b.eventid AS _ref_b, links,
       COLLECT { MATCH (a)-[:REPORTED_BY]->(s:Source)<-[:REPORTED_BY]-(b) RETURN s.citation } AS shared_sources;
```

### Q13. For group G: claimed vs suspected vs attributed events, with sources

GTD has no "confirmed" flag, so the third status is called **attributed, not flagged suspected**. Priority: `claimed` first, then `suspected`. Nine events are both claimed and flagged suspected; they show as `claimed`, and the raw flags are returned too.

Parameters: `$group`

Example phrasings: "How solid are the TTP attributions?" / "Which Lashkar-e-Jhangvi events were actually claimed?" / "Show suspected versus claimed events for MQM."

```cypher
MATCH (e:Event)-[r:ATTRIBUTED_TO]->(g:Group {name: $group})
RETURN CASE WHEN r.claimed   IN [1, true] THEN 'claimed'
            WHEN r.uncertain IN [1, true] THEN 'suspected'
            ELSE 'attributed, not flagged suspected' END AS status,
       e.eventid AS _ref, e.date AS date,
       r.claimed AS claimed_flag, r.uncertain AS uncertain_flag,
       COLLECT { MATCH (e)-[:REPORTED_BY]->(s:Source) RETURN s.citation } AS sources
ORDER BY status, e.date;
```

---

## Tier 5. Similarity for the unattributed events

### Q14. Events most similar to one event, with reasons

Uses the vector index, so it works for all events (`SIMILAR_TO` links cover only about 47%). Cosine = `2*score - 1`, which matches the stored `SIMILAR_TO` values.

Parameters: `$ref`, `$k`

Example phrasings: "Find attacks like that one." / "What other incidents look similar to the deadliest bombing?" / "Show the 5 most similar events and why."

```cypher
MATCH (x:Event {eventid: $ref})
CALL db.index.vector.queryNodes('event_embedding', $k + 1, x.embedding) YIELD node AS y, score
WHERE y <> x
  AND NOT (x.dup_group IS NOT NULL AND y.dup_group = x.dup_group)
WITH x, y, 2 * score - 1 AS cosine
RETURN y.eventid AS _ref, y.date AS date, round(cosine, 3) AS cosine,
       abs(duration.inDays(x.date, y.date).days) AS gap_days,
       EXISTS { (x)-[:OCCURRED_IN]->(:Area)<-[:OCCURRED_IN]-(y) } AS same_area,
       (x.attack_type = y.attack_type AND x.attack_type <> 'Unknown') AS same_attack_type,
       (x.weapon_type = y.weapon_type AND x.weapon_type <> 'Unknown') AS same_weapon_type,
       (x.target_type = y.target_type AND x.target_type <> 'Unknown') AS same_target_type,
       EXISTS { (x)-[:ATTRIBUTED_TO]->(:Group)<-[:ATTRIBUTED_TO]-(y) } AS same_group,
       EXISTS { (x)-[:REPORTED_BY]->(:Source)<-[:REPORTED_BY]-(y) } AS shared_source,
       EXISTS { (x)-[:SIMILAR_TO]-(y) } AS has_similar_to_link
ORDER BY cosine DESC
LIMIT $k;
```

### Q15. Unattributed events that resemble events attributed to group G

The output is always "resembles", never attribution. Whoever shows this result must keep that wording.

Parameters: `$group`, `$k` (neighbours per attributed event), `$min_cosine` (for example 0.85), `$limit`

Example phrasings: "Which unattributed attacks look like TTP attacks?" / "Events that resemble Lashkar-e-Jhangvi but have no group."

```cypher
MATCH (e:Event)-[:ATTRIBUTED_TO]->(:Group {name: $group})
CALL (e) {
  CALL db.index.vector.queryNodes('event_embedding', $k, e.embedding) YIELD node AS u, score
  RETURN u, 2 * score - 1 AS cosine
}
WITH e, u, cosine
WHERE cosine >= $min_cosine
  AND u <> e
  AND NOT EXISTS { (u)-[:ATTRIBUTED_TO]->(:Group) }
RETURN u.eventid AS _ref, u.date AS date,
       'resembles' AS relation, $group AS resembles_group,
       count(DISTINCT e) AS resembling_events,
       round(max(cosine), 3) AS best_cosine,
       collect(DISTINCT e.eventid)[0..5] AS _example_refs
ORDER BY resembling_events DESC, best_cosine DESC
LIMIT $limit;
```

---

## Verified assumptions

- `eventid` is INTEGER and `date` is DATE.
- `claimed` and `uncertain` are BOOLEAN. Counts: claimed only 161, neither 88, suspected only 68, both 9 (total 326).
- `dup_group` is set for every event (twins share a value, the rest are unique), so the twin-exclusion in Q14 and Q15 works.
- Vector index `event_embedding` is ONLINE. Stored cosine 0.9265 equals `2*score - 1` = 0.9265.
- Neo4j 2026.09.0; `COLLECT { }` and `CALL (e) { }` both ran.
- Q8 on the busiest event (degree 24) reached 182 events within 3 hops.
- `nkill`, `nwound` and `eventid` are INTEGER. In the raw data `nkillter` is missing for 5 events and `nwoundte` for 7; 100 events have perpetrator deaths.
- Severity for 2016-2020 (top 5 by victims killed): 5, 4, 4, 4, 4. The Stock Exchange attack (7 killed, 4 of them attackers) and the Rangers convoy clash (6 killed, all attackers) no longer rank.

## Expected results

Reference results for the graph described in `graph_schema.md` and `DECISIONS.md`, used to verify the queries.

| Query | Parameters | Expected |
|---|---|---|
| Q0a | none | 2000-01-17, 2020-12-22, 1,664 events |
| Q0b | `order` 'severity', `limit` 5, `date_from` '2015-12-23', `date_to` '2020-12-22', rest null | 5 rows; `victims_killed` 5, 4, 4, 4, 4; the first is in Nazimabad on 2016-10-29 |
| Q2 | TTP, no dates | 150 rows |
| Q3 | no group, `max_gap_days` 30, no dates | 632 rows |
| Q3b | no group, `max_gap_days` 7 / 30 / 90 | 236 / 632 / 1,446 rows |
| Q4 | all filters null, `max_gap_days` 30 | 184 rows |
| Q4b | all filters null, `max_gap_days` 30 | about 184 (may differ slightly from the stored-link count) |
| Q5 | `ref` null | 607 rows |
| Q9 | no filters, `limit` 5 | longest chain 14 events, from 20 Jan 2014 to 24 Feb 2014 |
| Q13 | TTP | 72 claimed |
| Q14 | an event that has a `SIMILAR_TO` link | its neighbour appears with `has_similar_to_link = true` |