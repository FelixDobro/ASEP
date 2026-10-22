# AGENT CONTEXT: Project ASE (Food & Recipe Engine)

> **Purpose of this document:** This file serves as an architectural briefing and operational guide for subsequent AI coding agents to resume work seamlessly without context loss.

---

## 1. Project Mission & Core Workflow
The objective is an intelligent pantry inventory and recipe matching system:
1. **Barcode Scan:** User scans a grocery barcode (EAN / UPC).
2. **Metadata Extraction & Classification:** The system fetches raw JSON metadata from a local Open Food Facts (OFF) database, extracts a compact summary, and uses an LLM (with Pydantic structured output) to classify the item into a **canonical ingredient** from a controlled vocabulary (Top 250).
3. **Inventory Management:** Matched items are added to `user_inventory`. Finished snacks/sweets (e.g., *Mon Chéri*) or non-cooking items are rejected.
4. **Deterministic Recipe Matching:** Fast, relational set-intersection against 50,513 recipes from `dataset.csv`:
   * **100% Matches (Cookable Now):** All required ingredients are in stock or covered by assumed pantry staples.
   * **Near-Matches (Almost Cookable):** Ranked by match percentage (max. 1–2 missing ingredients). **Strictly disjoint** from the 100% list!
5. **Fallback (AI Freestyle):** If no static recipe in the database fits the user's pantry, the LLM can generate a customized recipe strictly constrained to available inventory.

---

## 2. Project Files & Databases

### A. Raw Data & Datasets
* **`openfoodfacts.db` (SQLite, ~30 GB):**
  * Table `products`: Columns `barcode` (PRIMARY KEY, indexed), `product_name`, `raw_data` (JSON string containing 150–200 OFF fields).
* **`dataset.csv` (~110 MB, 50,513 recipes):**
  * Delimiter: Semicolon (`;`).
  * Columns: `Name;Author;Date;Rating Value;...;Ingredients;Ingredients_Raw;Instructions;Servings;Nutrition;URL`
  * `Ingredients`: Parsed Python dict list as string: `[{'ingredient': '...', 'quantity': '...', 'unit': '...'}]`.
  * `Nutrition`: Pre-calculated nutrition per serving present in **98.6% of all recipes** (`Calories`, `Protein`, `Carbohydrates`, `Fat`, etc.).

### B. Normalized Databases & Preprocessing Scripts
* **`ingredients_canonical.db` (SQLite - CURRENT TAXONOMY):**
  * Table `canonical_categories`: 502 clean, disjoint canonical umbrella categories (controlled vocabulary for the LLM prompt) with recipe frequencies and pantry staple flags.
  * Table `ingredient_mappings`: N:1 mapping from 15,127 normalized ingredients to the 502 canonical categories.
  * Table `raw_ingredient_mappings`: Direct 1:1 lookup from 17,015 raw ingredients in `dataset.csv` to the 502 canonical categories.
* **`ingredients_normalized.db` (SQLite):**
  * Table `normalized_frequencies`: 15,127 cleaned singular ingredients with recipe frequencies and raw variant counts.
  * Table `ingredient_mappings`: Exact 1:1 lookup table mapping raw ingredient strings (17,015) $\rightarrow$ normalized singular ingredient (15,127).
* **`build_canonical_database.py`:** Builds `ingredients_canonical.db` and exports `canonical_categories.csv` and `canonical_taxonomy_map.json`.
* **`build_normalized_db.py`:** Generates `ingredients_normalized.db` from `dataset.csv` using `inflect` for English singularization and regex for stripping preparation adjectives (*diced, chopped, extra-virgin, skinless*).
* **`count_ingredients.py`:** Standalone frequency counter for raw recipe ingredients.

### C. Prototypes
* **`prototype_optimal.py` (OPTIMAL PRODUCTION PROTOTYPE):**
  * Uses `ingredients_canonical.db` with 502 disjoint canonical categories.
  * Unifies Penne, Fusilli, Spaghetti, and Macaroni into `pasta`, Bratwurst into `sausage`, etc.
  * 100% deterministic recipe matching via precomputed `raw_ingredient_mappings` table.
  * Clean, unbloated code (~390 lines, zero regex synonym hacks).
  * Features 50-item pantry default, `--quick` mode, and single-batch LLM substitution analysis.
  * Replaces legacy prototypes `prototype.py` and `prototype_llm.py` (both removed).
* **`data.ipynb` / `quer.ipynb`:** Interactive Jupyter Notebooks for data exploration.

---

## 3. Python Environment & Configuration
* **Conda Environment:** `ASE` (Python 3.11)
  * Path to Python binary: `/home/felix/miniconda3/envs/ASE/bin/python`
  * Installed libraries: `langchain`, `langchain-google-genai`, `langchain-openai`, `pydantic`, `pandas`, `inflect`, `python-dotenv`.
* **API Keys:** Located in `.env` in the project root:
  * `GEMINI_API_KEY`: Active Google Gemini key (default configured model: `gemini-3.5-flash-lite`).
  * `OPENAI_API_KEY`: Optional fallback key.

---

## 4. Key Architectural Invariants & Decisions

1. **Do Not Use Brittle Regex/Tag Filters on OFF Categories:**  
   Open Food Facts tags are crowdsourced and inconsistent across countries. Let the LLM evaluate the compact metadata JSON directly.
2. **Recipe Ingredients MUST Be Normalized Before Matching:**  
   When matching against `dataset.csv`, never compare raw ingredient strings directly. Always map through `ingredient_mappings` (e.g., `thin spaghetti` $\rightarrow$ `spaghetti`, `eggs` $\rightarrow$ `egg`).
3. **The "Else" Branch Strategy (Out-of-Catalog Items):**  
   If a scanned item is not in the Top 250/500 canonical categories (e.g., *tahini*, *lemongrass*), store it as clear text in inventory. Do not attempt forced string matching against the database's 15,000 raw strings. Let the **AI Freestyle Fallback** handle recipes for these items.
4. **Pantry Staples (Assumed Items):**  
   Items like salt, black pepper, water, sugar, butter, and cooking oil are treated as standard staples. Recipes requiring only inventory items plus staples are considered 100% matches.
5. **Deduplication:**  
   A recipe categorized as a 100% match must never appear in the near-match list.
