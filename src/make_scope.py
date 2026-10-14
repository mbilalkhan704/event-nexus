import pandas as pd

df = pd.read_parquet("data/processed/gtd_full.parquet")
pk = df[df["country_txt"].eq("Pakistan")]

in_box = pk["latitude"].between(24.7, 25.2) & pk["longitude"].between(66.8, 67.4)
in_sindh = pk["provstate"].eq("Sindh").fillna(False)
labelled = pk["city"].fillna("").str.contains("karachi", case=False)

scope = pk[(labelled | (in_box & in_sindh)) & pk["iyear"].between(2000, 2020)]
print("Scope events:", len(scope))
print("Years:", scope["iyear"].min(), "to", scope["iyear"].max())

scope.to_parquet("data/processed/karachi_2000_2020_raw.parquet")
