import os
import sys
import json
import zipfile
import jsonlines
import urllib.request

from proxies_pool import proxy_list
from user_agent_pool import user_agents

from get_changes import get_response

def git_clone_whole(user_name, proj_name, sha):
    '''
    Download the whole repo
    '''
    if os.path.exists(f'./repos/{user_name}_{proj_name}_{sha}/.whole_repo'):
        return # if this repo has been downloaded fully in the past
    url = f'https://api.github.com/repos/{user_name}/{proj_name}/zipball/{sha}'
    zipfile_name = os.path.join('./repos', f'{user_name}_{proj_name}_{sha}.zip')
    try:
        data = urllib.request.urlopen(url, timeout=40)
        with open(zipfile_name, 'wb') as f:
            f.write(data.read())
    except:
        raise Exception(f"==> Downloading {zipfile_name} failed")

    print("==> Extracting %s" % zipfile_name)
    with zipfile.ZipFile(zipfile_name, 'r') as f:
        f.extractall('./repos')
    # github's zip file name only presive 7 digits of sha
    os.rename(f'./repos/{user_name}-{proj_name}-{sha[:7]}',f'./repos/{user_name}_{proj_name}_{sha}')
    os.remove(zipfile_name)
    open(f'./repos/{user_name}_{proj_name}_{sha}/.whole_repo',"w+").close() # make a mark if the whole repo has been downloaded

def git_clone_file(user_name, proj_name, sha, file_path):
    '''
    Only download the specified file
    '''
    if os.path.exists(f'./repos/{user_name}_{proj_name}_{sha}/{file_path}'):
        return
    url = f'https://raw.githubusercontent.com/{user_name}/{proj_name}/{sha}/{file_path}'
    d = get_response(url, return_text=True) # get the file
    # save it to the path
    file_path_wo_name = '/'.join(file_path.split('/')[:-1])
    if not os.path.exists(f'./repos/{user_name}_{proj_name}_{sha}/{file_path_wo_name}'):
        os.makedirs(f'./repos/{user_name}_{proj_name}_{sha}/{file_path_wo_name}', exist_ok=True)
    with open(f'./repos/{user_name}_{proj_name}_{sha}/{file_path}', 'w', encoding="utf-8") as f:
        f.write(d)

def get_datasample(lang, download_files_when_generate_datasamples=False, only_download_changed_files=False):
    if not os.path.exists('./dataset'):
        os.mkdir('./dataset')
    for file_name in os.listdir(f"./changes/{lang}"):   # for every change recorded in jsonl
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
        
        # get commit message and html url
        with jsonlines.open(f"./commit_history/{user_name}_{proj_name}.jsonl") as reader:
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

        # get pull message
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
        # download the entire repo if required
        try: # if failed to download the whole repo, skip conversion
            if download_files_when_generate_datasamples and only_download_changed_files == False:
                git_clone_whole(user_name, proj_name, sha)
                git_clone_whole(user_name, proj_name, old_sha)
        except:
            print('==> Failed to clone the whole repo of specific commit')
            os.remove(f'./changes/{lang}/{file_name}') 
            continue
        
        # open jsonl file and convert to list
        with jsonlines.open(f'./changes/{lang}/{file_name}') as reader:
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
            try:
                if download_files_when_generate_datasamples and only_download_changed_files == True:
                    git_clone_file(user_name, proj_name, sha, file)
                    git_clone_file(user_name, proj_name, old_sha, file)
                dic = {
                    'old_file_path': f'./repos/{user_name}_{proj_name}_{old_sha}/' + file,
                    'new_file_path': f'./repos/{user_name}_{proj_name}_{sha}/' + file,
                    'changes': file_changes[file],
                    'commit_msg': commit_msg,
                    'pull_msg': pull_msg,
                    'html_url': html_url
                }
                samples.append(dic)
            except Exception as e:
                raise Exception(e)
            except:
                print(f'==> Failed to convert {user_name}/{proj_name}\'s commit {sha} into data samples')
                continue

        with jsonlines.open(f"./dataset/{lang}_dataset.jsonl", 'a') as writer:
            writer.write_all(samples)
        # delete the changes file when done
        os.remove(f'./changes/{lang}/{file_name}')