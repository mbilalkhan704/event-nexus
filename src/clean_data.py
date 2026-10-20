"""
Cleaning rules (see docs/data_dictionary.md for the reasoning):
 1. Keep only the 32 chosen columns
 2. Keep original city as city_raw; set city to "Karachi"
 3. Build a single date; day or month 0 becomes 1, flagged by date_approx
 4. actor_known is False for the generic labels "Unknown" and "Gunmen"
 5. GTD unknown-codes (negative values) become missing
 6. summary_clean = summary without the leading MM/DD/YYYY: prefix
 7. Keep every event; dup_group marks identical summaries (leakage guard)
 8. Parse related into related_ids and related_in_scope
 9. Missing nkill / nwound / nkillter / nwoundte stay missing, not zero
"""
import re
import pandas as pd

KEEP = [
    "eventid", "iyear", "imonth", "iday",
    "city", "location",
    "gname", "guncertain1", "claimed",
    "attacktype1_txt", "weaptype1_txt", "weapsubtype1_txt", "weapdetail",
    "targtype1_txt", "targsubtype1_txt", "corp1", "target1",
    "nkill", "nkillter", "nwound", "nwoundte", "success", "suicide",
    "multiple", "related", "doubtterr",
    "summary", "motive",
    "scite1", "scite2", "scite3", "dbsource",
]
GENERIC_GROUPS = ["Unknown", "Gunmen"]

df = pd.read_parquet("data/processed/karachi_2000_2020_raw.parquet", columns=KEEP).copy()

# 2. City
df["city_raw"] = df["city"]
df["city"] = "Karachi"

# 3. Date
df["date_approx"] = df["iday"].eq(0) | df["imonth"].eq(0)
df["date_approx"] = df["date_approx"] | df["summary"].str.contains("Default Date", na=False)
df["date"] = pd.to_datetime(dict(
    year=df["iyear"].astype(int),
    month=df["imonth"].replace(0, 1).astype(int),
    day=df["iday"].replace(0, 1).astype(int),
))

# 4. Actor
df["actor_known"] = ~df["gname"].isin(GENERIC_GROUPS)

# 5. Unknown codes become missing
for col in ["claimed", "nkill", "nwound", "nkillter", "nwoundte"]:
    df[col] = df[col].where(df[col] >= 0)

# 6. Text
df["summary_clean"] = (
    df["summary"]
    .str.replace(r"^\d{2}/\d{2}/\d{4}(\s*\(Default Date\))?:\s*", "", regex=True)
    .str.strip()
)

# 7. Duplicate summaries (use dup_group when splitting data for models)
df["dup_group"] = df.groupby("summary_clean").ngroup()

# 8. Related events
def parse_related(value, self_id):
    if pd.isna(value):
        return []
    ids = [int(x) for x in re.findall(r"\d+", str(value))]
    return [i for i in ids if i != self_id]

df["related_ids"] = [parse_related(v, e) for v, e in zip(df["related"], df["eventid"])]
in_scope = set(df["eventid"].astype(int).tolist())
df["related_in_scope"] = df["related_ids"].apply(lambda ids: [i for i in ids if i in in_scope])

# Save
df = df.sort_values("date").reset_index(drop=True)
df.to_parquet("data/processed/karachi_events_clean.parquet")

# Report
print("Rows, columns:", df.shape)
print("Cities:", df["city"].unique().tolist())
print("Date range:", df["date"].min().date(), "to", df["date"].max().date())
print("Approximate dates:", int(df["date_approx"].sum()))
print("Actor known:", round(float(df["actor_known"].mean()), 2))
print("Missing claimed / nkill / nwound / nkillter / nwoundte:",
      *[int(df[c].isna().sum()) for c in ["claimed", "nkill", "nwound", "nkillter", "nwoundte"]])
print("Events with a date prefix left in summary_clean:",
      int(df["summary_clean"].str.match(r"^\d{2}/\d{2}/\d{4}").sum()))
print("Duplicate-summary groups:", int((df["dup_group"].value_counts() > 1).sum()))
print("Events with related links / in scope:",
      int(df["related_ids"].apply(len).gt(0).sum()),
      int(df["related_in_scope"].apply(len).gt(0).sum()))

