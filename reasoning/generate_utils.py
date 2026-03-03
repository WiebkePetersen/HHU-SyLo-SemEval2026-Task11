import torch
import json
from transformers import pipeline, AutoTokenizer
from transformers import AutoModelForCausalLM
from tqdm.auto import tqdm
from typing import Dict, Any
import ast
import re
import numpy as np


import re
import numpy as np

def format_to_prompt(example, experiment_config, tokenizer):
    """
    Prepares a prompt for the LLM by combining system instructions, 
    few-shot examples, and the current input. 
    Supports Qwen3 'enable_thinking' switch and legacy models.
    """
    model_name = experiment_config.get('model', '').lower()
    messages = []
    
    # Identify model family
    is_gemma = "gemma" in model_name
    is_qwen = "qwen" in model_name

    system_content = experiment_config.get('system_prompt_content', '').strip()

    # 1. & 2. Handle System Prompt and Few-Shot Examples
    first_user_prefix = ""
    if is_gemma and system_content:
        # Gemma workaround: Prepend system prompt to the first user message
        first_user_prefix = f"{system_content}\n\n"
    elif system_content:
        # Standard behavior for Smol, Qwen, Llama
        messages.append({
            "role": "system", 
            "content": system_content
        })

    # Add Few-Shot Examples
    examples = experiment_config.get('examples_list', [])
    for i, (user_input, assistant_output) in enumerate(examples):
        user_text = str(user_input)
        
        if i == 0 and first_user_prefix:
            user_text = first_user_prefix + user_text
            first_user_prefix = "" 

        messages.append({"role": "user", "content": user_text})
        
        # Format assistant output (string or list)
        if isinstance(assistant_output, list):
            formatted_output = str([str(item) for item in assistant_output])
        else:
            formatted_output = str(assistant_output)
            
        messages.append({"role": "assistant", "content": formatted_output})

    # 3. Add Current Task Input
    input_key = experiment_config.get('input_key')
    if input_key not in example:
        raise KeyError(f"❌ Input key '{input_key}' not found in dataset.")

    raw_input = example[input_key]

    # Datatype normalization
    if isinstance(raw_input, (list, np.ndarray)):
        input_text = ". ".join([str(item).strip(".") for item in raw_input]) + "."
    else:
        input_text = str(raw_input)

    if not input_text.strip() or input_text == ".":
        input_text = "[Empty Input Error]"

    if first_user_prefix:
        input_text = first_user_prefix + input_text

    messages.append({"role": "user", "content": input_text})

    # 4. Apply Chat Template with Qwen3 Switch
    # Wir versuchen, das Denken für Qwen zu deaktivieren (Hard Switch)
    template_kwargs = {
        "tokenize": False,
        "add_generation_prompt": True
    }
    
    if is_qwen:
        # Qwen3-spezifisch: Deaktiviere Thinking-Mode für Effizienz
        template_kwargs["enable_thinking"] = False

    try:
        prompt = tokenizer.apply_chat_template(messages, **template_kwargs)
    except TypeError:
        # Falls ein Modell (Llama/Gemma) 'enable_thinking' nicht kennt -> Fehler abfangen
        template_kwargs.pop("enable_thinking", None)
        prompt = tokenizer.apply_chat_template(messages, **template_kwargs)

    # 5. Final Polish for Qwen
    if is_qwen:
        # Entferne hängende Leerzeichen, damit Qwen sofort die Formel startet
        prompt = prompt.rstrip()

    return {"prompt": prompt}

