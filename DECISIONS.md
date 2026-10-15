# EventNexus decision log

| Decision | Choice | Why |
|---|---|---|
| Scope | Karachi: any city spelling, plus Sindh events inside Karachi's coordinate box (about 2,800 events across all years) | Karachi alone has plenty of events; district-named events are included, Hub (Balochistan) is not |
| Time window | 2000 to 2020 (about 1,650 events) | Incident summaries exist only from 2000; the 1990s have almost no text and mostly unknown perpetrators |
| Main focus | Cross-event analysis, not information extraction | GTD is already structured; the value is in connecting events |
| Graph database | Local Neo4j Desktop, database `eventnexus-db` | Offline-capable, native vector index, built-in browser |
| Data format | GTD converted once to Parquet; notebooks for exploration, scripts for repeatable steps | Fast loading on an 8 GB machine; reproducible pipeline |
| NER | GLiNER (medium) plus spaCy baseline | Custom entity labels without training |
| Embeddings | all-MiniLM-L6-v2 | Small and fast on CPU |
| Classifier base | distilbert-base-uncased, fine-tuned on a GPU machine | Light enough for a 6 GB GPU |
| LLM | Provider switch: Gemini API in development, local Ollama model for offline mode | Speed and quality now, offline demo later |
| Optional extra | Fine-tune a ~1B model to pick queries from the query library | Only if the core app is finished |
| Frontend | Plain HTML, CSS, JavaScript with D3, served by FastAPI | No Node build step; works offline |
| PyTorch | Installed per machine, not in requirements.txt | CPU here, CUDA on the GPU machine |
| Data privacy | Raw and processed data are not tracked by git | GTD terms of use; file size |
| Area from text | Neighbourhoods are extracted from location and summary text, not coordinates | 1,627 of 1,664 events share one city-centre coordinate |
| Columns kept | 30 of 135 (identity, place, actor, method, target, outcome, cross-event hints, text, evidence) | Chosen for linking events, describing them, or evidence; the rest are mostly empty or redundant |
| Unknown is not a link | Values labelled "Unknown" (and generic groups) never create shared-attribute links in the graph | Two unknowns don't mean the same thing |
| Graph questions | 15 questions in 5 tiers (lookup, cross-event patterns, multi-hop chains, provenance, similarity); 12 of them are cross-event | The schema is built backwards from the questions, so every structure earns its place |
| Graph nodes | Event, Group, AttackType, WeaponType, TargetType, TargetOrg, Source, and Area (from entity recognition in Phase 4) | These are the things events connect through |
| Unknown means no edge | An event with an unknown weapon, target or group simply has no edge of that kind; the text value stays on the event for display | Makes "Unknown is not a link" structural, not just a query habit |
| Confidence on edges | `claimed` and `uncertain` are stored on the ATTRIBUTED_TO edge | Confidence belongs to the link between an event and a group, not to the group |
| Derived cross-event links | SAME_ACTOR_NEARBY, SAME_SOURCE, SAME_MO_LOCAL, FOLLOWED_BY, SIMILAR_TO; each stores rule, strength and evidence | Every link can explain why it exists, which answers "why are these linked?" |
| Same-actor window | 30 days, with gap_days stored on each edge (236 pairs within 7 days, 632 within 30, 1,446 within 90) | Captures campaign waves without a flood of loose links; other windows stay queryable |
| Shared sources link events | 411 citations are shared by 2 or more events, covering 664 events (40%); SAME_SOURCE links them regardless of actor, with a cap for very widely shared citations (to be set after a distribution check) | Reaches the 80% of events with an unknown actor |
| GTD related is evaluation only | GTD_RELATED pairs are never used to build links, retrieve results or train models | Prevents a circular evaluation |
| `multiple` is a property only | Not used as a link rule or model feature | It is tied to GTD's own relatedness judgement |
| Rule parameters | Windows and thresholds live in one config dictionary | Tuning never means rewriting rules |
| Placeholder organisations | "Not Applicable" and "Civilian(s)" create no TargetOrg node | They mean no organisation, and would form false hubs (140 events) |
| Organisation aliases | Spelling variants of the same organisation are merged (MQM, MQM-H, ANP, PPP, police) | Prevents one organisation being split across nodes and losing links |
| Rebuildable graph | `build_graph.py --reset` rebuilds the whole graph; running it twice gives identical counts; `check_graph.py` verifies it | Reproducibility |
| Source links reach the unknown actors | 607 SAME_SOURCE links connect 524 of 1,338 unattributed events (39%) | The cross-event value for the 80% with no named group |
| Fair evaluation of GTD pairs | GTD_RELATED is tested against text similarity alone, not against source or actor links | 115 of 118 GTD pairs are already linked by shared sources or same actor, so those links would make the test too easy |