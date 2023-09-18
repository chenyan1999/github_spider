from get_changes import get_changes
from get_code import get_datasample

if __name__ == '__main__':
    lang = 'javascript' 
    num_of_repo = 1 # the number of repo to be crawled
    download_files_when_generate_datasamples = True
    only_download_changed_files = True
    get_changes(lang, num_of_repo)
    get_datasample(lang, download_files_when_generate_datasamples, only_download_changed_files)