def BACKUP_format_to_prompt(example, experiment_config, tokenizer):
    """
    Prepares a prompt for the LLM by combining system instructions, 
    few-shot examples, and the current input.
    Handles both string inputs and list/ndarray inputs (simplified logic).
    """
    messages = []

    # 1. Add System Prompt
    if experiment_config.get('system_prompt_content'):
        messages.append({
            "role": "system", 
            "content": experiment_config['system_prompt_content']
        })

    # 2. Add Few-Shot Examples from JSON
    # We ensure examples are also formatted correctly as Python list strings
    for user_input, assistant_output in experiment_config.get('examples_list', []):
        messages.append({"role": "user", "content": str(user_input)})
        
        # Ensure assistant output is a string representation of a list if it's a list
        if isinstance(assistant_output, list):
            formatted_output = str([str(item) for item in assistant_output])
        else:
            formatted_output = str(assistant_output)
            
        messages.append({"role": "assistant", "content": formatted_output})

    # 3. Add Current Task Input
    input_key = experiment_config.get('input_key')
    if input_key not in example:
        raise KeyError(f"❌ Input key '{input_key}' not found in dataset. Available: {list(example.keys())}")

    raw_input = example[input_key]

    # --- DATATYPE NORMALIZATION ---
    # Convert lists or numpy arrays to a clean, punctuated string for the model
    if isinstance(raw_input, (list, np.ndarray)):
        # Join: ['A', 'B'] -> "A. B."
        input_text = ". ".join([str(item).strip(".") for item in raw_input]) + "."
    else:
        # Standard string input
        input_text = str(raw_input)

    # Final check: Ensure we don't send an empty user prompt
    if not input_text.strip() or input_text == ".":
        print(f"⚠️ Warning: Empty input for ID {example.get('id', 'unknown')}")
        input_text = "[Empty Input Error]"

    messages.append({"role": "user", "content": input_text})

    # 4. Apply Chat Template
    # tokenize=False returns the raw prompt string
    prompt = tokenizer.apply_chat_template(
        messages, 
        tokenize=False, 
        add_generation_prompt=True
    )
    # Qwen-Spezialbehandlung: 
    # Manchmal fügen Tokenizer ein Leerzeichen oder einen Umbruch zu viel ein.
    # Wir stellen sicher, dass der Prompt exakt mit dem Assistant-Tag endet.
    if "qwen" in model_name.lower():
        prompt = prompt.rstrip() # Entfernt hängende Leerzeichen/Umbruche

    return {"prompt": prompt}

def generate_with_prompt(dataset, experiment_config):
    model_name = experiment_config['model']
    output_key = experiment_config['output_key']
    expected_type = experiment_config.get('output_type', 'string')
    
    # Params aus Config laden mit Fallbacks
    params = experiment_config.get('params', {})
    b_size = params.get('batch_size', 1)
    max_new = params.get('max_new_tokens', 512)
    do_samp = params.get('do_sample', False)
    temp = params.get('temperature', 0.0)
    top_p = params.get('top_p', 1.0)
    rep_pen = params.get('repetition_penalty', 1.0)

    print(f"--- Starte Experiment: {experiment_config['experiment_id']} ---")
    print(f"Settings: Sample={do_samp}, Temp={temp}, RepPen={rep_pen}")

    # Tokenizer & Model setup (wie gehabt)
    tokenizer = AutoTokenizer.from_pretrained(model_name, trust_remote_code=True)
    tokenizer.padding_side = "left" 
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    dtype = torch.bfloat16 if torch.cuda.is_available() and torch.cuda.is_bf16_supported() else torch.float16
    # load model
    model = AutoModelForCausalLM.from_pretrained(
        model_name, torch_dtype=dtype, device_map={"": 0}, 
        trust_remote_code=True, attn_implementation="sdpa"
    )

    # Stop IDs 
    stop_ids = [tokenizer.eos_token_id]
    for s in ["<|im_end|>", "<|eot_id|>", "<|endoftext|>", "</think>"]:
        tid = tokenizer.convert_tokens_to_ids(s)
        if isinstance(tid, int) and tid != tokenizer.unk_token_id:
            stop_ids.append(tid)
    stop_ids = list(set(stop_ids))

    results = []
    prompts = dataset['prompt']

    for i in tqdm(range(0, len(prompts), b_size), desc="Processing Batches"):
        batch_prompts = prompts[i:i+b_size]
        inputs = tokenizer(batch_prompts, return_tensors="pt", padding=True, truncation=True, max_length=2048).to("cuda")
        
        with torch.no_grad():
            output_ids = model.generate(
                **inputs,
                max_new_tokens=max_new,
                do_sample=do_samp,      # Aus Config
                temperature=temp if do_samp else None, # Temp nur bei Sampling
                top_p=top_p if do_samp else None,
                repetition_penalty=rep_pen, # Aus Config
                eos_token_id=stop_ids,
                pad_token_id=tokenizer.pad_token_id,
                min_new_tokens=1
            )

        new_tokens = output_ids[:, inputs["input_ids"].shape[1]:]
        batch_responses = tokenizer.batch_decode(new_tokens, skip_special_tokens=True)
        if i == 0: 
            print(f"\n--- Erster Output Test ---\n{batch_responses[0]}\n--------------------------")

        for raw_text in batch_responses:
            # 1. Reinigung: Alles vor und inklusive </think> entfernen
            if "</think>" in raw_text:
                raw_text = raw_text.split("</think>")[-1]
            
            raw_text = raw_text.strip()

            # 2. Parsing: String in Liste umwandeln, falls gefordert
            if expected_type == 'list':
                try:
                    # Versuch 1: Echtes Python-Literal (sicherste Methode)
                    import ast
                    parsed_val = ast.literal_eval(raw_text)
                    results.append(parsed_val if isinstance(parsed_val, list) else [str(parsed_val)])
                except Exception:
                    # Versuch 2: Fallback, falls das Modell Klammern vergessen hat oder Text davor steht
                    # Wir entfernen eckige Klammern und splitten am Komma
                    clean = raw_text.strip("[] ")
                    # Falls das Modell die Formeln einfach untereinander geschrieben hat:
                    if '\n' in clean and ',' not in clean:
                        lines = [s.strip() for s in clean.split('\n') if s.strip()]
                        results.append(lines)
                    else:
                        results.append([s.strip() for s in clean.split(',') if s.strip()])
            else:
                # Normaler String-Output
                results.append(raw_text)

    # Speicher Cleanup
    del model
    del tokenizer
    import gc
    gc.collect()
    torch.cuda.empty_cache()

    if output_key in dataset.column_names:
        dataset = dataset.remove_columns(output_key)
    return dataset.add_column(output_key, results)







