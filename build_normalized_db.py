"""
Erstellt ingredients_normalized.db mit:
- A: Singularisierung (Plurale auf Singular via inflect)
- B: Normalisierung (Regex / Modifikatoren wie 'extra-virgin', 'freshly ground', 'chopped' entfernen)
- Mappings-Tabelle für direkten Vergleich (raw vs. normalized)
"""
import csv
import ast
import re
import sqlite3
from collections import Counter
import pandas as pd
import inflect

p = inflect.engine()

DATASET_CSV = "dataset.csv"
OUTPUT_DB = "ingredients_normalized.db"

DO_NOT_SINGULARIZE = {
    'hummus', 'couscous', 'asparagus', 'molasses', 'citrus', 'lemongrass', 'watercress',
    'swiss cheese', 'blue cheese', 'feta cheese', 'parmesan cheese', 'cheddar cheese', 'cheese',
    'mayonnaise', 'dijon mustard', 'mustard', 'allspice', 'anise'
}

STRIP_PHRASES = [
    r'\band black pepper to taste\b',
    r'\band pepper to taste\b',
    r'\bsalt and black pepper to taste\b',
    r'\bsalt and pepper to taste\b',
    r'\bblack pepper to taste\b',
    r'\bto taste\b',
    r'\bas needed\b',
    r'\bif needed\b',
    r'\boptional\b',
    r'\bor more to taste\b',
    r'\bfor frying\b',
    r'\bfor garnish\b',
    r'\bfor serving\b',
    r'\bor to taste\b',
    r'\bor more as needed\b',
    r'\bfreshly ground\b',
    r'\bfreshly grated\b',
    r'\bfreshly squeezed\b',
    r'\bfreshly\b',
    r'\bfresh\b',
    r'\bfinely chopped\b',
    r'\bcoarsely chopped\b',
    r'\broughly chopped\b',
    r'\bchopped\b',
    r'\bfinely diced\b',
    r'\bdiced\b',
    r'\bthinly sliced\b',
    r'\bsliced\b',
    r'\bfinely minced\b',
    r'\bminced\b',
    r'\bfinely grated\b',
    r'\bgrated\b',
    r'\bshredded\b',
    r'\bcrushed\b',
    r'\bground\b',
    r'\bmelted\b',
    r'\bsoftened\b',
    r'\bpeeled\b',
    r'\bseeded\b',
    r'\bhalved\b',
    r'\bdrained\b',
    r'\brinsed\b',
    r'\bcooked\b',
    r'\buncooked\b',
    r'\braw\b',
    r'\broasted\b',
    r'\btoasted\b',
    r'\bsteamed\b',
    r'\bboiled\b',
    r'\bfrozen\b',
    r'\bthawed\b',
    r'\bwarm\b',
    r'\bcold\b',
    r'\bhot\b',
    r'\bextra virgin\b',
    r'\bextra-virgin\b',
    r'\bvirgin\b',
    r'\borganic\b',
    r'\bkosher\b',
    r'\bcoarse\b',
    r'\ball purpose\b',
    r'\ball-purpose\b',
    r'\bunbleached\b',
    r'\bboneless skinless\b',
    r'\bskinless boneless\b',
    r'\bboneless\b',
    r'\bskinless\b',
    r'\blarge\b',
    r'\bmedium\b',
    r'\bsmall\b',
]

# Cache für bereits bereinigte Begriffe (beschleunigt den Durchlauf enorm)
CLEAN_CACHE = {}

def clean_term(raw):
    if raw in CLEAN_CACHE:
        return CLEAN_CACHE[raw]
        
    s = raw.strip().lower()
    if not s:
        return ''
        
    # Sonderfälle
    if s in ['and black pepper to taste', 'black pepper to taste', 'and pepper to taste']:
        res = 'black pepper' if 'black' in s else 'pepper'
        CLEAN_CACHE[raw] = res
        return res
    if s in ['salt and black pepper to taste', 'salt and pepper to taste']:
        CLEAN_CACHE[raw] = 'salt'
        return 'salt'
        
    # Regex-Stripping
    for pat in STRIP_PHRASES:
        s = re.sub(pat, '', s)
        
    # Satzzeichen & Sonderzeichen bereinigen
    s = re.sub(r'[,()/*\-]', ' ', s)
    s = ' '.join(s.split())
    
    # Häufige Rest-Kombinationen
    if s in ['clove garlic', 'cloves garlic', 'garlic clove', 'garlic cloves']:
        res = 'garlic'
    elif s in ['white sugar', 'granulated sugar']:
        res = 'sugar'
    elif s in ['all purpose flour']:
        res = 'flour'
    else:
        res = s
        # Plural zu Singular
        if res not in DO_NOT_SINGULARIZE:
            words = res.split()
            if words:
                last = words[-1]
                if last not in DO_NOT_SINGULARIZE:
                    sing = p.singular_noun(last)
                    if sing and isinstance(sing, str):
                        words[-1] = sing
                        res = ' '.join(words)
                        
    # Überflüssige Verbindungswörter am Rand
    res = re.sub(r'^(and|or|with)\s+', '', res)
    res = re.sub(r'\s+(and|or|with)$', '', res).strip()
    
    final_res = res if res else raw.strip().lower()
    CLEAN_CACHE[raw] = final_res
    return final_res

