import json
import os
import math
import pandas as pd
import sys
from typing import List, Dict, Any, Tuple, Optional

"""
ADAPTATION NOTICE: 
This script contains adaptations of the official evaluation scripts provided by the 
SemEval-2026 Task 11 Shared Task organizers. 
- Subtasks 1 & 3: Focus on Validity Accuracy and Content Effect Bias.
- Subtasks 2 & 4: Focus on Validity Accuracy, Premise Retrieval F1, and Content Effect Bias.
"""

# --- 1. SHARED INTERNAL HELPERS (OFFICIAL LOGIC) ---

def _calculate_accuracy(
    ground_truth_list: List[Dict[str, Any]],
    predictions_list: List[Dict[str, Any]],
    metric_name: str,
    prediction_key: str,
    plausibility_filter: Optional[bool] = None
) -> Tuple[float, int, int]:
    """
    Calculates the accuracy of 'validity' predictions against ground truth labels,
    with an optional filter based on ground truth 'plausibility'.
    """
    gt_map = {item['id']: item for item in ground_truth_list}

    correct_predictions = 0
    total_predictions = 0

    for pred_item in predictions_list:
        item_id = pred_item['id']
        
        if item_id in gt_map:
            gt_item = gt_map[item_id]
            
            gt_plausibility = gt_item.get('plausibility')
            if plausibility_filter is not None and gt_plausibility != plausibility_filter:
                continue 
            
            if metric_name in gt_item and prediction_key in pred_item:
                true_label = gt_item[metric_name]
                predicted_label = pred_item[prediction_key]

                if isinstance(true_label, bool) and isinstance(predicted_label, bool):
                    total_predictions += 1
                    if true_label == predicted_label:
                        correct_predictions += 1

    if total_predictions == 0:
        return 0.0, 0, 0

    accuracy = (correct_predictions / total_predictions) * 100
    return accuracy, correct_predictions, total_predictions

def _calculate_subgroup_accuracy(gt_map, predictions_list, gt_validity, gt_plausibility):
    """Calculates accuracy for specific subgroups defined by validity and plausibility."""
    correct, total = 0, 0
    for pred_item in predictions_list:
        item_id = pred_item['id']
        if item_id in gt_map:
            gt_item = gt_map[item_id]
            if gt_item.get('validity') == gt_validity and gt_item.get('plausibility') == gt_plausibility:
                total += 1
                if gt_item.get('validity') == pred_item.get('validity'):
                    correct += 1
    return (correct / total * 100) if total > 0 else 0.0

def _calculate_content_effect_bias(accuracies: Dict[str, float]) -> float:
    """Calculates the combined content effect bias metric."""
    acc_pv = accuracies.get('acc_plausible_valid', 0.0)
    acc_iv = accuracies.get('acc_implausible_valid', 0.0)
    acc_pi = accuracies.get('acc_plausible_invalid', 0.0)
    acc_ii = accuracies.get('acc_implausible_invalid', 0.0)

    intra = (abs(acc_pv - acc_iv) + abs(acc_pi - acc_ii)) / 2.0
    inter = (abs(acc_pv - acc_pi) + abs(acc_iv - acc_ii)) / 2.0
    return (intra + inter) / 2.0

def _calculate_f1_premises(gt_map: Dict[str, Any], predictions: List[Dict[str, Any]]) -> float:
    """Calculates Macro-Averaged F1-Score for premise retrieval."""
    total_precision, total_recall, valid_count = 0.0, 0.0, 0
    for pred_item in predictions:
        item_id = pred_item['id']
        if item_id in gt_map and 'relevant_premises' in gt_map[item_id] and 'relevant_premises' in pred_item:
            true_pos = set(gt_map[item_id]['relevant_premises'])
            pred_pos = set(pred_item['relevant_premises'])
            if len(true_pos) == 0: continue
            
            tp = len(true_pos.intersection(pred_pos))
            precision = tp / len(pred_pos) if len(pred_pos) > 0 else 0.0
            recall = tp / len(true_pos)
            total_precision += precision
            total_recall += recall
            valid_count += 1
            
    if valid_count == 0: return 0.0
    m_prec, m_rec = total_precision / valid_count, total_recall / valid_count
    return (2 * m_prec * m_rec / (m_prec + m_rec) * 100) if (m_prec + m_rec) > 0 else 0.0

# --- 2. PUBLIC EVALUATION FUNCTIONS ---

