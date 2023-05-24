import gc
import json
import random
import re
import urllib.request
import zipfile
import codecs
import requests
import os
import time
import shutil
import jsonlines

from gevent.pool import Pool
from gevent import monkey

from proxies_pool import proxy_list
from user_agent_pool import user_agents

from get_changes import get_response

def git_clone_whole(user_name, proj_name, sha):
    if os.path.exists(f'./repos/{user_name}_{proj_name}_{sha}/.whole_repo'):
        return # if this repo has been downloaded fully in the past
    url = f'https://api.github.com/repos/{user_name}/{proj_name}/zipball/{sha}'
    zipfile_name = os.path.join('./repos', f'{user_name}_{proj_name}_{sha}.zip')
    try:
        data = urllib.request.urlopen(url, timeout=40)
        with open(zipfile_name, 'wb') as f:
            f.write(data.read())
    except Exception as e:
        print("==> Downloading %s failed" % zipfile_name)
        print(e)
        return

    print("==> Extracting %s" % zipfile_name)
    with zipfile.ZipFile(zipfile_name, 'r') as f:
        f.extractall('./repos')
    # github's zip file name only presive 7 digits of sha
    os.rename(f'./repos/{user_name}-{proj_name}-{sha[:7]}',f'./repos/{user_name}_{proj_name}_{sha}')
    os.remove(zipfile_name)
    open(f'./repos/{user_name}_{proj_name}_{sha}/.whole_repo',"w+").close() # make a mark if the whole repo has been downloaded

def git_clone_file(user_name, proj_name, sha, file_path):
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
        if file_name.startswith('.'):  # ignore any hidden file
            continue
        user_name, proj_name, sha, old_sha = file_name.split('.')[0].split('_')
        
        print(f'==> Converting {user_name}/{proj_name}\'s commit {sha} into data samples')
        # download the entire repo if required
        if download_files_when_generate_datasamples and only_download_changed_files == False:
            git_clone_whole(user_name, proj_name, sha)
            git_clone_whole(user_name, proj_name, old_sha)
        
        # open jsonl file and convert to list
        with jsonlines.open(f'./changes/{lang}/{file_name}') as reader:
            changes = list(reader)

        # aggregate changes that happens on the same file
        file_changes = {}
        for change in changes:
            if change['file_path'] not in file_changes:
                file_changes[change['file_path']] = []
            file_changes[change['file_path']].append(change)

        # write a data sample for each file
        for file in file_changes:
            try:
                if download_files_when_generate_datasamples and only_download_changed_files == True:
                    git_clone_file(user_name, proj_name, sha, file)
                    git_clone_file(user_name, proj_name, old_sha, file)
                dic = {
                    'old_file_path': f'./repos/{user_name}_{proj_name}_{old_sha}/' + file,
                    'new_file_path': f'./repos/{user_name}_{proj_name}_{sha}/' + file,
                    'changes': file_changes[file]
                }
                samples.append(dic)
            except:
                continue

        with jsonlines.open(f"./dataset/{lang}_dataset.jsonl", 'a') as writer:
            writer.write_all(samples)
        # delete the changes file when done
        os.remove(f'./changes/{lang}/{file_name}')