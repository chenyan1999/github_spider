# this script is used to combine all languages into 1 dataset
import os
import json

def combine(lang_list, dataset_path):
    for name in ["train", "dev", "test"]:
        combined_dataset = {}
        for lang in lang_list:
            with open(f"{dataset_path}/{lang}/{name}.json", "r") as f:
                dataset = json.load(f)
            # for each value in dataset, add a new key: lang
            for commit_url, commit in dataset.items():
                commit["lang"] = lang
                combined_dataset[commit_url] = commit
        
        with open(f"{dataset_path}/all/{name}.json", "w") as f:
            json.dump(combined_dataset, f, indent=4)

if __name__ == '__main__':
    lang_list = ["python", "go", "java", "javascript", "typescript"]
    dataset_path = "/media/chenyan/dataset_fine_grain"
    if not os.path.exists(f"{dataset_path}/all"):
        os.mkdir(f"{dataset_path}/all")
    combine(lang_list, dataset_path)
    