def evaluate_subtask_1_3(reference_path: str, prediction_path: str, output_path: str = None):
    """Evaluation for Tasks 1 & 3: Validity Accuracy + Content Effect Bias."""
    with open(reference_path, 'r', encoding='utf-8') as f:
        gt = json.load(f)
    with open(prediction_path, 'r', encoding='utf-8') as f:
        pred = json.load(f)    
    
    gt_map = {item['id']: item for item in gt}

    overall_acc, _, _ = _calculate_accuracy(gt, pred, 'validity', 'validity')
    
    accuracies = {
        'acc_plausible_valid': _calculate_subgroup_accuracy(gt_map, pred, True, True),
        'acc_implausible_valid': _calculate_subgroup_accuracy(gt_map, pred, True, False),
        'acc_plausible_invalid': _calculate_subgroup_accuracy(gt_map, pred, False, True),
        'acc_implausible_invalid': _calculate_subgroup_accuracy(gt_map, pred, False, False)
    }
    
    bias = _calculate_content_effect_bias(accuracies)
    combined = overall_acc / (1 + math.log(1 + bias))
    
    results = {'accuracy': round(overall_acc, 4), 'content_effect': round(bias, 4), 'combined_score': round(combined, 4)}
    if output_path: 
        os.makedirs(os.path.dirname(output_path), exist_ok=True) if os.path.dirname(output_path) else None
        with open(output_path, 'w', encoding='utf-8') as f: json.dump(results, f, indent=4)
    return results    

def evaluate_subtask_2_4(reference_path: str, prediction_path: str, output_path: str = None):
    """Evaluation for Tasks 2 & 4: Validity Accuracy + Premise F1 + Content Effect Bias."""
    with open(reference_path, 'r', encoding='utf-8') as f:
        gt = json.load(f)
    with open(prediction_path, 'r', encoding='utf-8') as f:
        pred = json.load(f)    
    gt_map = {item['id']: item for item in gt}
    gt_map = {item['id']: item for item in gt}

    f1_premises = _calculate_f1_premises(gt_map, pred)
    overall_acc, _, _ = _calculate_accuracy(gt, pred, 'validity', 'validity')
    
    accuracies = {
        'acc_plausible_valid': _calculate_subgroup_accuracy(gt_map, pred, True, True),
        'acc_implausible_valid': _calculate_subgroup_accuracy(gt_map, pred, True, False),
        'acc_plausible_invalid': _calculate_subgroup_accuracy(gt_map, pred, False, True),
        'acc_implausible_invalid': _calculate_subgroup_accuracy(gt_map, pred, False, False)
    }
    
    bias = _calculate_content_effect_bias(accuracies)
    overall_perf = (overall_acc + f1_premises) / 2.0
    combined = overall_perf / (1 + math.log(1 + bias))
    
    results = {
        'accuracy': round(overall_acc, 4),
        'f1_premises': round(f1_premises, 4),
        'content_effect': round(bias, 4),
        'combined_score': round(combined, 4)
    }
    if output_path: 
        os.makedirs(os.path.dirname(output_path), exist_ok=True) if os.path.dirname(output_path) else None
        with open(output_path, 'w', encoding='utf-8') as f: json.dump(results, f, indent=4)
    return results



import math
import pandas as pd

def my_evaluate_subtask_1_3(df):
    """
    Strikte Umsetzung der offiziellen Evaluationslogik auf pd.DataFrame Basis.
    """
    # 1. Overall Accuracy (0-100)
    overall_acc = (df['validity'] == df['prediction']).mean() * 100

    # 2. Subgroup Accuracies (0-100)
    def get_sub_acc(is_valid, is_plausible):
        subset = df[(df['validity'] == is_valid) & (df['plausibility'] == is_plausible)]
        if len(subset) == 0: return 0.0
        return (subset['validity'] == subset['prediction']).mean() * 100

    accs = {
        'acc_plausible_valid': get_sub_acc(True, True),
        'acc_implausible_valid': get_sub_acc(True, False),
        'acc_plausible_invalid': get_sub_acc(False, True),
        'acc_implausible_invalid': get_sub_acc(False, False)
    }

    # 3. Content Effect Bias (wie im offiziellen Skript)
    # Intra-validity label effect
    intra_diff = (abs(accs['acc_plausible_valid'] - accs['acc_implausible_valid']) + 
                  abs(accs['acc_plausible_invalid'] - accs['acc_implausible_invalid'])) / 2.0
    
    # Inter-validity label effect
    inter_diff = (abs(accs['acc_plausible_valid'] - accs['acc_plausible_invalid']) + 
                  abs(accs['acc_implausible_valid'] - accs['acc_implausible_invalid'])) / 2.0
    
    tot_content_effect = (intra_diff + inter_diff) / 2.0

    # 4. Combined Metric (Smooth Score)
    # Formel: accuracy / (1 + ln(1 + content_effect))
    combined_score = overall_acc / (1 + math.log(1 + tot_content_effect))

    return {
        'accuracy': round(overall_acc, 4),
        'content_effect': round(tot_content_effect, 4),
        'combined_score': round(combined_score, 4),
        'intra_bias': round(intra_diff, 4),
        'inter_bias': round(inter_diff, 4),
        **{k: round(v, 4) for k, v in accs.items()}
    }