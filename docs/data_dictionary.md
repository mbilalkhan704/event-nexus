# Data dictionary

## Source and scope

- **Source:** Global Terrorism Database (GTD), maintained by START at the University of Maryland. The raw data is not included in this repository.
- **Scope:** incidents in Karachi, 2000 to 2020 (1,664 events). Karachi means a city name containing "karachi" (any spelling), or an event in Sindh whose coordinates fall inside Karachi's bounding box (latitude 24.7 to 25.2, longitude 66.8 to 67.4). This also captures events filed under district names such as North Nazimabad, Gadap and Korangi.
- **Why 2000 onward:** incident summaries exist only from 2000. Earlier events have almost no text, and most have an unknown perpetrator.
- **File:** `data/processed/karachi_events_clean.parquet` (1,664 rows, 40 columns).

## Columns kept from GTD (32)

| Column | Meaning | Role in the graph |
|---|---|---|
| `eventid` | Unique 12-digit event ID (an identifier, not a date) | Key of the `Event` node |
| `iyear`, `imonth`, `iday` | Year, month and day of the incident (0 means unknown) | Combined into `date` |
| `city` | City of the incident (set to "Karachi" for all rows, see `city_raw`) | Constant |
| `location` | Free-text note about the specific location (83% filled) | Main text source for place extraction (Area and Locality) |
| `gname` | Perpetrator group as recorded by GTD ("Unknown" for about 80% of events) | `Group` node, only when the actor is known |
| `guncertain1` | 1 if the attribution to the group is suspected rather than confirmed | Property `uncertain` on the `ATTRIBUTED_TO` edge |
| `claimed` | Whether a group claimed responsibility (1 yes, 0 no, missing unknown) | Property `claimed` on the `ATTRIBUTED_TO` edge |
| `attacktype1_txt` | Primary attack type | `AttackType` node; classifier label candidate |
| `weaptype1_txt` | Primary weapon category | `WeaponType` node |
| `weapsubtype1_txt` | Weapon subtype | Property `subtype` on the `USED_WEAPON` edge |
| `weapdetail` | Free-text weapon description (50% filled) | Event property `weapon_detail` (display) |
| `targtype1_txt` | Primary target category | `TargetType` node |
| `targsubtype1_txt` | Target subcategory | Property `subtype` on the `TARGETED` edge |
| `corp1` | Organisation targeted | `TargetOrg` node (placeholders ignored, spelling variants merged) |
| `target1` | Description of the specific target or victim | Event property `target_desc` (display) |
| `nkill` | Total confirmed fatalities, victims and perpetrators together | Event property |
| `nwound` | Confirmed non-fatal injuries | Event property |
| `nkillter` | Perpetrators killed, included in `nkill`. Missing for 5 events | Event property; severity uses `nkill` − `nkillter` |
| `nwoundte` | Perpetrators wounded, included in `nwound`. Missing for 7 events | Event property; severity uses `nwound` − `nwoundte` |
| `success` | Whether the attack achieved its immediate objective, as GTD defines it per attack type | Event property |
| `suicide` | 1 if a suicide attack | Event property |
| `multiple` | 1 if the event is part of a multiple (coordinated) incident | Event property only; not a link rule or model feature, because it reflects GTD's own relatedness judgement |
| `related` | IDs of events that GTD analysts marked as related (10% filled) | `GTD_RELATED` links, used for evaluation only |
| `doubtterr` | 1 if there is doubt the incident meets GTD's terrorism criteria | Event property (quality flag) |
| `summary` | GTD's narrative description of the event | Original text; `summary_clean` is used for NLP |
| `motive` | Stated or inferred motive (44% filled) | Event property (display) |
| `scite1`, `scite2`, `scite3` | Source citations (news articles); 100%, 70% and 44% filled | `Source` nodes (`REPORTED_BY`), the evidence trail |
| `dbsource` | The data source that supplied the record | Property on the `REPORTED_BY` edge |

## Columns added by cleaning (8)

