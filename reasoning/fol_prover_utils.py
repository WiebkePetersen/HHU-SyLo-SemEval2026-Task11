import re
import string
import json
import subprocess
import concurrent.futures
import ast
from tqdm import tqdm
from reasoning.io_utils import load_data, save_data
import pandas as pd

# --- CONFIGURATION ---
# Default Otter control syntax for automated reasoning
OTTER_CONTROL_SYNTAX = "set(auto).\nset(formula_history).\nassign(max_seconds, 15).\n"
OTTER_COMMAND = "otter"
TIMEOUT_SECONDS = 15
MAX_WORKERS = 4



##################### Utilities to go directly from simplified English to FOL #####################
# optimized on 100 examples from train data


# --- ROBUST REGEX PATTERNS (The Safety Net) ---
# These handle cases where the LLM forgets to remove articles or has weird spacing
PATTERNS = {
    'no_not': re.compile(r'^no\s+(?:a\s+|an\s+)?(.+?)\s+(?:is|are)\s+not\s+(?:a\s+|an\s+)?(.+)$', re.IGNORECASE),
    'some_not': re.compile(r'^some\s+(?:a\s+|an\s+)?(.+?)\s+(?:is|are)\s+not\s+(?:a\s+|an\s+)?(.+)$', re.IGNORECASE),
    'all': re.compile(r'^(all|every|any|each)\s+(?:a\s+|an\s+)?(.+?)\s+(?:is|are)\s+(?:a\s+|an\s+)?(.+)$', re.IGNORECASE),
    'no': re.compile(r'^no\s+(?:a\s+|an\s+)?(.+?)\s+(?:is|are)\s+(?:a\s+|an\s+)?(.+)$', re.IGNORECASE),
    'some': re.compile(r'^some\s+(?:a\s+|an\s+)?(.+?)\s+(?:is|are)\s+(?:a\s+|an\s+)?(.+)$', re.IGNORECASE)
}

def _clean_term(term: str) -> str:
    if not term: return "Unknown"
    
    # 1. Standard cleaning
    term = term.replace("[", "").replace("]", "").replace("'", "").replace('"', "")
    
    # 2. Aggressive Prefix Stripping (Fixes Term-Inconsistency)
    # We remove these even if they are connected by underscores
    prefixes_to_strip = [
        r'^(a|an|the)\s+', 
        r'^some_', r'^single_', r'^piece_of_', r'^person_who_is_', 
        r'^animal_that_has_', r'^creature_that_is_'
    ]
    for p in prefixes_to_strip:
        term = re.sub(p, '', term, flags=re.IGNORECASE).strip()

    # 3. Replace remaining spaces with underscores
    term = term.replace(" ", "_")
    
    # 4. Singularization
    if len(term) > 3 and term.lower().endswith('s'):
        if not term.lower().endswith(('ss', 'us')):
            term = term[:-1]
    # ensure upper case        
    return term[0].upper() + term[1:] if len(term) > 0 else "Unknown"



def translate_sentence_to_fol(sentence: str) -> str:
    s = sentence.strip().strip('"').strip("'").rstrip('.')
    if not s or s == "[]": return ""

    x, y = None, None
    quantifier = "all"
    has_not = False
    
    # Handle "not all"
    if s.lower().startswith("not all"):
        quantifier = "some"
        has_not = True
        s = s[7:].strip()

    # --- NEW: Double Negation Detection ---
    # Check if the predicate itself contains a "not" 
    # (e.g., "is not not Wood" or "no X is not Y")
    internal_not = False
    if " not not " in s.lower():
        s = re.sub(r"\s+not\s+not\s+", " is ", s, flags=re.IGNORECASE)
    
    # Strategy 1: Splitting
    if " is not " in s.lower() or " are not " in s.lower():
        parts = re.split(r'\s+(?:is|are)\s+not\s+', s, flags=re.IGNORECASE)
        has_not = True
    elif " is " in s.lower() or " are " in s.lower():
        parts = re.split(r'\s+(?:is|are)\s+', s, flags=re.IGNORECASE)
    else:
        parts = []

    if len(parts) == 2:
        left_side = parts[0].strip()
        y_raw = parts[1].strip()
        
        # If we already have a 'no' quantifier AND an 'is not', 
        # they cancel each other out.
        if left_side.lower().startswith("no ") and has_not:
            quantifier = "all"
            has_not = False # -(-) = +
            x_raw = left_side[3:].strip()
        else:
            words = left_side.split()
            if len(words) >= 2:
                quantifier = words[0].lower()
                x_raw = " ".join(words[1:])
            else:
                x_raw = left_side
        
        x, y = _clean_term(x_raw), _clean_term(y_raw)

    # --- STRATEGY 2: Regex Fallback  ---
    if not x or not y:
        s_lower = s.lower()
        if match := PATTERNS['no_not'].match(s_lower):
            x, y, quantifier, has_not = _clean_term(match.group(1)), _clean_term(match.group(2)), "all", False
        elif match := PATTERNS['some_not'].match(s_lower):
            x, y, quantifier, has_not = _clean_term(match.group(1)), _clean_term(match.group(2)), "some", True
        elif match := PATTERNS['all'].match(s_lower):
            x, y, quantifier, has_not = _clean_term(match.group(2)), _clean_term(match.group(3)), "all", False
        elif match := PATTERNS['no'].match(s_lower):
            x, y, quantifier, has_not = _clean_term(match.group(1)), _clean_term(match.group(2)), "no", False
        elif match := PATTERNS['some'].match(s_lower):
            x, y, quantifier, has_not = _clean_term(match.group(1)), _clean_term(match.group(2)), "some", False

    if not x or not y:
        return f"ERROR_UNPARSABLE: {sentence}"

    # Final Mapping using Otter symbols
    if quantifier == "no" or (quantifier == "all" and has_not):
        return f"all x ({x}(x) -> -{y}(x))"
    if quantifier in ["all", "every", "each", "any"]:
        return f"all x ({x}(x) -> {y}(x))"
    if quantifier == "some" and has_not:
        return f"exists x ({x}(x) & -{y}(x))"
    if quantifier == "some":
        return f"exists x ({x}(x) & {y}(x))"

    return f"all x ({x}(x) -> {y}(x))"



