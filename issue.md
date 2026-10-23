# [ISSUE] Recipe Bottleneck: Scraper Artifacts, Reversed Units & Equipment Noise Block 57.4% of Matches

- **Status:** Open / Confirmed by Empirical Audit
- **Severity:** High (Unnecessary Ceiling on 100% "Cookable Now" Recipes)
- **Affects:** [`prototype_optimal.py`](file:///home/felix/projects/ASE/prototype_optimal.py), [`dataset.csv`](file:///home/felix/projects/ASE/dataset.csv), [`ingredients_canonical.db`](file:///home/felix/projects/ASE/ingredients_canonical.db)

---

## 1. Executive Summary

An audit of the 57.4% (29,017) recipes blocked from reaching 100% matches reveals that **the bottleneck is NOT a lack of food categories (502 is plenty)**. 

Instead, the unmapped fallback space is heavily polluted by:
1. **Preparation phrases & noise:** `to taste`, `boneless`, `as needed`, `to cover`, `for frying`.
2. **Kitchen equipment & packaging:** `toothpick`, `skewer`, `aluminum foil`, `tea bag`.
3. **Inverted scraper units:** Measurement words parsed as ingredient names (`stalk` instead of `celery`, `stick` instead of `butter`, `wedge` instead of `lemon`).

Treating these non-food tokens as mandatory recipe ingredients prevents thousands of otherwise cookable dishes from matching.

---

## 2. Empirical Audit: Top Fallback Blockers

Analysis across all 50,513 recipes in [`dataset.csv`](file:///home/felix/projects/ASE/dataset.csv):

| Fallback String | Recipes Blocked | True Culinary Nature |
| :--- | :--- | :--- |
| **`to taste`** | **1,471** | Preparation modifier (salt/pepper to taste) |
| **`boneless`** | **448** | Meat cut adjective (*boneless chicken breast*) |
| **`ice cube` / `ice water`** | **340** | Water variation (pantry staple) |
| **`stick`** | **337** | Measurement unit (*1 stick butter*) |
| **`fillet`** | **253** | Fish cut adjective (*salmon fillet*) |
| **`skewer` / `toothpick`** | **286** | Non-food kitchen equipment |
| **`aluminum foil` / `foil`** | **159** | Non-food packaging artifact |
| **`to cover` / `for frying`** | **186** | Preparation instructions (*water to cover*) |
| **`wedge` / `stalk` / `slice`**| **278** | Measurement units (*lemon wedge*, *celery stalk*) |

> [!IMPORTANT]
> A test run ignoring just **20 of these noise tokens** instantly unlocked **+1,794 recipes** into 100% "Cookable Now" status with zero changes to the 502 taxonomy.

---

## 3. Root Causes

1. **Boolean All-or-Nothing Matching:**  
   [`prototype_optimal.py`](file:///home/felix/projects/ASE/prototype_optimal.py#L344) requires `can_recipe_ings - avail == set()`. If a recipe lists `toothpick` or `to taste`, it mathematically fails 100% matching.
2. **Reversed Unit Parsing in `dataset.csv`:**  
   Scraped recipes systematically swapped `unit` and `ingredient`:
   * Text: *"1 celery stalk"* $\to$ Parsed: `unit: 'celery'`, `ingredient: 'stalk'`.
   * Result: The matcher searches for literal `stalk`. Because `stalk` is in the 1:1 fallback space, no barcode scan can ever fulfill it.

---

## 4. Actionable Remediation (Beyond Expanding the Taxonomy)

Instead of inflating the taxonomy with hundreds of rare words, apply these three architectural fixes:

### Solution 1: Automated "Reversed Unit" Dataset Healing (Immediate Win)
Run an offline healing script over [`dataset.csv`](file:///home/felix/projects/ASE/dataset.csv):
* **Rule:** If `unit` exists in the 502 canonical categories (`celery`, `butter`, `garlic`, `lemon`) and `ingredient` is a measurement word (`stalk`, `stick`, `clove`, `wedge`, `slice`) $\to$ **Swap them**: `ingredient = unit`.
* **Impact:** Reclaims several thousand recipes into the 502 categories without touching runtime code.

### Solution 2: Non-Food & Preparation Exclusion Filter (Runtime Fix)
Add an explicit ignore-set to `match_recipes()` in [`prototype_optimal.py`](file:///home/felix/projects/ASE/prototype_optimal.py):
```python
NON_INGREDIENT_NOISE = {
    'to taste', 'boneless', 'bone in', 'as needed', 'to cover', 'for frying', 
    'ice cube', 'toothpick', 'skewer', 'aluminum foil', 'foil', 'tea bag', 
    'slice', 'stick', 'wedge', 'cube', 'fillet', 'powder', 'vegetable', 'sauce'
}
# When computing missing ingredients:
missing = {ing for ing in (can_recipe_ings - avail) if ing not in NON_INGREDIENT_NOISE}
```
* **Impact:** Instantly recovers ~1,800 recipes with 5 lines of code.

### Solution 3: The "Pristine Catalog" Pruning Option (Production Quality)
* **The Reality:** 21,496 recipes in `dataset.csv` are already **100% pure canonical** (larger than the full catalogs of HelloFresh or NYT Cooking).
* **Action:** Prune or tag the active matching pool to only recipes where $\le 1$ ingredient is non-canonical.
* **Impact:** Eliminates all scraper garbage from the user-facing app and guarantees high-quality, predictable recommendations.
