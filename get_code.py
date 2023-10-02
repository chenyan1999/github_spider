import os
import sys
import json
import zipfile
import jsonlines
import subprocess
import urllib.request

from proxies_pool import proxy_list
from user_agent_pool import user_agents

from get_changes import get_response

def git_clone(user_name, proj_name):
    # Check if this repo has been downloaded
    global ROOT_PATH
    global GITHUB_TOKENS, CURR_TOKEN_IDX
    if os.path.exists(ROOT_PATH+f'/repos/{proj_name}/'):
        return
    # if not, download the whole repo of the latest version
    curr_dir = os.getcwd()
    try:
        os.chdir(os.path.normpath(ROOT_PATH+'/repos'))
        clone_url = f"https://{GITHUB_TOKENS[CURR_TOKEN_IDX]}@github.com/{user_name}/{proj_name}.git"
        
        git_clone_command = ["git", "clone", clone_url]
        # Run the Git clone command
        subprocess.run(git_clone_command, check=True)
    except:
        os.chdir(curr_dir)
        raise Exception(f"==> Downloading {user_name}/{proj_name} failed")
    
    os.chdir(curr_dir)
    
def get_datasample(lang):
    global ROOT_PATH
    if not os.path.exists(ROOT_PATH+'/dataset'):
        os.mkdir(ROOT_PATH+'/dataset')
    for file_name in os.listdir(ROOT_PATH+f"/changes/{lang}"):   # for every change recorded in jsonl
        samples = []
        if file_name.startswith('.') or file_name[-6:] != '.jsonl':  # ignore any hidden file or files not jsonl
            continue
        l = file_name[:-6].split('_')
        if len(l) < 4: # if this file don't have the correct format, ignore it
            continue
        else:
            user_name = l[0]
            sha = l[-2]
            old_sha = l[-1]
            proj_name = '_'.join(l[1:-2]) # in case that the project name contain _
        
        # 从已经下载的 commit history jsonl 中找到对应的 commit message 和 html_url
        with jsonlines.open(ROOT_PATH+f"/commit_history/{user_name}_{proj_name}.jsonl") as reader:
            commits = list(reader)
        for commit in commits:
            if commit["sha"] == sha:
                html_url = commit["html_url"]
                try:
                    commit_msg = commit["commit"]["message"]
                except:
                    print(f"Failed to find commit message from {user_name}\'s {proj_name} of commit {sha}")
                    commit_msg = ""
                break # quit loop once find

        # 从 GitHub 获取 pull message (无法从 git log 中获取)
        try:
            url = f'https://api.github.com/repos/{user_name}/{proj_name}/commits/{sha}/pulls'
            content = get_response(url)
            pull_info = json.loads(content)
            if len(pull_info) != 1:
                pull_msg = ""
            else:
                pull_info = pull_info[0]
                pull_msg = pull_info["body"]
        except:
            # Normal if a commit do not have pull msg, do not raise error
            print(f"==> {user_name}\'s {proj_name} of commit {sha} do not find pull msg")
            pull_msg = ""

        print(f'==> Converting {user_name}/{proj_name}\'s commit {sha} into data samples')     
        # open jsonl file and convert to list
        with jsonlines.open(ROOT_PATH+f'/changes/{lang}/{file_name}') as reader:
            changes = list(reader)

        # aggregate changes that happens on the same file
        file_changes = {}
        for change in changes:
            file_path = change['file_path']
            if file_path not in file_changes:
                file_changes[file_path] = []
            change.pop('file_path')
            file_changes[file_path].append(change)

        # write a data sample for each file
        for file in file_changes:
            dic = {
                'user_name': user_name,
                'proj_name': proj_name,
                'old_sha': old_sha,
                'new_sha': sha,
                'file_path': file,
                'changes': file_changes[file],
                'commit_msg': commit_msg,
                'pull_msg': pull_msg,
                'html_url': html_url
            }
            samples.append(dic)      

        with jsonlines.open(ROOT_PATH+f"/dataset/{lang}_dataset.jsonl", 'a') as writer:
            writer.write_all(samples)
        # delete the changes file when done
        os.remove(ROOT_PATH+f'/changes/{lang}/{file_name}')

    # download repos
    with jsonlines.open(ROOT_PATH+f"/repo_info/{lang}_top_star_repos.jsonl") as reader:
        print(f"==> {lang}_top_star_repos.jsonl exists, read from local")
        repos = list(reader)
    for repo in repos:
        user_name = repo['user_name']['full_name'].split('/')[0]
        proj_name = repo['name']
        git_clone(user_name, proj_name)