def process_dataset_to_fol(input_file, input_key, output_file=None, output_key="fol_output"):
    """
    Reads Parquet as a Dataset object, processes logic, and saves back.
    Uses dataset.map for better performance and clean structure.
    """
    if output_file is None:
        output_file = input_file

    # Always load as a Dataset object for consistency
    ds = load_data(input_file, return_dataset=True)

    def translation_helper(example):
        """Helper function for dataset.map"""
        lines = example.get(input_key, [])
        
        # Ensure we are dealing with a list
        if not isinstance(lines, list):
            lines = [lines] if lines else []
            
        # Translate each line; filter out None/empty results
        fol_formulas = [translate_sentence_to_fol(line) for line in lines]
        example[output_key] = [f for f in fol_formulas if f]
        return example

    # Use .map to process the entire dataset
    # batched=False is easier for LLM calls/complex logic
    ds_processed = ds.map(translation_helper)

    # Save the Dataset directly
    save_data(ds_processed, output_file)
    return ds_processed


####################### Preprocessing Utilities ########################

# --- 1. BASIC SYNTAX CORRECTION ---


def _clean_basic_syntax(f):
    """Standardizes basic logical operators and quantifier syntax."""
    f = f.strip()
    
    # 1. Standardize Boolean constants
    f = re.sub(r'\b(true|True|TRUE)\b', '$T', f)
    f = re.sub(r'\b(false|False|FALSE)\b', '$F', f)
    
    # 2. Fix "NotPredicate(x)" -> "-Predicate(x)"
    # Sucht nach "Not" oder "Isnot" direkt vor einem Großbuchstaben (Prädikat)
    f = re.sub(r'\b(?:Not|Isnot|isnot|not)([A-Z])', r'-\1', f)
    
    # 3. Standardize Quantifiers (ensure "all x" / "exists x" format)
    # This also fixes cases like "all(x)" or "exists(x)"
    f = re.sub(r'\b(exists|exist|all|every|forall)\s*\(?([a-z])\)?',
                lambda m: f"{m.group(1).lower()} {m.group(2)}",
                f, flags=re.IGNORECASE)
    
    # 4. Global Negation replacement (standalone "not" to "-")
    f = re.sub(r'\bnot\b', '-', f)
    
    # 5. Spacing for Otter (ensures "-" doesn't merge weirdly with quantifiers)
    f = f.replace(' - ', ' -').replace('(- ', '(-')
    
    return f


# --- 2. LOGIC CORE ISOLATION ---

def _extract_logic_core(f):
    """Removes trailing dots and identifies if the entire formula is negated."""
    core = f.replace('.', '').strip()
    is_negated = core.startswith('-')
    if is_negated:
        core = core[1:].strip()
    return core, is_negated

# --- 3. ALPHA CONVERSION & PRENEX FORM ---

