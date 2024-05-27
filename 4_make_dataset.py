# This script is used to convert snapshots within the same commit into a dataset
import os
import re
import json
import random
from tqdm import tqdm

ROOT_PATH = "./"

def clean_msg(msg: str):
    # remove pull request id, e.g. (#1234)
    pr_id_pattern = r'\(#(\d+)\)'
    msg = re.sub(pr_id_pattern, '', msg)

    return msg

def make_dataset(lang, dataset_name: str, snapshots_by_commit = None, auto_save = True):
    if snapshots_by_commit is None:
        with open(os.path.join(ROOT_PATH, "qualified_commit", f"{lang}_qualified_commit_snapshots.json"), "r") as f:
            snapshots_by_commit = json.load(f)
    
    with open(os.path.join(ROOT_PATH, "commit_info", f"{lang}_commit_info.jsonl"), "r") as f:
        commits_info = [json.loads(line) for line in f.readlines()]
    
    dataset = {}
    for commit_idx, (commit_url, snapshots) in enumerate(tqdm(snapshots_by_commit.items())):
        dataset[commit_url] = {}
        # find commit msg
        for commit_info in commits_info:
            if commit_url == commit_info["html_url"]:
                commit_msg = commit_info["commit"]["message"]
                break
        dataset[commit_url]["commit_msg"] = clean_msg(commit_msg)
        
        # assign id to each hunk
        hunk_id = 0
        for file_path, snapshot in snapshots.items():
            for window in snapshot:
                if type(window) is dict:
                    window["id"] = hunk_id
                    hunk_id += 1
        
        dataset[commit_url]["hunks"] = []
        # make hunks (hunks are used for generator)
        for file_path, snapshot in snapshots.items():
            line_count = 0
            for window_idx, window in enumerate(snapshot):
                if type(window) is list:
                    line_count += len(window)
                elif type(window) is dict: 
                    hunk = {}
                    # find prior context and prior labels
                    if window_idx == 0: # if there's no prior context
                        prior_context = []
                        prior_inline_labels = []
                        prior_inter_labels = []
                    else:
                        prior_window = snapshot[window_idx - 1]
                        assert type(prior_window) is list
                        prior_context_lines = min(len(prior_window), random.choice([3, 4, 5]))
                        # extract the last few lines as prior context
                        prior_context = prior_window[-prior_context_lines:]
                        prior_inline_labels = ["keep"] * len(prior_context)
                        prior_inter_labels = ["keep"] * len(prior_context)
                    # find posterior context and posterior labels
                    if window_idx == len(snapshot) - 1: # if there's no posterior context
                        posterior_context = []
                        posterior_inline_labels = []
                        posterior_inter_labels = []
                    else:
                        posterior_window = snapshot[window_idx + 1]
                        assert type(posterior_window) is list
                        posterior_context_lines = min(len(posterior_window), random.choice([3, 4, 5]))
                        # extract the first few lines as posterior context
                        posterior_context = posterior_window[:posterior_context_lines]
                        posterior_inline_labels = ["keep"] * len(posterior_context)
                        posterior_inter_labels = ["keep"] * len(posterior_context)
                    hunk["id"] = window["id"]
                    target_window_len = len(window["before"])
                    if window["type"] == "insert":
                        target_code_window = []
                        target_inline_labels = []
                        target_inter_labels = ["insert"]
                    elif window["type"] == "delete":
                        target_code_window = window["before"]
                        target_inline_labels = ["delete"] * len(window["before"])
                        target_inter_labels = ["keep"] * (len(window["before"]) + 1)
                    elif window["type"] == "replace":
                        target_code_window = window["blocks"]
                        target_inline_labels = []
                        target_inter_labels = []
                        insert_label = []
                        for block_idx, block in enumerate(window["blocks"]):
                            if block["block_type"] == "delete":
                                target_inline_labels += ["delete"] * len(block["before"])
                                target_inter_labels += insert_label + ["keep"] * (len(block["before"]) - len(insert_label))
                                insert_label = []
                            elif block["block_type"] == "modify":
                                target_inline_labels += ["replace"] * len(block["before"])
                                if block_idx != 0 and window["blocks"][block_idx - 1]["block_type"] == "modify": 
                                    # if we have 2 consecutive modify blocks, use <block-split> label to separate them
                                    target_inter_labels += ["block-split"] + ["keep"] * (len(block["before"]) - 1)
                                else:
                                    target_inter_labels += insert_label + ["keep"] * (len(block["before"]) - len(insert_label))
                                insert_label = []
                            elif block["block_type"] == "insert":
                                insert_label = ["insert"]
                            else:
                                print(block["block_type"])
                                raise ValueError("Invalid block type")
                        target_inter_labels += insert_label + ["keep"] * (1 - len(insert_label))
                    else:
                        raise ValueError("Invalid window type")
                    hunk["code_window"] = prior_context + target_code_window + posterior_context
                    hunk["inline_labels"] = prior_inline_labels + target_inline_labels + posterior_inline_labels
                    hunk["inter_labels"] = prior_inter_labels + target_inter_labels + posterior_inter_labels
                    code_window_len = len(prior_context) + target_window_len + len(posterior_context)
                    assert code_window_len == len(hunk["inline_labels"])
                    assert code_window_len + 1 == len(hunk["inter_labels"])
                    hunk["after_edit"] = window["after"]
                    hunk["file_path"] = file_path
                    hunk["type"] = window["type"]
                    hunk["edit_start_line_idx"] = line_count
                    line_count += len(window["before"])
                    dataset[commit_url]["hunks"].append(hunk)        

        # make sliding windows (sliding windows are used for edit locator)
        """
        Sliding window there's 3 types:
            1. Overlap with 1 or more edit hunk
            2. Overlap with 0 edit hunk, should be 1/3 of type 1
            3. What code looks like after edit has been applied
        """
        # sample type 1 sliding windows
        dataset[commit_url]["sliding_windows"] = []
        sliding_window_len = 10
        for file_path, snapshot in snapshots.items():
            line_count = 0
            sliding_window = { # initialize a sliding window
                "code_window": [],
                "inline_labels": [],
                "inter_labels": [],
                "overlap_hunk_ids": [],
                "file_path": file_path,
                "edit_start_line_idx": line_count
            }
            insert_label = "keep"
            for window_idx, window in enumerate(snapshot):
                if type(window) is list:
                    for code_line in window:
                        # if existing sliding window is full, append it to dataset and create a new one
                        if len(sliding_window["code_window"]) == sliding_window_len:
                            sliding_window["inter_labels"].append(insert_label)
                            if insert_label == "insert":
                                # not update insert label because it's shared by 2 sliding windows inter labels
                                shared_insert_hunk_id = sliding_window["overlap_hunk_ids"][-1]
                            assert len(sliding_window["code_window"]) == len(sliding_window["inline_labels"])
                            assert len(sliding_window["code_window"]) + 1 == len(sliding_window["inter_labels"])
                            dataset[commit_url]["sliding_windows"].append(sliding_window)
                            sliding_window = { # initialize a sliding window
                                "code_window": [],
                                "inline_labels": [],
                                "inter_labels": [],
                                "overlap_hunk_ids": [],
                                "file_path": file_path,
                                "edit_start_line_idx": line_count
                            }
                        sliding_window["code_window"].append(code_line)
                        sliding_window["inline_labels"].append("keep")
                        # here inter label indicate whether to insert code before each line
                        sliding_window["inter_labels"].append(insert_label)
                        if insert_label == "insert":
                            if shared_insert_hunk_id not in sliding_window["overlap_hunk_ids"]:
                                sliding_window["overlap_hunk_ids"].append(shared_insert_hunk_id)
                            insert_label = "keep"
                        line_count += 1
                elif type(window) is dict:
                    hunk_id = window["id"]
                    # case 1: it's an insert hunk
                    if window["type"] == "insert":
                        insert_label = "insert"
                        if hunk_id not in sliding_window["overlap_hunk_ids"]:
                            sliding_window["overlap_hunk_ids"].append(hunk_id)
                        shared_insert_hunk_id = hunk_id
                    # case 2: it's a delete hunk
                    elif window["type"] == "delete":
                        for code_line in window["before"]:
                            if len(sliding_window["code_window"]) == sliding_window_len:
                                sliding_window["inter_labels"].append(insert_label)
                                if insert_label == "insert":
                                    # not update insert label because it's shared by 2 sliding windows inter labels
                                    shared_insert_hunk_id = sliding_window["overlap_hunk_ids"][-1]
                                assert len(sliding_window["code_window"]) == len(sliding_window["inline_labels"])
                                assert len(sliding_window["code_window"]) + 1 == len(sliding_window["inter_labels"])
                                dataset[commit_url]["sliding_windows"].append(sliding_window)
                                sliding_window = { # initialize a sliding window
                                    "code_window": [],
                                    "inline_labels": [],
                                    "inter_labels": [],
                                    "overlap_hunk_ids": [],
                                    "file_path": file_path,
                                    "edit_start_line_idx": line_count
                                }
                            if hunk_id not in sliding_window["overlap_hunk_ids"]:
                                sliding_window["overlap_hunk_ids"].append(hunk_id)
                            sliding_window["code_window"].append(code_line)
                            sliding_window["inline_labels"].append("delete")
                            sliding_window["inter_labels"].append(insert_label)
                            if insert_label == "insert":
                                if shared_insert_hunk_id not in sliding_window["overlap_hunk_ids"]:
                                    sliding_window["overlap_hunk_ids"].append(shared_insert_hunk_id)
                                insert_label = "keep"
                            line_count += 1
                    # case 3: it's a replace hunk
                    elif window["type"] == "replace":
                        for block_idx, block in enumerate(window["blocks"]):
                            if block["block_type"] == "delete":
                                for code_line in block["before"]:
                                    if len(sliding_window["code_window"]) == sliding_window_len:
                                        sliding_window["inter_labels"].append(insert_label)
                                        if insert_label == "insert":
                                            # not update insert label because it's shared by 2 sliding windows inter labels
                                            shared_insert_hunk_id = sliding_window["overlap_hunk_ids"][-1]
                                        assert len(sliding_window["code_window"]) == len(sliding_window["inline_labels"])
                                        assert len(sliding_window["code_window"]) + 1 == len(sliding_window["inter_labels"])
                                        dataset[commit_url]["sliding_windows"].append(sliding_window)
                                        sliding_window = { # initialize a sliding window
                                            "code_window": [],
                                            "inline_labels": [],
                                            "inter_labels": [],
                                            "overlap_hunk_ids": [],
                                            "file_path": file_path,
                                            "edit_start_line_idx": line_count
                                        }
                                    if hunk_id not in sliding_window["overlap_hunk_ids"]:
                                        sliding_window["overlap_hunk_ids"].append(hunk_id)
                                    sliding_window["code_window"].append(code_line)
                                    sliding_window["inline_labels"].append("delete")
                                    sliding_window["inter_labels"].append(insert_label)
                                    if insert_label == "insert":
                                        if shared_insert_hunk_id not in sliding_window["overlap_hunk_ids"]:
                                            sliding_window["overlap_hunk_ids"].append(shared_insert_hunk_id)
                                        insert_label = "keep"
                                    line_count += 1
                            elif block["block_type"] == "insert":
                                insert_label = "insert"
                                if hunk_id not in sliding_window["overlap_hunk_ids"]:
                                    sliding_window["overlap_hunk_ids"].append(hunk_id)
                                shared_insert_hunk_id = hunk_id
                            elif block["block_type"] == "modify":
                                for code_line_idx, code_line in enumerate(block["before"]):
                                    if len(sliding_window["code_window"]) == sliding_window_len:
                                        sliding_window["inter_labels"].append(insert_label)
                                        if insert_label == "insert":
                                            # not update insert label because it's shared by 2 sliding windows inter labels
                                            shared_insert_hunk_id = sliding_window["overlap_hunk_ids"][-1]
                                        assert len(sliding_window["code_window"]) == len(sliding_window["inline_labels"])
                                        assert len(sliding_window["code_window"]) + 1 == len(sliding_window["inter_labels"])
                                        dataset[commit_url]["sliding_windows"].append(sliding_window)
                                        sliding_window = { # initialize a sliding window
                                            "code_window": [],
                                            "inline_labels": [],
                                            "inter_labels": [],
                                            "overlap_hunk_ids": [],
                                            "file_path": file_path,
                                            "edit_start_line_idx": line_count
                                        }
                                    if block_idx != 0 and window["blocks"][block_idx - 1]["block_type"] == "modify" and code_line_idx == 0 and len(sliding_window["code_window"]) != 0:
                                        # if we have 2 consecutive modify blocks, and we can see both of them in the same sliding window, use <block-split> label to separate them
                                        sliding_window["inter_labels"].append("block-split")
                                    else:
                                        sliding_window["inter_labels"].append(insert_label)
                                    if hunk_id not in sliding_window["overlap_hunk_ids"]:
                                        sliding_window["overlap_hunk_ids"].append(hunk_id)
                                    sliding_window["code_window"].append(code_line)
                                    sliding_window["inline_labels"].append("replace")
                                    if insert_label == "insert":
                                        if shared_insert_hunk_id not in sliding_window["overlap_hunk_ids"]:
                                            sliding_window["overlap_hunk_ids"].append(shared_insert_hunk_id)
                                        insert_label = "keep"
                                    line_count += 1
        
        # Sample type 2 sliding windows and reduce their number of 1/3 of type 1
        all_sliding_windows = dataset[commit_url]["sliding_windows"]
        type2_sliding_windows = []
        type1_sliding_windows = []
        for sliding_window in all_sliding_windows:
            if sliding_window["overlap_hunk_ids"] == []:
                type2_sliding_windows.append(sliding_window)
            else:
                type1_sliding_windows.append(sliding_window)
        if len(type2_sliding_windows) != 0:
            sample_number = max(1, len(type1_sliding_windows) // 3)
            sample_number = min(sample_number, len(type2_sliding_windows))
            type2_sliding_windows = random.sample(type2_sliding_windows, sample_number)
            # shuffle type 1 and type 2 sliding windows
            sampled_all_sliding_windows = type1_sliding_windows + type2_sliding_windows
            random.shuffle(sampled_all_sliding_windows)
            dataset[commit_url]["sliding_windows"] = sampled_all_sliding_windows
            
        # Make type 3 sliding windows
        for file_path, snapshot in snapshots.items():
            line_count = 0
            for window_idx, window in enumerate(snapshot):
                if type(window) is not dict:
                    line_count += len(window)
                    continue
                sliding_window = { # initialize a sliding window
                    "code_window": [],
                    "inline_labels": [],
                    "inter_labels": [],
                    "overlap_hunk_ids": [], # because the overlapped edit has happened, we can use it as prior edit
                    "file_path": file_path,
                    "edit_start_line_idx": line_count
                }
                # find prior context and prior labels
                if window_idx != 0:
                    prior_context_lines = min(len(snapshot[window_idx - 1]), random.choice([3, 4, 5]))
                    prior_context = snapshot[window_idx - 1][-prior_context_lines:]
                    sliding_window["code_window"] += prior_context
                    sliding_window["inline_labels"] += ["keep"] * prior_context_lines
                    sliding_window["inter_labels"] += ["keep"] * prior_context_lines
                # add the code after edit and label as keep
                if window["type"] == "delete":
                    continue
                elif window["type"] == "insert":
                    sliding_window["code_window"] += window["after"]
                    sliding_window["inline_labels"] += ["keep"] * len(window["after"])
                    sliding_window["inter_labels"] += ["keep"] * len(window["after"])
                elif window["type"] == "replace":
                    for block_idx, block in enumerate(window["blocks"]):
                        if block["block_type"] == "delete":
                            continue
                        elif block["block_type"] == "insert":
                            sliding_window["code_window"] += block["after"]
                            sliding_window["inline_labels"] += ["keep"] * len(block["after"])
                            sliding_window["inter_labels"] += ["keep"] * len(block["after"])
                        elif block["block_type"] == "modify":
                            sliding_window["code_window"] += block["after"]
                            sliding_window["inline_labels"] += ["keep"] * len(block["after"])
                            if block_idx != 0 and window["blocks"][block_idx - 1]["block_type"] == "modify":
                                sliding_window["inter_labels"] += ["block-split"] + ["keep"] * (len(block["after"]) - 1)
                            else:
                                sliding_window["inter_labels"] += ["keep"] * len(block["after"])
                        else:
                            raise ValueError("Invalid block type")
                # find posterior context and posterior labels
                if window_idx != len(snapshot) - 1:
                    posterior_context_lines = min(len(snapshot[window_idx + 1]), sliding_window_len - len(sliding_window["code_window"]))
                    posterior_context = snapshot[window_idx + 1][:posterior_context_lines]
                    sliding_window["code_window"] += posterior_context
                    sliding_window["inline_labels"] += ["keep"] * len(posterior_context)
                    sliding_window["inter_labels"] += ["keep"] * len(posterior_context)
                if len(sliding_window["code_window"]) > 5 and len(sliding_window["code_window"]) < 15:
                    sliding_window["inter_labels"].append("keep")
                    assert len(sliding_window["code_window"]) == len(sliding_window["inline_labels"])
                    assert len(sliding_window["code_window"]) + 1 == len(sliding_window["inter_labels"])
                    dataset[commit_url]["sliding_windows"].append(sliding_window)
    
    if not os.path.exists(os.path.join(ROOT_PATH, dataset_name, lang)):
        os.makedirs(os.path.join(ROOT_PATH, dataset_name, lang)) 
    
    if auto_save:
        # extract 70% of dataset as training set, 10% as dev set, 20% as test sets
        train_dataset = {}
        dev_dataset = {}
        test_dataset = {}
        dataset_size = len(dataset)
        for idx, (commit_url, data) in enumerate(dataset.items()):
            if idx < dataset_size * 0.7:
                train_dataset[commit_url] = data
            elif idx < dataset_size * 0.8:
                dev_dataset[commit_url] = data
            else:
                test_dataset[commit_url] = data
        with open(os.path.join(ROOT_PATH, dataset_name, lang, "train.json"), "w") as f:
            json.dump(train_dataset, f, indent=4)
        with open(os.path.join(ROOT_PATH, dataset_name, lang, "dev.json"), "w") as f:
            json.dump(dev_dataset, f, indent=4)
        with open(os.path.join(ROOT_PATH, dataset_name, lang, "test.json"), "w") as f:
            json.dump(test_dataset, f, indent=4)        
    else:
        return dataset

if __name__ == "__main__":
    make_dataset("python", "fine_grain_dataset")