def BACKUP_generate_with_prompt(dataset, experiment_config):
    model_name = experiment_config['model']
    output_key = experiment_config['output_key']
    # Default to string if not specified, for safety
    expected_type = experiment_config.get('output_type', 'string')

    print(f"--- Starte Experiment: {experiment_config['experiment_id']} (Type: {expected_type}) ---")

    tokenizer = AutoTokenizer.from_pretrained(model_name, trust_remote_code=True)
    # Ensure pad_token exists (essential for batching)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token
    tokenizer.padding_side = "left"
    
    pipe = pipeline(
        "text-generation",
        model=model_name,
        tokenizer=tokenizer,
        device=0,
        torch_dtype=torch.float16
    )

    def stream_prompts():
        for p in dataset['prompt']:
            yield str(p)

    params = experiment_config.get('params', {})
    b_size = params.get('batch_size', 8)

    results = []
    stop_ids = [tokenizer.eos_token_id]
    # Falls das Modell ein spezielles Ende-Token für Chats hat:
    if tokenizer.convert_tokens_to_ids("<|eot_id|>") is not None:
        stop_ids.append(tokenizer.convert_tokens_to_ids("<|eot_id|>"))
    if tokenizer.convert_tokens_to_ids("<|im_end|>") is not None:
        stop_ids.append(tokenizer.convert_tokens_to_ids("<|im_end|>"))
    for out in tqdm(pipe(stream_prompts(),
                         batch_size=b_size,
                         max_new_tokens=params.get('max_new_tokens', 256),
                         do_sample=False,
                         eos_token_id=stop_ids,
                         pad_token_id=tokenizer.pad_token_id,
                         temperature=None,
                         return_full_text=False),
                    total=len(dataset)):
        
        raw_text = out[0]['generated_text'].strip()
        
        if expected_type == 'list':
            try:
                # 1. Try to parse as real Python list
                parsed_val = ast.literal_eval(raw_text)
                if isinstance(parsed_val, list):
                    results.append(parsed_val)
                else:
                    results.append([str(parsed_val)])
            except Exception:
                # 2. Fallback: Clean string and split by comma if parsing fails
                clean = raw_text.strip("[] ")
                results.append([s.strip() for s in clean.split(',') if s.strip()])
        else:
            # For 'string' output type (e.g. Prolog)
            results.append(raw_text)

    if output_key in dataset.column_names:
        dataset = dataset.remove_columns(output_key)

    return dataset.add_column(output_key, results)