def _apply_alpha_conversion(core):
    """Ensures unique variable naming (a, b, c...) for prenex normalization."""
    alphabet = string.ascii_lowercase
    new_quantifiers = []
    temp_body = core
    var_index = 0
    quant_regex = re.compile(r'\b(all|exists)\s+([a-z])\b', re.IGNORECASE)

    while True:
        match = quant_regex.search(temp_body)
        if not match:
            break
        q_type = match.group(1).lower()
        q_var = match.group(2)
        new_var = alphabet[var_index] if var_index < 26 else f"v{var_index}"
        new_quantifiers.append(f"{q_type} {new_var}")
        start, end = match.span()
        temp_body = temp_body[:start] + temp_body[end:]
        temp_body = re.sub(rf'\b{q_var}\b', new_var, temp_body)
        var_index += 1

    clean_body = re.sub(r'\s+', ' ', temp_body).strip()
    clean_body = clean_body.replace('()', '').strip()

    while clean_body.startswith('(') and clean_body.endswith(')'):
        inner = clean_body[1:-1].strip()
        if inner.count('(') == inner.count(')'):
            balance = 0
            is_outer = True
            for char in inner:
                if char == '(': balance += 1
                elif char == ')': balance -= 1
                if balance < 0:
                    is_outer = False
                    break
            if is_outer and balance == 0:
                clean_body = inner
            else:
                break
        else:
            break
    prefix = " ".join(new_quantifiers)
    return prefix, clean_body

# --- 4. PARENTHESES BALANCING ---

def _balance_parentheses(f):
    """Ensures balanced parentheses by appending or trimming markers."""
    open_c = f.count('(')
    close_c = f.count(')')
    if open_c > close_c:
        f += ')' * (open_c - close_c)
    elif close_c > open_c:
        while f.count(')') > f.count('(') and f.endswith(')'):
            f = f[:-1]
    return f

# --- 5. PROCESSING PIPELINE ---

def process_formula_to_pranex(formula):
    """Full pipeline to convert raw FOL to standardized prenex format."""
    f = _clean_basic_syntax(formula)
    core, was_negated = _extract_logic_core(f)
    prefix, body = _apply_alpha_conversion(core)
    result = f"{prefix} ({body})" if prefix else body
    if was_negated:
        result = f"-({result})"
    return _balance_parentheses(result)

# --- 6. EXISTENCE CONDITIONS ---

def _add_existence_condition(formulas_list):
    """Adds implicit existence axioms for all detected predicates."""
    new_formulas = list(formulas_list)
    found_predicates = set()
    predicate_pattern = r'\b([A-Z][a-z_A-Z0-9]*)\s*\('
    for f in formulas_list:
        matches = re.findall(predicate_pattern, f)
        found_predicates.update(matches)
    new_formulas.append("% separation marker: end of original premises\n")  # separation marker
    for pred in sorted(found_predicates):
        condition = f"exists a ( {pred}(a) )"
        if not any("exists" in f.lower() and pred in f for f in new_formulas):
            new_formulas.append(condition)
    return new_formulas

# --- 7. OTTER INTERFACE ---

def _format_for_otter(usable_formulas_list, conclusion_formula_raw):
    """Formats premises and negated conclusion for Otter input."""
    processed_premises = [f"{process_formula_to_pranex(p)}." for p in usable_formulas_list]
    core_conclusion = process_formula_to_pranex(conclusion_formula_raw)
    final_conclusion = _balance_parentheses(f"-({core_conclusion}).")
    return (OTTER_CONTROL_SYNTAX + "\nformula_list(usable).\n" + 
            "\n".join(processed_premises) + "\n" + final_conclusion + "\nend_of_list.\n")



def make_clean_list(fol_output_raw):
    """
    Parses raw FOL input into a list. 
    Safe against UnboundLocalError and Gemma-specific artifacts.
    """
    # 1. Falls es bereits eine Liste ist (direkt verarbeiten)
    if isinstance(fol_output_raw, list):
        current_list = fol_output_raw
    else:
        # 2. String-Vorverarbeitung
        clean_raw = str(fol_output_raw).strip()
        
        # GEMMA-FIX: Alles nach dem letzten ] abschneiden
        if "]" in clean_raw:
            clean_raw = clean_raw[:clean_raw.rfind(']') + 1]

        # 3. Parsing-Versuche
        if not clean_raw.startswith('['):
            current_list = [clean_raw] if clean_raw else []
        else:
            try:
                # Versuch A: Standard JSON (für Qwen/Llama)
                current_list = json.loads(clean_raw)
            except Exception:
                try:
                    # Versuch B: Python Literal (für Gemma Quotes)
                    # Entferne hängende Einzel-Anführungszeichen hinter der Klammer
                    temp_eval = clean_raw.rstrip("'\" ")
                    current_list = ast.literal_eval(temp_eval)
                except Exception:
                    # Fallback C: Wenn alles scheitert, den String als Ganzes nehmen
                    current_list = [clean_raw] if clean_raw else []

    # 4. Finales Polieren der Items (entfernt restliche Quotes/Müll)
    final_list = []
    if isinstance(current_list, list):
        for item in current_list:
            if item:
                # String-Konvertierung und Säuberung von äußeren Quotes
                s = str(item).strip().strip("'").strip('"').strip()
                # Falls noch Artefakte wie "] display" im String hängen
                s = s.split(']')[0].strip()
                if s:
                    final_list.append(s)
                    
    return final_list


