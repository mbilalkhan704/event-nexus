# Data dictionary

## Source and scope

- **Source:** Global Terrorism Database (GTD), maintained by START at the University of Maryland. The raw data is not included in this repository.
- **Scope:** incidents in Karachi, 2000 to 2020 (1,664 events). Karachi means a city name containing "karachi" (any spelling), or an event in Sindh whose coordinates fall inside Karachi's bounding box (latitude 24.7 to 25.2, longitude 66.8 to 67.4). This also captures events filed under district names such as North Nazimabad, Gadap and Korangi.
- **Why 2000 onward:** incident summaries exist only from 2000. Earlier events have almost no text, and most have an unknown perpetrator.
- **File:** `data/processed/karachi_events_clean.parquet` (1,664 rows, 38 columns).

## Columns kept from GTD (30)

| Column | Meaning | Planned role |
|---|---|---|
| `eventid` | Unique 12-digit event ID | Node key for each event |
| `iyear`, `imonth`, `iday` | Year, month and day of the incident (0 means unknown) | Time; combined into `date` |
| `city` | City of the incident (set to "Karachi" for all rows, see `city_raw`) | Constant |
| `location` | Free-text note about the specific location (83% filled) | Text source for neighbourhood extraction |
| `gname` | Perpetrator group as recorded by GTD ("Unknown" for about 80% of events) | Actor link, when known |
| `guncertain1` | 1 if the attribution to the group is suspected rather than confirmed | Attribution confidence |
| `claimed` | Whether a group claimed responsibility (1 yes, 0 no, missing unknown) | Attribution evidence |
| `attacktype1_txt` | Primary attack type | Attack-type link; classifier label candidate |
| `weaptype1_txt` | Primary weapon category | Weapon link |
| `weapsubtype1_txt` | Weapon subtype | Finer weapon link |
| `weapdetail` | Free-text weapon description (50% filled) | Text for entity recognition |
| `targtype1_txt` | Primary target category | Target-type link |
| `targsubtype1_txt` | Target subcategory | Finer target link |
| `corp1` | Organisation targeted | Target organisation |
| `target1` | Description of the specific target or victim | Target description |
| `nkill` | Confirmed fatalities (GTD counts victims and attackers) | Severity |
| `nwound` | Confirmed non-fatal injuries | Severity |
| `success` | Whether the attack achieved its immediate objective, as GTD defines it per attack type | Event property |
| `suicide` | 1 if a suicide attack | Event property |
| `multiple` | 1 if the event is part of a multiple (coordinated) incident | Coordinated-attack hint |
| `related` | IDs of events that GTD analysts marked as related (10% filled) | Evaluation answer key |
| `doubtterr` | 1 if there is doubt the incident meets GTD's terrorism criteria | Quality flag |
| `summary` | GTD's narrative description of the event | Original text |
| `motive` | Stated or inferred motive (44% filled) | Extra text |
| `scite1`, `scite2`, `scite3` | Source citations (news articles); 100%, 70% and 44% filled | Evidence trail |
| `dbsource` | The data source that supplied the record | Evidence trail |

## Columns added by cleaning (8)

| Column | Meaning |
|---|---|
| `city_raw` | The original `city` value (spelling variants and district names) |
| `date` | Single date built from year, month and day |
| `date_approx` | True if the exact day or month was unknown, or the summary says "(Default Date)" |
| `actor_known` | False when `gname` is "Unknown" or "Gunmen" (generic labels, not real groups) |
| `summary_clean` | `summary` without the leading date prefix, used for NLP |
| `dup_group` | ID shared by events with identical `summary_clean`. Mostly same-day twin records, plus two groups of separate incidents with templated wording. Use it to keep these events together when splitting data for models |
| `related_ids` | `related` parsed into a list of integer event IDs, without the event's own ID |
| `related_in_scope` | The subset of `related_ids` that exists in this dataset |

## Cleaning rules

1. Keep only the 30 chosen columns. The rest are mostly empty or redundant.
2. Keep the original city as `city_raw`, then set `city` to "Karachi". This fixes spelling variants, and `city_raw` keeps district names as hints for neighbourhood extraction.
3. Build `date`. A zero month or day becomes 1 and sets `date_approx`.
4. Add `actor_known`. "Unknown" and "Gunmen" are not real groups, and the original `gname` is kept.
5. Turn GTD's negative unknown-codes (for example -9 in `claimed`) into missing values.
6. Add `summary_clean` by stripping the date prefix, including the "(Default Date)" variant.
7. Keep every event. Identical summaries are marked with `dup_group` and not removed, since they are separate GTD records.
8. Parse `related` into `related_ids` and `related_in_scope`.
9. Leave missing `nkill` and `nwound` missing. Unknown is not the same as zero.

## Known limits of the data

- **Most perpetrators are unknown:** about 80% of events have no named group, so "shared actor" links reach only about a fifth of events.
- **Coordinates carry no area information:** 1,627 of 1,664 events share one city-centre point, so latitude, longitude and specificity were dropped. Neighbourhoods have to be extracted from `location` and the summary text.
- **Short summaries:** they average about 300 characters (roughly 50 words).
- **Labels such as "Unknown" are not evidence of a shared attribute.** They never create links between events.
- **Skewed over time:** about 700 events fall in 2013 and 2014 (the Karachi surge), and 1993 is absent from GTD entirely (the records for that year were lost).

## Rebuilding the dataset

```
python src/convert_to_parquet.py   # raw Excel to Parquet
python src/make_scope.py           # Karachi, 2000 to 2020
python src/clean_data.py           # cleaning and added columns
```