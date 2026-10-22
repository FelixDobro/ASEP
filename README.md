# 🍳 Smart Pantry & Recipe Engine (ASE)

A hybrid engine connecting grocery barcodes to actionable recipes using a canonical culinary taxonomy and deterministic set matching.

---

## 🚀 Quickstart

```bash
# 1. Activate conda environment
conda activate ASE

# 2. Set API key in .env
echo 'GEMINI_API_KEY="your_api_key"' > .env

# 3. Run the fast 10-item demo
python prototype_optimal.py --quick

# 4. Or scan custom barcodes
python prototype_optimal.py 00032056 0008583830472 0021130980826
```

---

## 🧠 Architecture & Methodology

```
[Grocery Barcode]
       │
       ▼
1. LLM Normalizer (Gemini 3.5 Flash-Lite)
   • Maps noisy product metadata into exactly ONE of 502 canonical cooking categories.
   • Strictly rejects snacks, confectionery (e.g., Mon Chéri), and ready meals.
       │
       ▼  (e.g., "pasta", "tomato paste", "garlic")
2. Canonical User Inventory
       │
       ▼
3. Deterministic Recipe Matcher (dataset.csv)
   • 100% Set-Algebra lookup via precomputed SQLite table (`raw_ingredient_mappings`).
   • 🟢 Cookable Now: 100% ingredients in stock.
   • 🟡 Almost Cookable: Missing 1–2 ingredients.
       │
       ▼
4. Single-Batch Chef Evaluation (Gemini 3.5 Flash-Lite)
   • Evaluates all near-matches in 1 single call (substitutions & indispensability).
```

### Why this approach?
1. **No Fragmentation Trap**: Naive Top-250 lists split pasta into 329 raw strings and sausages into 20 strings, causing basic items like Penne or Bratwurst to be rejected. Our 502 canonical categories group synonyms without losing identity.
2. **Why No Vector Embeddings**: Embeddings fail at culinary logic—they treat *baking soda* and *baking powder*, or *garlic salt* and *salt* as interchangeable neighbors, ruining dishes.
3. **Deterministic & Cheap**: Recipe matching is zero-cost hashmap lookups. Classification and substitution checks cost less than **$0.002 USD** per full pantry run.

---

## 📁 Key Files

| File | Description |
| :--- | :--- |
| **[`prototype_optimal.py`](prototype_optimal.py)** | Main production prototype (barcode scan $\to$ canonical match $\to$ recipe evaluation). |
| **[`ingredients_canonical.db`](ingredients_canonical.db)** | SQLite database containing the 502 categories and 17k raw ingredient mappings. *(Ignored)* |
| **[`build_canonical_database.py`](build_canonical_database.py)** | Build script generating the canonical database. |
| **`openfoodfacts.db`** | Local Open Food Facts dump (1.23M products). *(Ignored)* |
| **`dataset.csv`** | 50,513 structured recipes with nutrition info. *(Ignored)* |
| **[`agent.md`](agent.md)** | Technical briefing for AI coding assistants. |
