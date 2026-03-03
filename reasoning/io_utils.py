import json
import requests
import os
import yaml
from datasets import Dataset
import pandas as pd
from pathlib import Path
import ast
from io import BytesIO



def load_config(path):
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def save_data(data, path):
    """
    Saves data to Parquet. 
    If path is None, the function returns without doing anything.
    Forces all columns to 'object' type to prevent schema/type conflicts.
    """
    # 1. Skip if path is None or data is missing
    if path is None:
        return
    
    if data is None:
        print("⚠️ No data to save.")
        return

    # 2. Convert to DataFrame based on input type
    if hasattr(data, 'to_pandas'):
        df = data.to_pandas()
    elif isinstance(data, list):
        df = pd.DataFrame(data)
    else:
        df = pd.DataFrame(data)

    # 3. Universal Fix: Cast everything to object 
    for col in df.columns:
        df[col] = df[col].astype(object)

    # 4. Create directory if needed
    folder = os.path.dirname(path)
    if folder and not os.path.exists(folder):
        os.makedirs(folder)

    # 5. Save as Parquet
    try:
        df.to_parquet(path, index=False, engine='pyarrow')
        print(f"✅ Saved {len(df)} rows to: {path}")
    except Exception as e:
        print(f"❌ Error saving Parquet to {path}: {e}")


def load_data(path_or_url, return_dataset=True):
    """
    Loads data from a URL or local path using Parquet.
    Guarantees that lists, tuples, and nested structures are preserved.
    """
    if path_or_url.startswith(("http://", "https://")):
        # Fetch from URL
        response = requests.get(path_or_url)
        response.raise_for_status()
        # Read the binary content into pandas
        df = pd.read_parquet(BytesIO(response.content))
    else:
        # Load from local file
        df = pd.read_parquet(path_or_url)

    # Convert to Hugging Face Dataset if requested
    if return_dataset:
        # Since Parquet already has a strict schema, 
        # the conversion to Dataset is safe and fast.
        return Dataset.from_pandas(df, preserve_index=False)
    
    # Return as list of dictionaries
    return df.to_dict(orient='records')



def create_predictions_file(data, predictions_key, subtask, used_clauses_key=None, output_file="predictions.json"):
    """
    Processes model answers into binary validity or premise selection based on subtask.
    Saves results as a standard JSON file.
    """
    # 1. Convert to DataFrame
    df = pd.DataFrame(data)
    
    # Check if base 'id' column exists
    if 'id' not in df.columns:
        raise KeyError("Missing 'id' column in the input data.")

    # 2. Mapping logic for validity (Booleans)
    def _map_validity(answer):
        return True if answer is True else False

    # 3. Create prediction structure
    prediction_df = pd.DataFrame()
    prediction_df["id"] = df["id"]
    
    prediction_df["validity"] = df[predictions_key].apply(_map_validity)
    
    # Logic for Subtask 2 & 4: Relevant Premises
    if subtask in ["subtask2", "subtask4"]:
        if used_clauses_key not in df.columns:
             raise KeyError(f"Missing used_clauses_key '{used_clauses_key}' for {subtask}.")
        # Copies the clauses (e.g., list of strings or indices) to the new column
        prediction_df["relevant_premises"] = df[used_clauses_key]

    # 4. Convert to list of dictionaries
    prediction_list = prediction_df.to_dict(orient='records')
    
    # 5. Save as JSON
    try:
        folder = os.path.dirname(output_file)
        if folder and not os.path.exists(folder):
            os.makedirs(folder)
            
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(prediction_list, f, indent=4)
            
        print(f"✅ Prediction file created: {output_file} (Subtask: {subtask}, Rows: {len(prediction_list)})")
    except Exception as e:
        print(f"❌ Failed to write JSON file: {e}")
    
    return prediction_list


def list_apply(data_list, target_key, func, new_key=None):
    """
    Applies a function to a specific key in a list of dictionaries.
    
    Args:
        data_list: The list of dictionaries to process.
        target_key: The key whose value should be transformed.
        func: The function/lambda to apply to the value.
        new_key: Optional. If provided, stores the result in this new key 
                 instead of overwriting the target_key.
                 
    Returns:
        The updated list of dictionaries.
    """
    # Use new_key if provided, otherwise overwrite target_key
    destination = new_key if new_key else target_key
    
    for item in data_list:
        # Get the current value
        current_value = item.get(target_key)
        
        try:
            # Apply the function and store the result
            item[destination] = func(current_value)
        except Exception as e:
            print(f"Error processing item with {target_key}='{current_value}': {e}")
            item[destination] = None # Or handle error as needed
            
    return data_list


import yaml
import json
from pathlib import Path

def get_experiment_config(experiment_id, config_path="experiments.yaml", examples_path="prompts/examples.json"):
    """
    Loads experiment metadata and enriches it with the markdown prompt 
    and the examples list using the keys from your YAML.
    All comments in English.
    """
    # 1. Load the main experiment registry
    with open(config_path, 'r') as f:
        full_config = yaml.safe_load(f)
    
    # Access the dictionary (no list index error anymore)
    if experiment_id not in full_config['experiments']:
        raise ValueError(f"Experiment ID '{experiment_id}' not found in {config_path}")
        
    cfg = full_config['experiments'][experiment_id].copy()
    cfg['experiment_id'] = experiment_id

    # 2. Map the 'system_prompt' key to the markdown file
    # Uses cfg['system_prompt'] from your YAML to find the file
    prompt_file = Path(f"prompts/{cfg['system_prompt']}.md")
    if prompt_file.exists():
        cfg['system_prompt_content'] = prompt_file.read_text(encoding='utf-8')
    else:
        cfg['system_prompt_content'] = None
        print(f"⚠️ Warning: Prompt file {prompt_file} not found.")

    # 3. Map the 'examples' key to the ID in your JSON
    try:
        with open(examples_path, 'r') as f:
            all_examples_data = json.load(f)
        # Uses cfg['examples'] from your YAML to index the JSON
        cfg['examples_list'] = all_examples_data.get(cfg['examples'], [])
    except FileNotFoundError:
        cfg['examples_list'] = []
        print(f"⚠️ Warning: {examples_path} not found.")

    return cfg

# Usage example:
# cfg = get_experiment_config("exp_001_triples")
# print(cfg['system_prompt']) # Raw markdown text
# print(cfg['examples'])      # List of lists/tuples



def merge_datasets_by_id(target_ds, source_data, merge_key, id_key="id", new_key=None):
    """
    Strictly merges a column from source_data into a Hugging Face Dataset.
    target_ds: A datasets.Dataset object.
    source_data: A list of dicts or another Dataset object.
    """
    final_key = new_key if new_key is not None else merge_key

    # 1. Strict Checks
    if len(target_ds) != len(source_data):
        raise ValueError(f"❌ Length mismatch: Target {len(target_ds)} != Source {len(source_data)}")

    if final_key in target_ds.column_names:
        raise ValueError(f"❌ Key Collision: '{final_key}' already exists in target dataset.")

    # 2. Create a lookup mapping from the source
    # This works whether source_data is a list of dicts or a HF Dataset
    source_lookup = {item[id_key]: item[merge_key] for item in source_data}

    # 3. Define the mapping function for .map()
    def add_column_fn(example):
        obj_id = example[id_key]
        if obj_id not in source_lookup:
            raise ValueError(f"❌ ID '{obj_id}' from target not found in source data.")
        
        example[final_key] = source_lookup[obj_id]
        return example

    # 4. Apply the transformation
    # load_from_cache_file=False ensures we don't accidentally load old data
    return target_ds.map(add_column_fn, load_from_cache_file=False)


