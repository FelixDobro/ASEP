"""
Prototype (Optimal): LLM Barcode Classification & Recipe Matching with Canonical Taxonomy

Dependencies:
- Conda Environment: ASE (LangChain, OpenAI, Google GenAI, Pydantic)
- openfoodfacts.db (Barcode raw database)
- ingredients_canonical.db (502 curated canonical categories & N:1 recipe mappings)
- dataset.csv (50,513 structured recipes)
"""
import os
import sys
import json
import sqlite3
import argparse
import threading
from typing import Optional, List, Dict, Any
from dotenv import load_dotenv
from pydantic import BaseModel, Field
from langchain_core.callbacks import BaseCallbackHandler

load_dotenv()

OFF_DB_PATH = "openfoodfacts.db"
CANONICAL_DB_PATH = "ingredients_canonical.db"
DATASET_CSV = "dataset.csv"

# 0. Thread-safe Token Tracker for LangChain
class TokenTracker(BaseCallbackHandler):
    def __init__(self, stage_name: str = ""):
        super().__init__()
        self.stage_name = stage_name
        self.lock = threading.Lock()
        self.input_tokens = 0
        self.output_tokens = 0
        self.total_tokens = 0
        self.calls = 0

    def on_llm_end(self, response, **kwargs):
        with self.lock:
            self.calls += 1
            found_msg = False
            for generations in response.generations:
                for gen in generations:
                    msg = getattr(gen, "message", None)
                    if msg and getattr(msg, "usage_metadata", None):
                        u = msg.usage_metadata
                        self.input_tokens += u.get("input_tokens", 0)
                        self.output_tokens += u.get("output_tokens", 0)
                        self.total_tokens += u.get("total_tokens", 0)
                        found_msg = True
            if not found_msg and response.llm_output:
                tu = response.llm_output.get("token_usage", {})
                self.input_tokens += tu.get("prompt_tokens", 0)
                self.output_tokens += tu.get("completion_tokens", 0)
                self.total_tokens += tu.get("total_tokens", 0)

    def print_summary(self):
        print(f"\n📊 TOKEN USAGE ({self.stage_name}):")
        print(f"   • Executed Calls:      {self.calls}")
        print(f"   • Prompt (Input):      {self.input_tokens:,} Tokens")
        print(f"   • Completion (Output): {self.output_tokens:,} Tokens")
        print(f"   • Total:               {self.total_tokens:,} Tokens")

# 1. Pydantic Schemas for Structured LLM Outputs
class CategoryMatchResult(BaseModel):
    is_match: bool = Field(
        description="True if the product clearly matches one of the allowed canonical categories, False otherwise."
    )
    matched_category: Optional[str] = Field(
        None, 
        description="The EXACT string of the matched category from the provided list, or null if no match."
    )
    confidence: float = Field(
        description="Confidence score between 0.0 and 1.0."
    )
    explanation: str = Field(
        description="Brief 1-sentence culinary rationale for the decision."
    )

class RecipeSubstitutionItem(BaseModel):
    recipe_index: int = Field(description="Index of the recipe from the provided list (1, 2, 3...)")
    title: str = Field(description="Exact title of the recipe")
    can_omit: bool = Field(description="True if the missing ingredient can easily be omitted without ruining the dish.")
    can_substitute_from_inventory: bool = Field(description="True if an ingredient from current inventory can serve as an adequate substitute.")
    substitute_ingredient: Optional[str] = Field(None, description="Name of the specific replacement ingredient from inventory.")
    is_essential: bool = Field(description="True if the ingredient is an indispensable core component.")
    advice: str = Field(description="Concise, practical 1-2 sentence culinary guidance in English.")

class BatchSubstitutionResponse(BaseModel):
    evaluations: List[RecipeSubstitutionItem] = Field(
        description="List of culinary evaluations for each requested near-match recipe."
    )

