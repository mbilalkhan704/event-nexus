# Area extraction evaluation

## Task

Assign each event one primary **Area** (town or neighbourhood level, or a recurring named facility) and, when the text names something more specific, a **Locality** (for example Gulshan-e-Maymar, which belongs to the Area Gadap). Names seen in fewer than 2 events are not accepted as Areas, because they cannot link events.

## Method

Rule-based extractor (`src/areas.py`): patterns over the location text ("in the X area"), the original `city` field, a summary template ("in X area/town"), and a facility pattern, plus a gazetteer of names that appear in at least 2 events. Compared with GLiNER (zero-shot, labels: neighbourhood, locality, landmark) and a hybrid (rules first, GLiNER where rules abstain).

Predictions and labels are passed through the same spelling aliases and roll-up map before they are compared, so a label of Manghopir counts as correct for the Area Orangi. Scores therefore describe the Area level and are not comparable with the finer-grained scoring of the first rounds.

## Data and labelling

- **Development set:** 60 random events (40 with location text, 20 without). Used to tune the extractor.
- **Test set:** 30 fresh events (20 with location text, 10 without), labelled before the final version and scored once.
- Labels are written by the project author from the text only. `Name1|Name2` marks nested places where either level is acceptable. One annotator, no agreement measure.
- Development labels were corrected before any prediction was compared: two labels were swapped, two did not follow the text-only rule, and nested places were given alternatives.
- Two further development labels (Monimabad and Pirabad) were set after the roll-up rules were decided, to match the author's intent.

## Metrics

- **Coverage:** share of events that received an answer.
- **Precision:** correct answers among the answers given.
- **Recall:** correct answers among events with a true place.
- **Recall on recurring places:** the same, restricted to events whose true place appears in 2 or more events.
- **Accuracy:** correct answers plus correct abstentions.

## Results

| Method | Set | Coverage | Precision | Recall | Recall (recurring) | Accuracy |
|---|---|---|---|---|---|---|
| Rules | Dev | 0.65 | 1.00 | 0.81 | 0.95 | 0.85 |
| GLiNER | Dev | 0.57 | 0.97 | 0.69 | 0.80 | 0.73 |
| Hybrid | Dev | 0.67 | 0.97 | 0.81 | 0.95 | 0.83 |
| Rules | Test | 0.70 | 0.95 | 0.77 | 0.95 | 0.80 |
| GLiNER | Test | 0.63 | 0.95 | 0.69 | 0.86 | 0.73 |
| Hybrid | Test | 0.70 | 0.95 | 0.77 | 0.95 | 0.80 |

## Findings

- The rule-based extractor is as precise as GLiNER and finds more places. The hybrid adds nothing, so rules alone are used.
- Most misses are one-off places (a court, a clinic, an airport, a flyover) that cannot link events by design, plus spelling variants (for example "Layari" for Lyari), handled by an alias list.
- One of the six test errors appears to be a labelling slip (gold "T Town" for the text "Saddar Town"). It is kept as scored; corrected, test precision would be 1.00.
- GLiNER's first score (precision 0.21) was a formatting artefact: its spans carried words such as "area" and "city". After shared cleaning its precision matched the rules.

## Limits

Small samples (a test precision of 20 out of 21 is consistent with roughly 77% to 99%), a single labeller, and development-set numbers that are optimistic because the extractor was tuned on them.

After the test set was scored, spelling aliases, a hand-written roll-up map of sub-areas, bare-location handling and the exclusion of roads and districts were added using local knowledge. The test numbers describe the earlier version of the extractor.

## Final development-set result (after aliases, roll-ups and the two-level model)

| Method | Coverage | Precision | Recall | Recall (recurring) | Accuracy |
|---|---|---|---|---|---|
| Rules | 0.68 | 1.00 | 0.85 | 0.98 | 0.88 |
| GLiNER | 0.62 | 0.95 | 0.73 | 0.83 | 0.77 |
| Hybrid | 0.70 | 0.98 | 0.85 | 0.98 | 0.87 |

Whole dataset: 74% of events (1,239 of 1,664) receive an Area; the gazetteer holds 97 names, 95 of which became Area nodes. 225 events also carry a more specific Locality (43 distinct localities). These development numbers are optimistic because the extractor was tuned on them.