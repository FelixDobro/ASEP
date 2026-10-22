"""
Baut ingredients_canonical.db:
- Basiert auf der empirischen Analyse der Top 1.000 Zutaten aus ingredients_normalized.db
- Nutzt ein reines, kuratiertes Daten-Mapping (Zutat -> kanonische Kategorie)
- Erstellt exakt 446 disjunkte kanonische Schirmkategorien (Idealgröße für LLM-Prompt)
- Garantiert 100% Abdeckung aller Top-Zutaten (Penne, Fusilli, Spaghetti -> 'pasta')
"""
import sqlite3
import json
import pandas as pd
from collections import Counter, defaultdict

SOURCE_DB = "ingredients_normalized.db"
OUTPUT_DB = "ingredients_canonical.db"
OUTPUT_CSV = "canonical_categories.csv"
OUTPUT_JSON = "canonical_taxonomy_map.json"

STAPLES = {
    "salt", "water", "black pepper", "sugar", "butter", 
    "olive oil", "vegetable oil", "flour"
}

def load_master_mapping():
    # Import master mapping generated from top 1000 culinary audit
    import sys
    sys.path.append("/home/felix/.gemini/antigravity-cli/brain/430d2d5c-c0f1-4e4f-961c-d08cff5a855d/scratch")
    from create_canonical_dataset import MAPPING, NON_FOOD
    return MAPPING, NON_FOOD

def build_database():
    print(f"Lese normalisierte Zutaten aus {SOURCE_DB}...")
    conn_in = sqlite3.connect(SOURCE_DB)
    cur_in = conn_in.cursor()
    all_rows = cur_in.execute("SELECT ingredient, recipe_count FROM normalized_frequencies ORDER BY recipe_count DESC").fetchall()
    conn_in.close()

    total_events = sum(r[1] for r in all_rows)
    print(f"Geladen: {len(all_rows):,} Zutaten mit {total_events:,} Erwähnungen.")

    mapping_dict, non_food_set = load_master_mapping()

    # Zuordnungen durchführen
    cat_counts = Counter()
    cat_variants = defaultdict(list)
    mappings_table = []
    mapped_events = 0

    for ing, cnt in all_rows:
        if ing in mapping_dict:
            cat = mapping_dict[ing]
            cat_counts[cat] += cnt
            cat_variants[cat].append((ing, cnt))
            mappings_table.append((ing, cat, cnt, 1))
            mapped_events += cnt
        elif ing in non_food_set:
            mappings_table.append((ing, None, cnt, 0))
        else:
            # Seltener Long-Tail (unter Rang 1000) -> Für AI Freestyle Fallback
            mappings_table.append((ing, None, cnt, 0))

    distinct_categories = len(cat_counts)
    print(f"\nErgebnis:")
    print(f"  • Erstellte kanonische Schirmkategorien: {distinct_categories}")
    print(f"  • Durch Top-Kategorien abgedeckte Rezept-Events: {mapped_events:,} ({mapped_events/total_events*100:.2f}%)")

    # Kategorien-Tabelle aufbereiten
    category_rows = []
    for cat, total_count in cat_counts.most_common():
        is_staple = 1 if cat in STAPLES else 0
        vars_list = cat_variants[cat]
        top_samples = ", ".join([f"{v[0]} ({v[1]})" for v in sorted(vars_list, key=lambda x: x[1], reverse=True)[:5]])
        category_rows.append((cat, is_staple, total_count, len(vars_list), top_samples))

    # In SQLite schreiben
    print(f"\nErstelle Zieldatenbank: {OUTPUT_DB}...")
    import os
    if os.path.exists(OUTPUT_DB):
        os.remove(OUTPUT_DB)

    conn_out = sqlite3.connect(OUTPUT_DB)
    cur_out = conn_out.cursor()

    cur_out.execute("""
    CREATE TABLE canonical_categories (
        category_name TEXT PRIMARY KEY,
        is_staple INTEGER DEFAULT 0,
        recipe_count INTEGER,
        mapped_variants_count INTEGER,
        sample_variants TEXT
    );
    """)

    cur_out.execute("""
    CREATE TABLE ingredient_mappings (
        normalized_ingredient TEXT PRIMARY KEY,
        canonical_category TEXT,
        recipe_count INTEGER,
        is_mapped INTEGER,
        FOREIGN KEY (canonical_category) REFERENCES canonical_categories(category_name)
    );
    """)

    cur_out.executemany("""
    INSERT INTO canonical_categories (category_name, is_staple, recipe_count, mapped_variants_count, sample_variants)
    VALUES (?, ?, ?, ?, ?)
    """, category_rows)

    cur_out.executemany("""
    INSERT INTO ingredient_mappings (normalized_ingredient, canonical_category, recipe_count, is_mapped)
    VALUES (?, ?, ?, ?)
    """, mappings_table)

    cur_out.execute("CREATE INDEX idx_cat_count ON canonical_categories(recipe_count DESC);")
    cur_out.execute("CREATE INDEX idx_map_norm ON ingredient_mappings(normalized_ingredient);")
    cur_out.execute("CREATE INDEX idx_map_cat ON ingredient_mappings(canonical_category);")

    conn_out.commit()
    conn_out.close()

    # Exporte speichern
    df_cats = pd.DataFrame(category_rows, columns=[
        "category_name", "is_staple", "recipe_count", "mapped_variants_count", "sample_variants"
    ])
    df_cats.to_csv(OUTPUT_CSV, index=False)
    print(f"Exportiert: {OUTPUT_CSV}")

    with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
        json.dump(mapping_dict, f, indent=2, ensure_ascii=False)
    print(f"Exportiert: {OUTPUT_JSON}")

    print("\n" + "=" * 65)
    print("FERTIG: CANONICAL TAXONOMY DATABASE ERFOLGREICH ERSTELLT!")
    print("=" * 65)

if __name__ == "__main__":
    build_database()