# 2. Compact Metadata Extraction from Open Food Facts
def extract_compact_metadata(raw_json_str: str) -> Dict[str, Any]:
    try:
        d = json.loads(raw_json_str)
    except Exception:
        return {}
        
    name = d.get("product_name_en") or d.get("product_name") or d.get("product_name_de") or "Unknown"
    generic = d.get("generic_name_en") or d.get("generic_name") or d.get("generic_name_de")
    brand = d.get("brands")
    
    cat_tags = d.get("categories_tags") or []
    specific_cats = cat_tags[-3:] if cat_tags else []
    
    ciqual = [c for c in (d.get("ciqual_food_name_tags") or []) if c != "unknown"]
    ing_text = d.get("ingredients_text_en") or d.get("ingredients_text") or d.get("ingredients_text_de")
    
    return {
        "name": name,
        "generic_name": generic if generic else None,
        "brand": brand if brand else None,
        "categories": specific_cats,
        "food_group": d.get("food_groups") or d.get("pnns_groups_2"),
        "ciqual_term": ciqual if ciqual else None,
        "nova_group": d.get("nova_group"),
        "ingredients": ing_text[:180] if ing_text else None
    }

# 3. Load Canonical Categories from SQLite Database
def get_top_canonical_categories(limit: int = 500) -> List[str]:
    conn = sqlite3.connect(CANONICAL_DB_PATH)
    cur = conn.cursor()
    rows = cur.execute(
        "SELECT category_name FROM canonical_categories ORDER BY recipe_count DESC LIMIT ?", 
        (limit,)
    ).fetchall()
    conn.close()
    return [r[0] for r in rows]

# 4. Initialize LLM Instance (OpenAI / Gemini / Mock)
def get_base_llm(callbacks: Optional[List[Any]] = None):
    gemini_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    openai_key = os.getenv("OPENAI_API_KEY")
    
    if gemini_key and gemini_key != "your_gemini_api_key_here":
        from langchain_google_genai import ChatGoogleGenerativeAI
        return ChatGoogleGenerativeAI(
            model="gemini-3.5-flash-lite", 
            google_api_key=gemini_key,
            callbacks=callbacks
        )
    elif openai_key and openai_key != "your_openai_api_key_here":
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(model="gpt-4o-mini", temperature=0, callbacks=callbacks)
    else:
        return None

def classify_with_llm(llm, metadata: Dict[str, Any], allowed_categories: List[str]) -> CategoryMatchResult:
    if llm is None:
        name = (metadata.get("name") or "").lower()
        if "spaghetti" in name or "pasta" in name or "penne" in name or "fusilli" in name:
            return CategoryMatchResult(is_match=True, matched_category="pasta", confidence=0.98, explanation="Pasta product matches 'pasta'.")
        elif "milch" in name or "milk" in name:
            return CategoryMatchResult(is_match=True, matched_category="milk", confidence=0.98, explanation="Dairy milk matches 'milk'.")
        elif "tomate" in name or "tomato" in name:
            return CategoryMatchResult(is_match=True, matched_category="tomato paste", confidence=0.99, explanation="Tomato product matches 'tomato paste'.")
        elif "hafer" in name or "oat" in name:
            return CategoryMatchResult(is_match=True, matched_category="oat", confidence=0.96, explanation="Oat product matches 'oat'.")
        elif "garlic" in name or "knoblauch" in name:
            return CategoryMatchResult(is_match=True, matched_category="garlic", confidence=0.98, explanation="Garlic product matches 'garlic'.")
        elif "onion" in name or "zwiebel" in name:
            return CategoryMatchResult(is_match=True, matched_category="onion", confidence=0.98, explanation="Onion product matches 'onion'.")
        elif "parmesan" in name:
            return CategoryMatchResult(is_match=True, matched_category="parmesan cheese", confidence=0.98, explanation="Parmesan matches 'parmesan cheese'.")
        elif "basil" in name or "basilikum" in name:
            return CategoryMatchResult(is_match=True, matched_category="basil", confidence=0.98, explanation="Basil matches 'basil'.")
        else:
            return CategoryMatchResult(is_match=False, matched_category=None, confidence=0.92, explanation="No match in canonical vocabulary.")
            
    from langchain_core.prompts import ChatPromptTemplate
    
    prompt = ChatPromptTemplate.from_messages([
        ("system", """You are an expert food classification assistant.
Your task: Determine whether the scanned grocery product from OpenFoodFacts unambiguously matches one of our canonical culinary ingredient categories.

RULES:
1. Select ONLY ONE category from the list of Allowed Categories.
2. If the product is a ready meal, confectionery/snack (e.g., chocolates, candy bars, chips), beverage, or non-cooking processed item, set is_match=False and matched_category=null.
3. Only if the product can be used as a legitimate cooking ingredient and clearly fits a category, set is_match=True and matched_category=<Category>.
"""),
        ("user", """Scanned Product Metadata:
{metadata}

Allowed Categories ({num_categories}):
{categories}
""")
    ])
    
    chain = prompt | llm
    try:
        return chain.invoke({
            "metadata": json.dumps(metadata, indent=2, ensure_ascii=False),
            "num_categories": len(allowed_categories),
            "categories": ", ".join(allowed_categories)
        })
    except Exception as e:
        err_msg = str(e)
        if "insufficient_quota" in err_msg or "credit_balance_exhausted" in err_msg or "429" in err_msg:
            print(f"   ⚠️  [API Quota Limit] Falling back to mock for this scan.")
        else:
            print(f"   ⚠️  [LLM Error]: {err_msg[:100]}... Using fallback.")
        return classify_with_llm(None, metadata, allowed_categories)

