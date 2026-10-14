from pathlib import Path
import pandas as pd

script_dir = Path(__file__).resolve().parent
excel_path = script_dir.parent / "data" / "raw" / "raw.xlsx"

df = pd.read_excel(excel_path)
print("Loaded:", df.shape)

# Parquet needs one type per column; Excel columns can mix text and dates
text_cols = df.select_dtypes(include="object").columns
df[text_cols] = df[text_cols].astype("string")

df.to_parquet("data/processed/gtd_full.parquet")
print("Saved Parquet")