def build_database():
    print(f"Lese {DATASET_CSV} und wende Normalisierung an...")
    
    recipe_count = 0
    norm_recipe_counts = Counter()
    raw_counts = Counter()
    norm_to_raw_variants = {}
    raw_to_norm = {}
    
    with open(DATASET_CSV, "r", encoding="utf-8", errors="replace") as f:
        reader = csv.DictReader(f, delimiter=";")
        for row in reader:
            recipe_count += 1
            raw_ings = row.get("Ingredients")
            if not raw_ings:
                continue
            try:
                items = ast.literal_eval(raw_ings)
                seen_norm_in_recipe = set()
                for item in items:
                    raw_name = item.get("ingredient", "").strip().lower()
                    if not raw_name:
                        continue
                    
                    raw_counts[raw_name] += 1
                    norm_name = clean_term(raw_name)
                    raw_to_norm[raw_name] = norm_name
                    
                    if norm_name not in seen_norm_in_recipe:
                        seen_norm_in_recipe.add(norm_name)
                        norm_recipe_counts[norm_name] += 1
                        
                    if norm_name not in norm_to_raw_variants:
                        norm_to_raw_variants[norm_name] = Counter()
                    norm_to_raw_variants[norm_name][raw_name] += 1
            except Exception:
                pass

    print(f"Verarbeitet: {recipe_count} Rezepte.")
    print(f"Ursprüngliche unbereinigte Zutaten: {len(raw_counts)}")
    print(f"Normalisierte bereinigte Zutaten:   {len(norm_recipe_counts)}")
    
    # 1. Tabelle: normalized_frequencies
    freq_data = []
    for norm_name, r_count in norm_recipe_counts.most_common():
        pct = round(r_count / recipe_count * 100, 2)
        variants = norm_to_raw_variants[norm_name]
        var_count = len(variants)
        sample_vars = ", ".join([f"{v} ({c})" for v, c in variants.most_common(3)])
        freq_data.append((norm_name, r_count, pct, var_count, sample_vars))
        
    df_freq = pd.DataFrame(freq_data, columns=[
        "ingredient", "recipe_count", "percentage_of_recipes", "raw_variants_count", "sample_raw_variants"
    ])
    
    # 2. Tabelle: ingredient_mappings (raw -> normalized)
    map_data = []
    for raw_name, norm_name in raw_to_norm.items():
        map_data.append((raw_name, norm_name, raw_counts[raw_name]))
    df_map = pd.DataFrame(map_data, columns=["raw_ingredient", "normalized_ingredient", "raw_count"])
    df_map.sort_values(by="raw_count", ascending=False, inplace=True)
    
    # Speichern in SQLite
    print(f"Erstelle SQLite-Datenbank: {OUTPUT_DB}...")
    conn = sqlite3.connect(OUTPUT_DB)
    cur = conn.cursor()
    
    df_freq.to_sql("normalized_frequencies", conn, if_exists="replace", index=False)
    df_map.to_sql("ingredient_mappings", conn, if_exists="replace", index=False)
    
    # Indizes für ultraschnelle Abfragen anlegen
    cur.execute("CREATE INDEX IF NOT EXISTS idx_norm_freq ON normalized_frequencies(recipe_count DESC);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_norm_name ON normalized_frequencies(ingredient);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_map_raw ON ingredient_mappings(raw_ingredient);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_map_norm ON ingredient_mappings(normalized_ingredient);")
    
    conn.commit()
    conn.close()
    print("Fertig! Tabellen 'normalized_frequencies' und 'ingredient_mappings' erfolgreich erstellt.")

if __name__ == "__main__":
    build_database()
