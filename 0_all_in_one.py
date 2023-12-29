from importlib import import_module

if __name__ == '__main__':
    lang = 'python' 
    num_of_repo = 1 

    # Step 1: get repos, commits and clone to local
    step_1 = import_module("1_crawl")
    step_1.crawl(lang, num_of_repo)
    
    # Step 2: filter commit based on commit information
    step_2 = import_module("2_clean_commit_info")
    step_2.clean_commit(lang)
    
    # Step 3: filter commit based on edit information
    step_3 = import_module("3_clean_edit_info")
    step_3.clean_edit(lang)
    
    # Step 4: make a dataset
    step_4 = import_module("4_make_dataset")
    step_4.make_dataset(lang)