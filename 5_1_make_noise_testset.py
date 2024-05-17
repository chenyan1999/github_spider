# This script is used to create a noisy test dataset that have less strict filter rules compared with original test dataset. This is to bring more noise to the dataset. Use this noisy test dataset, we can compare the performance of prior edit selectors, to see if they can select helpful hunks from all noisy hunks
import os
import json
from tqdm import tqdm
from importlib import import_module

def make_noise_testset(lang: str):
    step_3 = import_module("3_clean_edit_info")
    # 1. fisrt load the original test dataset, extract all project names in test dataset
    with open(f"./new_dataset/{lang}/test.json", "r") as f:
        test_dataset = json.load(f)
    print("# of commits in test dataset: ", len(test_dataset))
    project_names = []
    for commit_url in test_dataset.keys():
        project_name = commit_url.split('/')[-3]
        if project_name not in project_names:
            project_names.append(project_name)
            
    # 2. if exist ./commit_info/{lang}_commit_info.jsonl, load it, and apply less strict filter
    with open(os.path.join(f"./commit_info/{lang}_filtered_commit_urls.json"), "r") as f:
        commit_urls = json.load(f)
    cnt = 0
    error_cnt = {}
    commit_snapshots = {}
    for commit_url in tqdm(commit_urls):
        try:
            result_dict = step_3.git_parse_diff(commit_url, strict=False)
            cnt += 1
            commit_snapshots[commit_url] = result_dict
        except Exception as e:
            label = str(e).split(' ')[0]
            if label not in ['1', '2', '3', '4', '5', '6', '7', '8', '9', '10', '11', '12']:
                print('other error: ', e)
                print(commit_url)
                break
            else:
                if label not in error_cnt:
                    error_cnt[label] = 1
                else:
                    error_cnt[label] += 1
            continue    
    
    with open(os.path.join('qualified_commit', f'{lang}_less_qualified_commit_snapshots.json'), 'w') as f:
        json.dump(commit_snapshots, f, indent=4)
    
    print(f'{lang} have {cnt} left, survive rate: {cnt/len(commit_urls)*100:.2f}%')
    print('Commit filtered out because:')
    error_dict = {
        "1": "Error in acquire git diff",
        "2": "Contain edit that changes file name",
        "3": "Contain edit on non-source files",
        "4": "Edit fail to match @@ -xx,xx +xx,xx @@",
        "5": "Edit/file contain non-ascii char",
        "6": "Commit contain > 15 hunks or < 3 hunks",
        "7": "Edit longer than 15 lines",
        "8": "Edit is trivial",
        "9": "File contain only edit",
        "10": "File contain add edit at first line",
        "11": "Contain edit on less than 2 files",
        "12": "Edit/file contain <mask> or <MASK>"
    }
    for error_idx, error_num in error_cnt.items():
        print(f'Rule {error_idx} {error_dict[error_idx]}: {error_num}')
        
    step_4 = import_module("4_make_dataset")
    with open(os.path.join('qualified_commit', f'{lang}_less_qualified_commit_snapshots.json'), 'r') as f:
        commit_snapshots = json.load(f)
    test_commit_snapshots = {}
    for commit_url, snapshot in commit_snapshots.items():
        project_name = commit_url.split('/')[-3]
        if project_name in project_names:
            test_commit_snapshots[commit_url] = snapshot
    print("# of commits in noise test dataset: ", len(test_commit_snapshots))
    dataset = step_4.make_single_dataset(lang, test_commit_snapshots)
    
    with open(os.path.join("./new_dataset", lang, "noise_test.json"), "w") as f:
        json.dump(dataset, f, indent=4)
        
if __name__ == '__main__':
    lang = 'java'
    make_noise_testset(lang)