def preprocess_otter_input(example, input_key):
    """
    Prepares the Otter input string. 
    Handles cases where the input might be a string, a list, 
    or a string representation of a list.
    """
    fol_output_raw = example.get(input_key, '[]')
    
    fol_output_list = make_clean_list(fol_output_raw)

    if not fol_output_list or fol_output_list == ['']:
        return None, "Empty list", None

    # Ensure existence conditions and format for Otter
    try:
        premises_with_existence = _add_existence_condition(fol_output_list[:-1])
        number_premises = len(fol_output_list[:-1])
        return _format_for_otter(premises_with_existence, fol_output_list[-1]), None, number_premises
    except Exception as e:
        return None, f"Otter Formatting Error: {str(e)}", None

######################### Postprocessing Utilities ########################

def postprocess_otter_output(result):
    """Interprets Otter exit codes (103: Proof Found, 104: No Proof)."""
    output_text = result.stdout.decode('utf-8', errors='ignore')
    if result.returncode == 103:
        return True, None
    elif result.returncode == 104:
        return False, None
    else:
        # RETURN None instead of "Error" to keep the column type consistent
        # The error details are preserved in the second return value
        error_msg = f"Exit code {result.returncode}. Snippet: {output_text[:100]}"
        return None, error_msg

# Collecting used clauses from proof
def clean_proof(proof):
    pattern = r"---------------- PROOF ----------------(.*?)------------ end of proof -------------"
    match = re.search(pattern, proof, re.DOTALL)
    return match.group(1).strip() if match else ""

def extract_clauses_used(proof):
    return re.findall(r"\[clausify,(\d+)\]", proof)

def analyze_proof(proof,number_premises):
    # cut out proof
    proof = clean_proof(proof)
    clauses = extract_clauses_used(proof)
    clauses = [int(c)-1 for c in clauses]  # convert to 0-based index
    clauses = list(set(clauses))  # unique clauses
    clauses = [c for c in clauses if c < number_premises]  # only originalpremises
    clauses.sort()
    if  len(clauses) == 0:
        return []
    return clauses





############################## Main Execution Utilities ##############################

def run_otter_proof(item, input_key, otter_command=OTTER_COMMAND, timeout=TIMEOUT_SECONDS):
    """Refined, compact and type-safe Otter execution."""
    example = item.copy()
    
    # Use f-strings for dynamic keys
    ans_key = f'otter_answer_{input_key}'
    err_key = f'otter_error_{input_key}'
    clauses_key = f'otter_used_clauses_{input_key}'

    example[clauses_key] = []
    
    final_input, err_msg, number_premises = preprocess_otter_input(example, input_key)
    if err_msg:
        example.update({ans_key: None, err_key: err_msg})
        return example

    try:
        res = subprocess.run(otter_command, input=final_input.encode('utf-8'),
                             capture_output=True, timeout=timeout + 5, shell=True)
        
        proof_found, err = postprocess_otter_output(res)
        stdout = res.stdout.decode('utf-8', errors='ignore')
        
        # Consistent types: proof_found is True/False, errors are strings
        example.update({
            ans_key: proof_found,
            err_key: err,
            f'otter_input_cleaned_{input_key}': final_input,
            f'otter_proof_{input_key}': stdout,
            f'otter_used_clauses_{input_key}': analyze_proof(stdout, number_premises) if proof_found is True else []
        })
    except Exception as e:
        # Crucial: Use None instead of "Error" string to keep the column type numeric/boolean
        example.update({ans_key: None, err_key: str(e)})
    
    return example


def evaluate_dataset_with_otter(dataset, input_key='fol_output', output_file=None, max_workers=4):
    """
    Runs Otter proofs in parallel for an entire dataset.
    Input_key must point to a list of FOL strings.
    """
    results = []
    data_list = list(dataset)
    
    print(f"🚀 Starting parallel Otter proofs | Key: '{input_key}' | Items: {len(data_list)}")
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        # Submit tasks
        future_to_item = {
            executor.submit(run_otter_proof, item, input_key): item 
            for item in data_list
        }
        
        # Collect results with progress bar
        for future in tqdm(concurrent.futures.as_completed(future_to_item), total=len(data_list), desc="Proving"):
            try:
                results.append(future.result())
            except Exception as e:
                print(f"❌ Critical error in worker thread: {e}")

    save_data(results, output_file)
    print(f"✅ Results saved to {output_file}")    
    return results