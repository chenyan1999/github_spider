# This script is used to 1. filter commit based on edits made, filter rules may check comments start with Rule #num
import re
import os
import json
import subprocess
from tqdm import tqdm
ROOT_PATH = '/media/chenyan/CodeEdit_raw_dataset'

def detect_extension(file_names: list[str]):
    # 使用os.path.basename获取文件名
    for file_name in file_names:
        filename = os.path.basename(file_name)
        # 使用splitext分割文件名和后缀
        file_name_elements = filename.split('.')
        if len(file_name_elements) == 2:
            extension = '.'+file_name_elements[-1]
        else:
            extension =  '.'+'.'.join(file_name_elements[-2:])
        # white_list = ['.go', '.js', '.java', '.py', '.ts', '.tsx']
        auto_gen_file_type = ['.map', '.lock', '.build', '.sample', '.min.js', '.bundle.js', '.less'  # Javascript
            '.class', '.jar', '.war', '.ear', '.bak', '.log', '.tmp',  # Java
            '.tsbuildinfo',  # Typescript
            '.pyc', '.pyo', '.pyd', '.so', '.dll',  # Python
            '.a', '.o', '.test', '.cover', '.prof', '.exe', '.pb.go', '.gen.go', '.swagger.go', '.generated.go'# Go
            '.css', '.html', '.sh', '.pem']
        if extension in auto_gen_file_type:
            return True
    return False
    
def convert_diff_section_to_snapshot(file_w_diff: str):
    diff_content = file_w_diff.splitlines(keepends=True)
    snapshot = []
    consecutive_code = []
    under_edit = False
    edits = []
    for line in diff_content:
        if line.startswith(" ") and under_edit == False:
            consecutive_code.append(line[1:])
        elif line.startswith(" ") and under_edit == True:
            under_edit = False
            snapshot.append(edit.copy())
            # for window in snapshot:
            #     print(window)
            consecutive_code.append(line[1:]) 
        elif line.startswith("-") and under_edit == False:
            under_edit = True
            snapshot.append(consecutive_code.copy())
            # for window in snapshot:
            #     print(window)
            consecutive_code = []
            edit = {
                "type": "replace",
                "before": [],
                "after": []
            }
            edit["before"].append(line[1:])
        elif line.startswith("+") and under_edit == False:
            under_edit = True
            snapshot.append(consecutive_code.copy())
            # for window in snapshot:
            #     print(window)
            consecutive_code = []
            edit = {
                "type": "add",
                "before": [],
                "after": []
            }
            edit["after"].append(line[1:])
        elif line.startswith("+") and under_edit == True:
            edit["after"].append(line[1:])
        elif line.startswith("-") and under_edit == True:
            edit["before"].append(line[1:])
    if under_edit == True:
        snapshot.append(edit.copy())
    if under_edit == False:
        snapshot.append(consecutive_code.copy())
    
    for window in snapshot:
        if type(window) == dict:
            edits.append(window)
    return snapshot, edits
   