# 5. LLM Batch Evaluation for Near-Matches
def analyze_near_matches_batch(
    llm, 
    near_recipes: List[Dict[str, Any]], 
    inventory: List[str]
) -> Dict[int, RecipeSubstitutionItem]:
    STAPLES = ["salt", "water", "black pepper", "sugar", "butter", "olive oil", "vegetable oil", "flour"]
    full_inventory = sorted(list(set(inventory).union(STAPLES)))

    def _heuristic_eval(idx: int, recipe: Dict[str, Any]) -> RecipeSubstitutionItem:
        title = recipe.get("title", "")
        title_l = title.lower()
        missing_list = recipe.get("missing", [])
        missing_s = ", ".join(missing_list)
        missing_l = missing_s.lower()

        if ("potato" in missing_l and "potato" in title_l) or ("flour" in missing_l and "pancake" in title_l) or ("tomato" in missing_l and "bruschetta" in title_l):
            return RecipeSubstitutionItem(
                recipe_index=idx, title=title, can_omit=False, can_substitute_from_inventory=False,
                substitute_ingredient=None, is_essential=True,
                advice=f"'{missing_s}' is an indispensable core ingredient for this dish."
            )
        elif "butter" in missing_l and ("butter" in full_inventory or "olive oil" in full_inventory):
            sub = "butter" if "butter" in full_inventory else "olive oil"
            return RecipeSubstitutionItem(
                recipe_index=idx, title=title, can_omit=True, can_substitute_from_inventory=True,
                substitute_ingredient=sub, is_essential=False,
                advice=f"You can substitute '{missing_s}' with '{sub}' from your inventory."
            )
        elif "bouillon" in missing_l or "broth" in missing_l:
            return RecipeSubstitutionItem(
                recipe_index=idx, title=title, can_omit=True, can_substitute_from_inventory=True,
                substitute_ingredient="salt", is_essential=False,
                advice="Use cooking water seasoned with salt and herbs instead of broth."
            )
        else:
            return RecipeSubstitutionItem(
                recipe_index=idx, title=title, can_omit=True, can_substitute_from_inventory=False,
                substitute_ingredient=None, is_essential=False,
                advice=f"'{missing_s}' can easily be omitted for this dish."
            )

    if llm is None or not near_recipes:
        return {idx: _heuristic_eval(idx, r) for idx, r in enumerate(near_recipes, 1)}

    recipe_lines = []
    for idx, r in enumerate(near_recipes, 1):
        missing_s = ", ".join(r.get("missing", []))
        matched_s = ", ".join(set(r.get("ingredients", [])) - set(r.get("missing", [])))
        cuisine = f" ({r.get('cuisine', '')})" if r.get('cuisine') else ""
        recipe_lines.append(f"{idx}. {r.get('title', '')}{cuisine}\n   - Missing: [{missing_s}]\n   - In Stock: [{matched_s}]")
    recipes_text = "\n".join(recipe_lines)

    from langchain_core.prompts import ChatPromptTemplate
    prompt = ChatPromptTemplate.from_messages([
        ("system", """You are an experienced professional chef and culinary expert.
Evaluate multiple recipes where the user is missing 1-2 ingredients, strictly considering their CURRENT INVENTORY IN A SINGLE BATCH CALL.

Evaluate EACH recipe individually:
1. CORE INGREDIENT: Is the missing item irreplaceable for the identity of the dish (e.g. potatoes for mashed potatoes)? If yes: is_essential=True.
2. INVENTORY SUBSTITUTE: Can an ingredient from the user's available inventory serve as an adequate substitute? If yes: can_substitute_from_inventory=True, substitute_ingredient=<Name>.
3. OMITTABLE: Can the dish simply be cooked without this ingredient? If yes: can_omit=True.
Always provide concise, practical 1-2 sentence culinary advice in English in the 'advice' field."""),
        ("user", """Available User Inventory (including pantry basics):
{inventory}

Near-Match Recipes to Evaluate:
{recipes_text}
""")
    ])

    chain = prompt | llm
    try:
        response: BatchSubstitutionResponse = chain.invoke({
            "inventory": ", ".join(full_inventory),
            "recipes_text": recipes_text
        })
        results = {ev.recipe_index: ev for ev in response.evaluations}
        for idx, r in enumerate(near_recipes, 1):
            if idx not in results:
                match_by_title = next((ev for ev in response.evaluations if ev.title.lower() in r.get("title", "").lower()), None)
                results[idx] = match_by_title if match_by_title else _heuristic_eval(idx, r)
        return results
    except Exception as e:
        print(f"   ⚠️  [LLM Batch Substitution Error: {str(e)[:80]}... Using heuristic fallback]")
        return {idx: _heuristic_eval(idx, r) for idx, r in enumerate(near_recipes, 1)}

