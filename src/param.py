import random, os, numpy as np, platform
import torch

random.seed(0)
torch.manual_seed(0)
torch.cuda.manual_seed_all(0)
np.random.seed(0)
extension = '.exe' if platform.system() == 'Windows' else ""
os.environ['CUDA_VISIBLE_DEVICES'] = '-1'

settings = {
    'cmd': ['search'],# steps of pipeline, ['finetune', 'predict', 'search', 'eval','aggregate','create_ds']
    't5model': 'base.gc',#'base.gc',# 'small.local'
    'ranker': 'bm25',#'qld'
    'metric': 'map',# 'map'
    'treclib': f'"./trec_eval.9.0.4/trec_eval{extension}"',#in non-windows, remove .exe, also for pytrec_eval, 'pytrec'
    'msmarco.passage': {
        'index': '../data/raw/msmarco.passage/lucene-index.msmarco-v1-passage.20220131.9ea315/',
        'pairing': [None, 'docs', 'query']# [context={msmarco does not have userinfo}, input={query, doc, doc(s)}, output={query, doc, doc(s)}], s means concat of docs
    },
    'aol': {
        'index_item': ['title'], # acceptable values ['title', 'url'], ['url'], ['title', 'url', 'text']
        'index': '../data/raw/aol/indexes/',
        'pairing': [None, 'docs', 'query'], #[context={2 scenarios, one with userID and one without userID). input={'userid','query','doc(s)'} output={'query','doc(s)'}
        'filter': [0, 10] #after merge queries and relevant 'index_item', if |query| <= 0 drop the row, if |'index_item'| < 10, drop row
    }
}