| Column | Meaning |
|---|---|
| `city_raw` | The original `city` value (spelling variants and district names) |
| `date` | Single date built from year, month and day |
| `date_approx` | True if the exact day or month was unknown, or the summary says "(Default Date)" |
| `actor_known` | False when `gname` is "Unknown" or "Gunmen" (generic labels, not real groups) |
| `summary_clean` | `summary` without the leading date prefix, used for NLP |
| `dup_group` | ID shared by events with identical `summary_clean`. Every event has one; it is unique to the event unless the text is shared. Mostly same-day twin records, plus two groups of separate incidents with templated wording. Use it to keep these events together when splitting data for models. Nine groups in total, each of 2 events, all with identical text. They are excluded from SIMILAR_TO. |
| `related_ids` | `related` parsed into a list of integer event IDs, without the event's own ID |
| `related_in_scope` | The subset of `related_ids` that exists in this dataset |

## Derived later (not stored in this file)

- **Area and Locality:** assigned to each event during the graph build by `src/areas.py`, from `location`, `city_raw` and the summary. 74% of events (1,239 of 1,664) receive an Area, and 225 of them also receive a more specific Locality. See `docs/area_evaluation.md`.
- **Graph links between events:** built by `src/build_graph.py` (see `docs/graph_schema.md`).
- **Embeddings and clusters:** `data/processed/event_embeddings.npz` holds the event IDs and a 384-dimension vector per summary (`src/embed_events.py`). The vectors, a `cluster` number (unset for noise) and the similarity links are written to the graph. The 2-D map coordinates are in `data/processed/event_map.json`. See `docs/graph_schema.md`.

## Cleaning rules

1. Keep only the 32 chosen columns. The rest are mostly empty or redundant.
2. Keep the original city as `city_raw`, then set `city` to "Karachi". This fixes spelling variants, and `city_raw` keeps district names as hints for neighbourhood extraction.
3. Build `date`. A zero month or day becomes 1 and sets `date_approx`.
4. Add `actor_known`. "Unknown" and "Gunmen" are not real groups, and the original `gname` is kept.
5. Turn GTD's negative unknown-codes (for example -9 in `claimed`) into missing values. This applies to `claimed`, `nkill`, `nwound`, `nkillter` and `nwoundte`.
6. Add `summary_clean` by stripping the date prefix, including the "(Default Date)" variant.
7. Keep every event. Identical summaries are marked with `dup_group` and not removed, since they are separate GTD records.
8. Parse `related` into `related_ids` and `related_in_scope`.
9. Leave missing `nkill`, `nwound`, `nkillter` and `nwoundte` missing. Unknown is not the same as zero.

## Known limits of the data

- **Most perpetrators are unknown:** about 80% of events have no named group, so "shared actor" links reach only about a fifth of events.
- **Coordinates carry no area information:** 1,627 of 1,664 events share one city-centre point, so latitude, longitude and specificity were dropped. Neighbourhoods have to be extracted from `location` and the summary text.
- **Short summaries:** they average about 300 characters (roughly 50 words).
- **Labels such as "Unknown" are not evidence of a shared attribute.** They never create links between events.
- **Skewed over time:** about 700 of the 1,664 events fall in 2013 and 2014 (the Karachi surge).
- **Event IDs are not dates:** the date prefix of an `eventid` can differ from the date fields (for example `201402100070` is dated 2014-02-08). Use the `date` column for ordering.
- **Only some events get an Area:** 26% name no recurring place (one-off landmarks, or no place at all), so area-based links reach about three quarters of events.
- **Only the primary attack, weapon and target are kept:** the second and third versions in GTD are under 6% filled.
- **Some group names are broad descriptors,** for example "Sunni Muslim extremists" or "Baloch Nationalists". They are kept as groups, so links through them are weaker than links through a named organisation.
- **Casualty counts include perpetrators:** `nkill` and `nwound` count attackers as well as victims, so rankings use `nkill` − `nkillter` and `nwound` − `nwoundte`. In 100 events at least one attacker was killed. Where a perpetrator count is missing (5 and 7 events), it is treated as unknown and the total is used.

## Rebuilding the dataset

```
python src/convert_to_parquet.py   # raw Excel to Parquet
python src/make_scope.py           # Karachi, 2000 to 2020
python src/clean_data.py           # cleaning and added columns
```

The graph is built from this file; see the README for the graph build steps.