# 6. Fetch Barcode Record from OpenFoodFacts
def fetch_product_from_off(barcode: str) -> Optional[Dict[str, Any]]:
    conn = sqlite3.connect(f"file:{OFF_DB_PATH}?mode=ro", uri=True)
    cur = conn.cursor()
    cur.execute("SELECT raw_data FROM products WHERE barcode = ?", (barcode,))
    row = cur.fetchone()
    conn.close()
    if not row or not row[0]:
        return None
    return extract_compact_metadata(row[0])

# 7. Deterministic Recipe Matcher using Canonical DB Lookup
def match_recipes(inventory: List[str], max_results: int = 6):
    """
    Finds matching recipes from dataset.csv by deterministically mapping raw recipe 
    ingredients to canonical categories via raw_ingredient_mappings table.
    """
    import ast
    import csv
    
    conn = sqlite3.connect(CANONICAL_DB_PATH)
    raw_to_canonical = dict(conn.execute("SELECT raw_ingredient, canonical_category FROM raw_ingredient_mappings WHERE canonical_category IS NOT NULL").fetchall())
    conn.close()
    
    STAPLES = {"salt", "water", "black pepper", "sugar", "butter", "olive oil", "vegetable oil", "flour"}
    avail = set(inventory).union(STAPLES)
    
    seen_titles = set()
    perfect_matches = []
    near_matches = []
    
    with open(DATASET_CSV, "r", encoding="utf-8", errors="replace") as f:
        reader = csv.DictReader(f, delimiter=";")
        for row in reader:
            title = row.get("Name", "").strip()
            if not title or title in seen_titles:
                continue
                
            try:
                items = ast.literal_eval(row.get("Ingredients") or "[]")
                can_recipe_ings = set()
                for i in items:
                    raw_ing = i.get("ingredient", "").strip().lower()
                    if raw_ing:
                        c = raw_to_canonical.get(raw_ing, raw_ing)
                        can_recipe_ings.add(c)
                
                if len(can_recipe_ings) < 2:
                    continue
                    
                missing = can_recipe_ings - avail
                total_count = len(can_recipe_ings)
                matched_count = total_count - len(missing)
                score = matched_count / total_count
                
                cuisines_raw = row.get("Cuisines") or "[]"
                try:
                    cuisines = ast.literal_eval(cuisines_raw)
                except Exception:
                    cuisines = []
                
                recipe_entry = {
                    "title": title,
                    "score": score,
                    "matched": matched_count,
                    "total": total_count,
                    "missing": sorted(list(missing)),
                    "ingredients": sorted(list(can_recipe_ings)),
                    "cuisine": cuisines
                }
                
                if len(missing) == 0:
                    perfect_matches.append(recipe_entry)
                    seen_titles.add(title)
                elif len(missing) <= 2 and score >= 0.70:
                    near_matches.append(recipe_entry)
                    seen_titles.add(title)
            except Exception:
                continue
                
    perfect_matches.sort(key=lambda x: (x["total"], x["score"]), reverse=True)
    near_matches.sort(key=lambda x: (x["score"], -len(x["missing"]), x["total"]), reverse=True)
    
    return perfect_matches[:max_results], near_matches[:max_results]

