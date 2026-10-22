"""
Skript: Zählt alle Zutaten aus dataset.csv und speichert die Häufigkeiten
in eine SQLite-Datenbank (ingredients_frequency.db) und optional als DataFrame / CSV.
"""
import csv
import ast
import sqlite3
from collections import Counter
import pandas as pd

DATASET_CSV = "dataset.csv"
SQLITE_DB = "ingredients_frequency.db"
OUTPUT_CSV = "ingredients_frequency.csv"

def extract_ingredient_frequencies(csv_path=DATASET_CSV):
    counter = Counter()
    total_recipes = 0
    
    print(f"Lese {csv_path}...")
    with open(csv_path, "r", encoding="utf-8", errors="replace") as f:
        reader = csv.DictReader(f, delimiter=";")
        for row in reader:
            total_recipes += 1
            raw = row.get("Ingredients")
            if not raw:
                continue
            try:
                items = ast.literal_eval(raw)
                # Set verwenden, damit eine Zutat pro Rezept nur einmal gezählt wird
                seen_in_recipe = set()
                for item in items:
                    name = item.get("ingredient", "").strip().lower()
                    if name and name not in seen_in_recipe:
                        seen_in_recipe.add(name)
                        counter[name] += 1
            except Exception:
                pass
                
    print(f"Verarbeitet: {total_recipes} Rezepte. Eindeutige Zutaten gefunden: {len(counter)}")
    
    # DataFrame erstellen
    df = pd.DataFrame(counter.most_common(), columns=["ingredient", "frequency"])
    df["percentage_of_recipes"] = (df["frequency"] / total_recipes * 100).round(2)
    return df, total_recipes

def save_to_sqlite(df, db_path=SQLITE_DB):
    print(f"Speichere in SQLite-Datenbank: {db_path}...")
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    
    cur.execute("""
    CREATE TABLE IF NOT EXISTS ingredient_frequencies (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ingredient TEXT UNIQUE,
        frequency INTEGER,
        percentage_of_recipes REAL
    );
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_freq ON ingredient_frequencies(frequency DESC);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_ing ON ingredient_frequencies(ingredient);")
    
    df.to_sql("ingredient_frequencies", conn, if_exists="replace", index=False)
    conn.close()
    print("In SQLite gespeichert.")

if __name__ == "__main__":
    df, total_recipes = extract_ingredient_frequencies()
    
    # 1. In SQLite DB speichern
    save_to_sqlite(df)
    
    # 2. Als CSV speichern
    df.to_csv(OUTPUT_CSV, index=False)
    print(f"CSV exportiert: {OUTPUT_CSV}")
    
    print("\nTop 20 häufigste Zutaten:")
    print(df.head(20).to_string(index=False))
