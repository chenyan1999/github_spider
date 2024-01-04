import os
import json
ROOT_PATH = "./"

def count(lang: str):
    global ROOT_PATH
    
    with open(os.path.join(ROOT_PATH, "new_dataset", f"{lang}_dataset.json"), "r") as f:
        dataset = json.load(f)
        
    # count project number
    projects = set()
    for commit_url in dataset.keys():
        proj_name = commit_url.split('/')[-3]
        if proj_name not in projects:
            projects.add(proj_name)
    print(f"#Projects: {len(projects)}")
    
    # count commit number
    print(f"#Commits: {len(dataset)}")
    
    # count hunk number (generator)
    hunk_num = 0
    for commit_url, data in dataset.items():
        hunk_num += len(data['hunks'])
    print(f"#Hunks: {hunk_num}")
    
    # count sliding window number (locator)
    sld_win_num = 0
    for commit_url, data in dataset.items():
        sld_win_num += len(data['sliding_windows'])
    print(f"#Sliding Windows: {sld_win_num}")
    
    