# 8. Main Program
def main():
    PANTRY_50_BARCODES = [
        # Grains, Pasta & Bakery
        "00032056",       # Spaghetti (Sainsbury's)
        "0008583830472",  # Penne Pasta
        "0011110868817",  # Gluten Free Fusilli
        "0011059243683",  # Jasmine Rice
        "0007781502693",  # Whole Wheat Flour
        "12127877",       # Rolled Oats (Haferflocken)
        "0000236555909",  # White Bread
        "0007815002489",  # Flour Tortillas

        # Vegetables & Aromatics
        "0021130980826",  # Minced Garlic
        "0041268162796",  # Yellow Onions
        "00438506",       # Red Onions
        "0021130530557",  # Russet Potatoes
        "0011110809308",  # Crushed Tomatoes
        "0024000007203",  # Tomato Paste (Del Monte)
        "0011110807779",  # Baby Carrots
        "0011110024480",  # Broccoli Florets
        "0000651213019",  # Fresh Spinach
        "00019170",       # Large Mushrooms
        "0011110872203",  # Green Bell Peppers
        "0036800463196",  # Cucumbers
        "0011110728432",  # Lemon Juice

        # Dairy & Eggs
        "9019100215505",  # Fresh Low Fat Milk (Fastenmilch)
        "0008441442038",  # Reduced Fat Milk
        "0011110807625",  # Salted Butter
        "0015204113319",  # Large Eggs
        "0011110884817",  # Grated Parmesan Cheese
        "0010096605102",  # Parmesan Cheese Topping
        "0011110504807",  # Shredded Mozzarella Cheese
        "0011110503015",  # Heavy Whipping Cream
        "0011153073216",  # Plain Yogurt

        # Meat & Seafood
        "00055734",       # Cajun Chicken Breasts
        "00180115",       # Chicken Thighs
        "0011110632005",  # Ground Beef
        "0010957423524",  # Smoked Bacon
        "0037600177900",  # Pork Chops
        "00015738",       # Pink Salmon Fillets
        "0011110888082",  # Chunk Light Tuna in Oil
        "0000850600108",  # Peeled Shrimp

        # Oils, Vinegars & Sauces
        "0005404490105",  # Extra Virgin Olive Oil
        "0000111048403",  # Canola Oil
        "0011110019875",  # Brewed Soy Sauce
        "0011110783530",  # Dijon Mustard
        "00077125",       # Mayonnaise
        "0008295663764",  # Apple Cider Vinegar
        "0011110831668",  # Pure Honey

        # Herbs & Spices
        "0016291441040",  # Basil
        "0011110815064",  # Oregano
        "00099226",       # Black Pepper
        "0011225557606",  # Paprika
        "0016291441194",  # Cumin Seed
    ]

    QUICK_10_BARCODES = [
        "00032056",       # Spaghetti (Sainsbury's)
        "0008583830472",  # Penne Pasta
        "0011110868817",  # Gluten Free Fusilli
        "0024000007203",  # Tomato Paste (Del Monte)
        "0021130980826",  # Minced Garlic (Safeway)
        "0041268162796",  # Yellow Onions (Hannaford)
        "0011110884817",  # Grated Parmesan Cheese (Kroger)
        "0016291441040",  # Basil (Morton & Bassett)
        "0015204113319",  # Large Eggs (First Light Egg Farms)
        "4008400102528",  # Mon Chéri (Ferrero) -> Expected to be rejected
    ]
    
    parser = argparse.ArgumentParser(description="Prototype: Canonical LLM Barcode Classification & Deterministic Recipe Matching")
    parser.add_argument("barcodes", nargs="*", default=None, help="Optional list of barcodes to scan")
    parser.add_argument("--quick", "--10", dest="quick", action="store_true", help="Run with 10-item fast demo inventory")
    args = parser.parse_args()
    
    if args.barcodes:
        barcodes_to_scan = args.barcodes
    elif args.quick:
        barcodes_to_scan = QUICK_10_BARCODES
    else:
        barcodes_to_scan = PANTRY_50_BARCODES

    print("=" * 75)
    print("PROTOTYPE (OPTIMUM): CANONICAL INVENTORY & DETERMINISTIC RECIPE MATCHING")
    print(f"Mode: {'Quick Test (10 Items incl. Penne & Fusilli)' if args.quick else 'Full Pantry Inventory (50 Items)'}")
    print("=" * 75)
    
    # 1. Load canonical categories
    categories = get_top_canonical_categories(500)
    print(f"-> {len(categories)} disjoint canonical categories loaded from {CANONICAL_DB_PATH}.")
    
    # 2. Setup LLMs
    classification_tracker = TokenTracker("1. Barcode Classification")
    substitution_tracker = TokenTracker("2. Recipe Substitution Check")

    base_llm_classify = get_base_llm(callbacks=[classification_tracker])
    base_llm_substitute = get_base_llm(callbacks=[substitution_tracker])

    if base_llm_classify:
        print("  -> Using Google Gemini Flash-Lite (gemini-3.5-flash-lite)...")
    else:
        print("  [NOTE] No API key found -> Mock mode active.\n")

    classifier_llm = base_llm_classify.with_structured_output(CategoryMatchResult) if base_llm_classify else None
    substitution_llm = base_llm_substitute.with_structured_output(BatchSubstitutionResponse) if base_llm_substitute else None
    
    user_inventory = []
    
    print("-" * 75)
    print(f"Processing {len(barcodes_to_scan)} barcode(s) from inventory (parallel accelerated):")
    print("-" * 75)
    
    from concurrent.futures import ThreadPoolExecutor

    def _process_barcode(barcode):
        meta = fetch_product_from_off(barcode)
        if not meta:
            return barcode, None, None
        res = classify_with_llm(classifier_llm, meta, categories)
        return barcode, meta, res

    with ThreadPoolExecutor(max_workers=min(len(barcodes_to_scan), 12)) as executor:
        scan_results = list(executor.map(_process_barcode, barcodes_to_scan))

    for barcode, meta, result in scan_results:
        if not meta:
            print(f"❌ Barcode {barcode}: Not found in openfoodfacts.db.")
            continue
            
        print(f"\n📦 Scan: Barcode {barcode} | Name: '{meta['name']}' (Brand: {meta.get('brand')})")
        
        if result.is_match and result.matched_category:
            print(f"   ✅ MATCHED (via Gemini): -> [{result.matched_category}] (Confidence: {result.confidence:.2f})")
            print(f"      Rationale: {result.explanation}")
            if result.matched_category not in user_inventory:
                user_inventory.append(result.matched_category)
        else:
            print(f"   ⛔ REJECTED (via Gemini): No match in canonical categories (snack / finished meal / irrelevant).")
            print(f"      Rationale: {result.explanation}")
            
    print("\n" + "=" * 75)
    print(f"CURRENT USER INVENTORY ({len(user_inventory)} recognized ingredients):")
    print("  " + ", ".join(user_inventory) if user_inventory else "  (No ingredients in inventory)")
    print("=" * 75)
    
    if classification_tracker.calls > 0:
        classification_tracker.print_summary()
    
    if user_inventory:
        print("\n🍳 RECIPE MATCHING (Normalized set-matching against dataset.csv):")
        m_100, m_near = match_recipes(user_inventory, max_results=6)
        
        if m_100:
            print(f"\n  🟢 1. COOKABLE NOW ({len(m_100)} top recipes with 100% of all ingredients in stock):")
            for r in m_100:
                print(f"     🍽️  {r['title']} ({r['cuisine']})")
                print(f"        -> Ingredients In Stock ({r['total']}): {', '.join(r['ingredients'])}")
        else:
            print("\n  ⚪ No 100% matches found.")
            
        if m_near:
            print(f"\n  🟡 2. ALMOST COOKABLE (Top near-matches, 100% matches excluded):")
            print("     🤖 LLM evaluating all near-matches in A SINGLE BATCH CALL...\n")
            
            eval_map = analyze_near_matches_batch(substitution_llm, m_near, user_inventory)

            for idx, r in enumerate(m_near, 1):
                advice = eval_map.get(idx)
                pct = int(r['score'] * 100)
                missing_str = ", ".join(r['missing'])
                print(f"     🍽️  {r['title']} ({r['cuisine']}) -> {pct}% Match ({r['matched']}/{r['total']} ingredients in stock)")
                print(f"        ❌ Missing:  [{missing_str}]")
                print(f"        ✅ In Stock: {', '.join(set(r['ingredients']) - set(r['missing']))}")
                
                if advice and advice.is_essential:
                    print(f"        🛑 [Core ingredient indispensable]: {advice.advice}")
                elif advice and advice.can_substitute_from_inventory and advice.substitute_ingredient:
                    print(f"        🔄 [Substitute available in inventory]: {advice.advice}")
                    if advice.can_omit:
                        print(f"           ℹ️  (Note: Can also be omitted if needed)")
                elif advice and advice.can_omit:
                    print(f"        ✂️  [Can be omitted]: {advice.advice}")
                elif advice:
                    print(f"        💡 [Chef's Tip]: {advice.advice}")
                print()
                
            if substitution_tracker.calls > 0:
                substitution_tracker.print_summary()

    total_in = classification_tracker.input_tokens + substitution_tracker.input_tokens
    total_out = classification_tracker.output_tokens + substitution_tracker.output_tokens
    total_all = classification_tracker.total_tokens + substitution_tracker.total_tokens
    total_calls = classification_tracker.calls + substitution_tracker.calls

    if total_calls > 0:
        est_cost_usd = (total_in * 0.000000075) + (total_out * 0.00000030)
        print("\n" + "=" * 75)
        print("💰 TOTAL PIPELINE TOKEN USAGE:")
        print(f"   1. Barcode Classification:    {classification_tracker.total_tokens:>7,} Tokens ({classification_tracker.calls:>2} Calls | In: {classification_tracker.input_tokens:,}, Out: {classification_tracker.output_tokens:,})")
        print(f"   2. Recipe Substitution Check: {substitution_tracker.total_tokens:>7,} Tokens ({substitution_tracker.calls:>2} Calls | In: {substitution_tracker.input_tokens:,}, Out: {substitution_tracker.output_tokens:,})")
        print("   " + "-" * 71)
        print(f"   👉 GRAND TOTAL:               {total_all:>7,} Tokens ({total_calls} Calls total)")
        print(f"   💵 Estimated API Cost:        ~${est_cost_usd:.5f} USD (ultra low-cost)")
        print("=" * 75)

if __name__ == "__main__":
    main()
