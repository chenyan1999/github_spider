import time
from get_changes import get_changes
from get_code import get_datasample

if __name__ == '__main__':
    start = time.time()
    lang = 'javascript' # java, python, typescript, go
    num_of_repo = 100 # the number of repo to be crawled
    get_changes(lang, num_of_repo)
    get_datasample(lang)
    end = time.time()
    print(f'==> Time elapsed: {end - start} seconds')