def git_parse_diff(commit_url: str):
    global ROOT_PATH
    proj_name = commit_url.split('/')[-3]
    repo_path = os.path.join(ROOT_PATH, 'repos',proj_name)
    sha = commit_url.split('/')[-1]
    
    result_dict = {}
    # 1. get git diff 
    command = f'git -C {repo_path} diff -U1000 {sha}^ {sha}'
    try:
        result = subprocess.run(command, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    except:
        raise ValueError(f'1 {commit_url} Error: Error in git diff')
    git_diff_str = result.stdout
    if git_diff_str.strip() == '':
        raise ValueError(f'1 {commit_url} Error: Error in git diff')
    
    # 2. parse all file names (w/ path), check if they have undesired extension
    file_name_matches = re.finditer(r'diff --git a/(.+) b/(.+)', git_diff_str)
    file_names = []
    for match in file_name_matches:
        before_filename = match.group(1)
        after_filename = match.group(2)
        try:
            assert before_filename == after_filename
            file_name = before_filename
        except:
            raise ValueError(f"2 {commit_url} Error: Contain edit changes file name: {before_filename} -> {after_filename}")
        file_names.append(before_filename)
    
    # Rule 1: do not contain auto-generated files
    if detect_extension(list(set(file_names))):
        raise ValueError(f'3 {commit_url} Error: Contain edit on non-source files')
        
    # 3. split into diff section, 1 section = 1 file
    diff_sections = re.findall(r'diff --git[^\n]*\n.*?(?=\ndiff --git|$)', git_diff_str, re.DOTALL)
    all_edit_num = 0
    for section in diff_sections:
        # 2.1 parse file name (w/ path), make sure edit don't change file name
        file_name_match = re.match(r'diff --git a/(.+) b/(.+)', section)
        if file_name_match:
            file_name = file_name_match.group(1)
        else:
            raise ValueError(f"5 {commit_url} Error: file name contain non-ascii char")
        
        
        # 2.2 get the diff of the whole file
        # (if -U{number} is set large enough, a file should contain only 1 @@ -xx,xx +xx,xx @@)
        # we can only make snapshot based on the diff of the whole file
        match = re.search(r'@@[^\n]*\n(.+)', section, re.DOTALL)
        if not match:
            raise ValueError(f"4 {commit_url} Error: Edit fail to match @@ -xx,xx +xx,xx @@")
        # 匹配@@行之后的内容
        after_at_symbol_content = match.group(1)
        # Rule 2: do not contain non-ascii chars
        if not after_at_symbol_content.isascii():
            raise ValueError(f"5 {commit_url} Error: Edit/file contain non-ascii char")
        # form snapshot: each element:
        # type 1: list of line of code, unchanged
        # type 2: dict of edit, have key: "type", "before", "after"
        snapshot, edits = convert_diff_section_to_snapshot(after_at_symbol_content)
        all_edit_num += len(edits)
        # Rule 5: contain > 3 hunk and < 10 hunk
        if all_edit_num > 10: # early stop
            raise ValueError(f'6 {commit_url} Error: Commit contain more than 10 hunk, hunk num >= {all_edit_num}')
        for edit in edits:
            # Rule 3: edit less than 15 lines
            if len(edit['before']) > 15 or len(edit['after']) > 15:
                raise ValueError(f'7 {commit_url} Error: Edit longer than 15 lines, before: {len(edit["before"])} lines, after: {len(edit["after"])} lines')
            # Rule 4: edit can not be trivial
            if edit['type'] == 'replace' and \
             "".join(edit['before']).strip('\n') == "".join(edit['after']).strip('\n'):
                raise ValueError(f'8 {commit_url} Error: Edit is trivial: {edit["before"]} -> {edit["after"]}')
            if edit['type'] == 'add' and "".join(edit['after']).strip() == '':
                raise ValueError(f'8 {commit_url} Error: Edit is trivial: {edit["before"]} -> {edit["after"]}')
        result_dict[file_name] = snapshot
    # Rule 5: contain > 3 hunk and < 10 hunk
    if all_edit_num < 3:
        raise ValueError(f'6 {commit_url} Error: Commit contain less than 3 hunk, hunk num: {all_edit_num}')
    return result_dict

def clean_edit(lang):
    with open(os.path.join(ROOT_PATH, f'commit_info/{lang}_filtered_commit_urls.json'), 'r') as f:
        commit_urls = json.load(f)
    cnt = 0
    error_cnt = {}
    commit_snapshots = {}
    for commit_url in tqdm(commit_urls):
        try:
            result_dict = git_parse_diff(commit_url)
            cnt += 1
            commit_snapshots[commit_url] = result_dict
        except Exception as e:
            label = str(e).split(' ')[0]
            if label not in ['1', '2', '3', '4', '5', '6', '7', '8']:
                print('other error: ', e)
                print(commit_url)
                break
            else:
                if label not in error_cnt:
                    error_cnt[label] = 1
                else:
                    error_cnt[label] += 1
            continue
    
    if not os.path.exists(os.path.join(ROOT_PATH, 'qualified_commit')):
        os.mkdir(os.path.join(ROOT_PATH, 'qualified_commit'))
    with open(os.path.join(ROOT_PATH, 'qualified_commit', f'{lang}_qualified_commit_snapshots.json'), 'w') as f:
        json.dump(commit_snapshots, f, indent=4)
    
    print(f'{lang} have {cnt} left, survive rate: {cnt/len(commit_urls)*100:.2f}%')
    print('Commit filtered out because:')
    error_dict = {
        "1": "Error in acquire git diff",
        "2": "Contain edit that changes file name",
        "3": "Contain edit on non-source files",
        "4": "Edit fail to match @@ -xx,xx +xx,xx @@",
        "5": "Edit/file contain non-ascii char",
        "6": "Commit contain > 10 hunks or < 3 hunks",
        "7": "Edit longer than 15 lines",
        "8": "Edit is trivial"
    }
    for error_idx, error_num in error_cnt.items():
        print(f'Rule {error_dict[error_idx]}: {error_num}')

if __name__ == '__main__':
    lang = 'python'
    clean_edit(lang)