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

# window = "@@ -1 +1,4 @@"
# print(re.findall(r"@@ \-(.+?)[,|\s]", window)[0])
# window = "@@ -1,3 +1,4 @@"
# print(re.findall(r"@@ \-(.+?)[,|\s]", window)[0])

di = {'name': 8}
l = [di for i in range(5)]
with jsonlines.open("test.jsonl", 'a') as writer:
    writer.write_all(l)

with jsonlines.open(f"test.jsonl") as reader:
    repos = list(reader)

print(repos)

