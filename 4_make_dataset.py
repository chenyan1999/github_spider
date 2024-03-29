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

def make_dataset(lang):
    with open(os.path.join(ROOT_PATH, "qualified_commit", f"{lang}_qualified_commit_snapshots.json"), "r") as f:
        snapshots_by_commit = json.load(f)
    
    with open(os.path.join(ROOT_PATH, "commit_info", f"{lang}_commit_info.jsonl"), "r") as f:
        commits_info = [json.loads(line) for line in f.readlines()]
    
    dataset = {}
    for commit_url, snapshots in tqdm(snapshots_by_commit.items()):
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
                        prior_labels = []
                    else:
                        prior_window = snapshot[window_idx - 1]
                        assert type(prior_window) is list
                        prior_context_lines = min(len(prior_window), random.choice([3, 4, 5]))
                        # extract the last few lines as prior context
                        prior_context = prior_window[-prior_context_lines:]
                        prior_labels = ["keep"] * len(prior_context)
                        if window["type"] == "add":
                            prior_labels[-1] = "add"
                    # find posterior context and posterior labels
                    if window_idx == len(snapshot) - 1: # if there's no posterior context
                        posterior_context = []
                        posterior_labels = []
                    else:
                        posterior_window = snapshot[window_idx + 1]
                        assert type(posterior_window) is list
                        posterior_context_lines = min(len(posterior_window), random.choice([3, 4, 5]))
                        # extract the first few lines as posterior context
                        posterior_context = posterior_window[:posterior_context_lines]
                        posterior_labels = ["keep"] * len(posterior_context)
                    hunk["id"] = window["id"]
                    hunk["code_window"] = prior_context + window["before"] + posterior_context
                    if window["type"] == "add":
                        assert len(window["before"]) == 0
                    hunk["labels"] = prior_labels + ["replace"] * len(window["before"]) + posterior_labels
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
        dataset[commit_url]["sliding_windows"] = []
        sliding_window_len = 10
        for file_path, snapshot in snapshots.items():
            line_count = 0
            sliding_window = { # initialize a sliding window
                "code_window": [],
                "labels": [],
                "overlap_hunk_ids": [],
                "file_path": file_path,
                "edit_start_line_idx": line_count
            }
            for window_idx, window in enumerate(snapshot):
                if type(window) is list:
                    for code_line in window:
                        if len(sliding_window["code_window"]) == sliding_window_len:
                            dataset[commit_url]["sliding_windows"].append(sliding_window)
                            sliding_window = {
                                "code_window": [],
                                "labels": [],
                                "overlap_hunk_ids": [],
                                "file_path": file_path,
                                "edit_start_line_idx": line_count
                            }
                        sliding_window["code_window"].append(code_line)
                        sliding_window["labels"].append("keep")
                        line_count += 1
                elif type(window) is dict:
                    # case 1: it's an add hunk
                    if window["type"] == "add":
                        if len(sliding_window["labels"]) == 0: 
                            # if sliding window is empty, we borrow 2 lines of code, its label and overlap hunk id from previous sliding window
                            sliding_window["code_window"] += dataset[commit_url]["sliding_windows"][-1]["code_window"][-2:]
                            sliding_window["labels"] += dataset[commit_url]["sliding_windows"][-1]["labels"][-2:]
                            if "replace" in sliding_window["labels"] or "add" in sliding_window["labels"]:
                                sliding_window["overlap_hunk_ids"] += dataset[commit_url]["sliding_windows"][-1]["overlap_hunk_ids"][-1:]
                        else:    
                            sliding_window["labels"][-1] = "add"
                        sliding_window["overlap_hunk_ids"].append(window["id"])
                    # case 2: it's a replace hunk
                    elif window["type"] == "replace":
                        for code_line in window["before"]:
                            if len(sliding_window["code_window"]) == sliding_window_len:
                                dataset[commit_url]["sliding_windows"].append(sliding_window)
                                sliding_window = {
                                    "code_window": [],
                                    "labels": [],
                                    "overlap_hunk_ids": [],
                                    "file_path": file_path,
                                    "edit_start_line_idx": line_count
                                }
                            sliding_window["code_window"].append(code_line)
                            sliding_window["labels"].append("replace")
                            line_count += 1
                            if window["id"] not in sliding_window["overlap_hunk_ids"]:
                                sliding_window["overlap_hunk_ids"].append(window["id"])
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
                sliding_window = {
                    "code_window": [],
                    "labels": [],
                    "overlap_hunk_ids": [],
                    "file_path": file_path,
                    "edit_start_line_idx": line_count
                }
                # find prior context and prior labels
                if window_idx != 0:
                    prior_context_lines = min(len(snapshot[window_idx - 1]), random.choice([3, 4, 5]))
                    prior_context = snapshot[window_idx - 1][-prior_context_lines:]
                    prior_context_labels = ["keep"] * prior_context_lines
                    sliding_window["code_window"] += prior_context
                    sliding_window["labels"] += prior_context_labels
                # add the code after edit and label as keep
                for code_line in window["after"]:
                    if len(sliding_window["code_window"]) == sliding_window_len:
                        dataset[commit_url]["sliding_windows"].append(sliding_window)
                        sliding_window = {
                            "code_window": [],
                            "labels": [],
                            "overlap_hunk_ids": [],
                            "file_path": file_path,
                            "edit_start_line_idx": line_count
                        }
                    sliding_window["code_window"].append(code_line)
                    sliding_window["labels"].append("keep")
                    line_count += 1
                # find posterior context and posterior labels
                if window_idx != len(snapshot) - 1:
                    posterior_context_lines = min(len(snapshot[window_idx + 1]), sliding_window_len - len(sliding_window["code_window"]))
                    posterior_context = snapshot[window_idx + 1][:posterior_context_lines]
                    posterior_context_labels = ["keep"] * posterior_context_lines
                    sliding_window["code_window"] += posterior_context
                    sliding_window["labels"] += posterior_context_labels
                if len(sliding_window["code_window"]) > 5:
                    dataset[commit_url]["sliding_windows"].append(sliding_window)
    
    if not os.path.exists(os.path.join(ROOT_PATH, "new_dataset", lang)):
        os.makedirs(os.path.join(ROOT_PATH, "new_dataset", lang)) 
    
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
    with open(os.path.join(ROOT_PATH, "new_dataset", lang, "train.json"), "w") as f:
        json.dump(train_dataset, f, indent=4)
    with open(os.path.join(ROOT_PATH, "new_dataset", lang, "dev.json"), "w") as f:
        json.dump(dev_dataset, f, indent=4)
    with open(os.path.join(ROOT_PATH, "new_dataset", lang, "test.json"), "w") as f:
        json.dump(test_dataset, f, indent=4)