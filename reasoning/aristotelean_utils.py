import re
import json
from reasoning.io_utils import load_data, save_data
from tqdm.auto import tqdm
tqdm.pandas(desc="Prolog Query")
import pandas as pd
import ast
from pyswip import Prolog
import os
import gc
import torch
from datasets import Dataset, load_dataset




# --- ARISTOTELEAN MAPPING ---
# We map 'all'->'a', 'no'->'e', 'some'->'i', 'some_not'->'o'
import re

PATTERNS = {
    'some_not': re.compile(r'^some\s+(.+?)\s+(?:is|are)\s+not\s+(.+)$', re.IGNORECASE),
    'all': re.compile(r'^(?:all|every|any)\s+(.+?)\s+(?:is|are)\s+(.+)$', re.IGNORECASE),
    'no': re.compile(r'^no\s+(.+?)\s+(?:is|are)\s+(.+)$', re.IGNORECASE),
    'some': re.compile(r'^some\s+(.+?)\s+(?:is|are)\s+(.+)$', re.IGNORECASE)
}

import re

def _clean(term: str) -> str:
    if not isinstance(term, str):
        return ""
    
    # 1. Standardize to lowercase and use underscores for internal spaces
    term = term.lower().strip().replace(" ", "_")
    
    # 2. Comprehensive filler list (handles both 'word_' and 'word ')
    # We use a combined approach to catch them regardless of how they were joined
    fillers = [
        r'^(piece|type|kind|item|single|some|any|a|an|the)_of_', 
        r'^(some|single|any|a|an|the)_',
        r'^person_who_is_', 
        r'^animal_that_has_',
        r'^shape_that_is_also_',
        r'^item_with_'
    ]
    
    for pattern in fillers:
        term = re.sub(pattern, '', term)
    
    # 3. Security: Remove any leading/trailing underscores that might have been left
    term = term.strip('_')

    # 4. Singularization
    if len(term) > 3 and term.endswith('s'):
        if not term.endswith(('ss', 'us')):
            term = term[:-1]
            
    return term.capitalize()



def sentence_to_aristotelian(sentence: str):
    """
    Returns (Operator, Subject, Predicate)
    """
    s = str(sentence).strip().lower().strip('"').strip("'").rstrip('.')
    
    # Handle Obversion: 'no child is not wood' -> 'all child is wood'
    if s.startswith('no ') and ' is not ' in s:
        s = s.replace('no ', 'all ', 1).replace(' is not ', ' is ', 1)

    for label in ['some_not', 'all', 'no', 'some']:
        match = PATTERNS[label].match(s)
        if match:
            # We always extract Subject first, then Predicate
            subj, pred = match.group(1), match.group(2)
            
            if label == 'all':
                # Handle 'all apple is not citrus' -> 'e'
                if pred.startswith('not '):
                    return ('e', _clean(subj), _clean(pred[4:]))
                return ('a', _clean(subj), _clean(pred))
            
            elif label == 'some_not':
                return ('o', _clean(subj), _clean(pred))
            
            mapping = {'no': 'e', 'some': 'i'}
            return (mapping[label], _clean(subj), _clean(pred))

    return f"ERROR: {sentence}"


def process_dataset_to_aristotelian(input_file, input_key, output_file=None, output_key="aristotelian_output"):
    """
    Processes sentences into Aristotelian triples and saves them 
    as a list of formatted strings: ["('a', 'S', 'P')", ...]
    """
    ds = load_data(input_file, return_dataset=True)

    def translation_helper(example):
        sentences = example.get(input_key, [])
        if not isinstance(sentences, list):
            sentences = [sentences] if sentences else []
            
        formatted_string_triples = []
        for s in sentences:
            t = sentence_to_aristotelian(s)
            # t is expected to be a tuple ('a', 'S', 'P') from sentence_to_aristotelian
            if isinstance(t, tuple) and len(t) == 3:
                # Create a clean string representation for each triple
                # We use repr() for the strings to handle quotes correctly
                op, subj, pred = [str(x).replace("'", "''") for x in t]
                triple_str = f"('{op}', '{subj}', '{pred}')"
                formatted_string_triples.append(triple_str)
        
        example[output_key] = formatted_string_triples
        return example

    ds_processed = ds.map(translation_helper)

    if output_file is not None:
        save_data(ds_processed, output_file)
        print(f"✅ Results saved to {output_file}")
    else:
        print("💡 output_file is None: Results kept in RAM.")
        
    return ds_processed





########### Prolog Aufrufe ##############

# Prolog-Engine initialisieren
prolog = Prolog()

# Prolog-Datei laden
prolog.consult("prolog_syllogism.pl")


def reload_prolog_file(filepath):
    """
    Forces Prolog to unload the file before consulting it again.
    """
    # 1. Unload the file to clear old predicates
    # We use abolish or unload_file depending on the Prolog distribution
    list(prolog.query(f"unload_file('{filepath}')"))
    
    # 2. Consult the file again
    prolog.consult(filepath)
    print(f"🔄 Prolog file '{filepath}' reloaded.")


reload_prolog_file("prolog_syllogism.pl")



# All comments in English
def process_prolog_results(data, input_key, output_prefix="aristotelian"):
    """
    Executes Prolog queries. Since input_key now contains a list of 
    pre-formatted strings like "('a', 'S', 'P')", we can build the 
    Prolog query string directly.
    """
    truth_col = f"{output_prefix}_truth"
    type_col = f"{output_prefix}_type"
    
    # 1. Ensure we are working with a Dataset object
    if not isinstance(data, Dataset):
        ds = Dataset.from_pandas(pd.DataFrame(data))
    else:
        ds = data
    def run_single_query(example):
        items = example.get(input_key)
        
        # Handle empty, None or non-list values
        if not items or not isinstance(items, list):
            return {truth_col: "none", type_col: "none"}
            
        try:
            # 2. Build the Prolog list string directly from the pre-formatted strings
            # items is already e.g. ["('a', 'S', 'P')", "('i', 'P', 'M')"]
            prolog_list_str = "[" + ", ".join(items) + "]"
            
            # 3. Construct and execute the query
            query_str = f"proof({prolog_list_str}, Truth, Type)"
            
            # Note: 'prolog' must be initialized globally (from pyswip)
            results = list(prolog.query(query_str))
            if results:
                # Return the bound values for Truth and Type
                return {
                    truth_col: str(results[0].get("Truth", "false")),
                    type_col: str(results[0].get("Type", "unknown"))
                }
            else:
                # If proof fails (no solution found)
                return {truth_col: "false", type_col: "unknown"}
                
        except Exception as e:
            # Return error info into the columns for debugging
            return {truth_col: "error", type_col: str(e)}
    
    print(f"--- Starting local Prolog inference on '{input_key}' ---")
    
    # 4. Use .map for processing
    # batched=False is crucial as pyswip is not thread-safe and stateful


    # Prolog-Abfrage ausführen
    processed_ds = ds.map(run_single_query, batched=False)

    # Truth Mapping-Funktion definieren
    TRUTH_MAP = {
    "true": True,    # Konvertiert String "true" zu Python Bool True
    "false": False,  # Konvertiert String "false" zu Python Bool False
    "error": False 
    }
    def apply_truth_mapping(example):
        raw_val = str(example[truth_col]).lower()
        example[truth_col] = TRUTH_MAP.get(raw_val, None)
        return example

    processed_ds = processed_ds.map(apply_truth_mapping)
    # 5. Cleanup
    gc.collect()
    
    return processed_ds
# Example usage:
# dataset = process_prolog_results(dataset, 'aristotelian_output', 'prolog_aristotelian')