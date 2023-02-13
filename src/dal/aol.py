import json, os, pandas as pd, shutil
from os.path import isfile, join
from tqdm import tqdm
tqdm.pandas()

from pyserini.search.lucene import LuceneSearcher

import param
from dal.ds import Dataset

class Aol(Dataset):

    @staticmethod
    def init(homedir, index_item, indexdir, ncore):
        try:
            Dataset.searcher = LuceneSearcher(f"{param.settings['aol']['index']}/{'.'.join(param.settings['aol']['index_item'])}")
        except:
            print(f"No index found at {param.settings['aol']['index']}! Creating index from scratch using ir-dataset ...")
            #https://github.com/allenai/ir_datasets
            os.environ['IR_DATASETS_HOME'] = homedir
            if not os.path.isdir(os.environ['IR_DATASETS_HOME']): os.makedirs(os.environ['IR_DATASETS_HOME'])
            import ir_datasets
            from cmn.lucenex import lucenex

            print('Setting up aol corpos using ir-datasets ...')
            aolia = ir_datasets.load("aol-ia")
            print('Getting queries and qrels ...')
            # the column order in the file is [qid, uid, did, uid]!!!! STUPID!!
            qrels = pd.DataFrame.from_records(aolia.qrels_iter(), columns=['qid', 'did', 'rel', 'uid'], nrows=1)  # namedtuple<query_id, doc_id, relevance, iteration>
            queries = pd.DataFrame.from_records(aolia.queries_iter(), columns=['qid', 'query'], nrows=1)# namedtuple<query_id, text>

            # print('Cleansing queries ...')
            # queries.dropna(inplace=True)
            # queries.drop_duplicates(inplace=True)
            # queries.drop(queries[queries['text'].str.strip().str.len() <= param.settings['aol']['filter']['minql']].index, inplace=True)
            # queries.to_csv(f'{homedir}/aol-ia/queries.tsv_', sep='\t', encoding='UTF-8', index=False, header=False)
            print('Creating jsonl collections for indexing ...')
            print(f'Raw documents should be downloaded already at {homedir}/aol-ia/downloaded_docs/ as explained here: https://github.com/terrierteam/aolia-tools')
            index_item_str = '.'.join(index_item)
            empdocs = Aol.create_jsonl(aolia, index_item, f'{homedir}/aol-ia/{index_item_str}')
            # qrels.drop(qrels[qrels.did.isin(empdocs)].index, inplace=True)  # remove qrels whose docs are empty
            # this makes different qrels as some may have url but no title ...
            # qrels.to_csv(f'{homedir}/aol-ia/qrels.{index_item_str}.tsv_', sep='\t', encoding='UTF-8', index=False, header=False)
            lucenex(f'{homedir}/aol-ia/{index_item_str}/', f'{indexdir}/{index_item_str}/', ncore)
            # do NOT rename qrel to qrel.tsv or anything else as aol-ia hardcoded it
            # if os.path.isfile('./../data/raw/aol-ia/qrels'): os.rename('./../data/raw/aol-ia/qrels', '../data/raw/aol-ia/qrels')
            Dataset.searcher = LuceneSearcher(f"{param.settings['aol']['index']}/{'.'.join(param.settings['aol']['index_item'])}")
            if not Dataset.searcher: raise ValueError(f"Lucene searcher cannot find aol index at {param.settings['aol']['index']}/{'.'.join(param.settings['aol']['index_item'])}!")

    @staticmethod
    def create_jsonl(aolia, index_item, output):
        """
        https://github.com/castorini/anserini-tools/blob/7b84f773225b5973b4533dfa0aa18653409a6146/scripts/msmarco/convert_collection_to_jsonl.py
        :param index_item: defaults to title_and_text, use the params to create specified index
        :param output: folder name to create docs
        :return: list of docids that have empty body based on the index_item
        """
        empty_did = set()
        print(f'Converting aol docs into jsonl collection for {index_item}')
        if not os.path.isdir(output): os.makedirs(output)
        output_jsonl_file = open(f'{output}/docs.json', 'w', encoding='utf-8', newline='\n')
        for i, doc in enumerate(aolia.docs_iter()):  # doc returns doc_id, title, text, url, ia_url
            did = doc.doc_id
            doc = {'title': doc.title, 'url': doc.url, 'text': doc.text}
            doc = ' '.join([doc[item] for item in index_item])
            # if len(doc) < param.settings["aol"]["filter"]['mindocl']:
            #     empty_did.add(did)
            #     continue
            output_jsonl_file.write(json.dumps({'id': did, 'contents': doc}) + '\n')
            if i % 100000 == 0: print(f'Converted {i:,} docs, writing into file {output_jsonl_file.name} ...')
        output_jsonl_file.close()
        return empty_did

    @staticmethod
    def to_txt(did):
        # no need to tell what type of content, the index already know that based on the index_item
        try:
            if not Dataset.searcher.doc(did): return None # it happens because the did may not have text. to drop these queries
            else: return json.loads(Dataset.searcher.doc(str(did)).raw())['contents'].lower()
        except Exception as e: raise e

    @staticmethod
    def to_pair(input, output, index_item, cat=True):
        queries = pd.read_csv(f'{input}/queries.tsv', sep='\t', index_col=False, names=['qid', 'query'], converters={'query': str.lower}, header=None)
        # the column order in the file is [qid, uid, did, uid]!!!! STUPID!!
        qrels = pd.read_csv(f'{input}/qrels', encoding='UTF-8', sep='\t', index_col=False, names=['qid', 'uid', 'did', 'rel'], header=None)
        #not considering uid
        # did is a hash of the URL. qid is the a hash of the *noramlised query* ==> two uid may have same qid then.
        queries_qrels = pd.merge(queries, qrels, on='qid', how='inner', copy=False)

        doccol = 'docs' if cat else 'doc'
        del queries, qrels
        queries_qrels['ctx'] = ''
        queries_qrels = queries_qrels.astype('category')
        queries_qrels[doccol] = queries_qrels['did'].progress_apply(Aol.to_txt)

        # no uid for now
        queries_qrels.drop_duplicates(subset=['qid', 'did'], inplace=True)  # two users with same click for same query
        queries_qrels['uid'] = -1
        queries_qrels.dropna(inplace=True) #empty doctxt, query, ...
        queries_qrels.drop(queries_qrels[queries_qrels['query'].str.strip().str.len() <= param.settings['aol']['filter']['minql']].index,inplace=True)
        queries_qrels.drop(queries_qrels[queries_qrels[doccol].str.strip().str.len() < param.settings["aol"]["filter"]['mindocl']].index,inplace=True)  # remove qrels whose docs are less than mindocl
        queries_qrels.to_csv(f'{input}/qrels.tsv_', index=False, sep='\t', header=False, columns=['qid', 'uid', 'did', 'rel'])

        if cat: queries_qrels = queries_qrels.groupby(['qid', 'query'], as_index=False, observed=True).agg({'uid': list, 'did': list, doccol: ' '.join})
        queries_qrels.to_csv(output, sep='\t', encoding='utf-8', index=False)
        return queries_qrels

    @staticmethod
    def to_search(in_query, out_docids, qids,index_item, ranker='bm25', topk=100, batch=None):
        print(f'Searching docs for {in_query} ...')
        # https://github.com/google-research/text-to-text-transfer-transformer/issues/322
        # with open(in_query, 'r', encoding='utf-8') as f: [to_docids(l) for l in f]
        queries = pd.read_csv(in_query, names=['query'], sep='\r', skip_blank_lines=False, engine='c')  #there might be empty predictions by t5
        Aol.to_search_df(queries, out_docids, qids, index_item, ranker=ranker, topk=topk, batch=batch)

    @staticmethod
    def to_search_df(queries, out_docids, qids, index_item,ranker='bm25', topk=100, batch=None):
        if ranker == 'bm25': Dataset.searcher.set_bm25(0.82, 0.68)
        if ranker == 'qld': Dataset.searcher.set_qld()
        assert len(queries) == len(qids)
        if batch:
            raise ValueError('Trec_eval does not accept more than 2GB files! So, we need to break it into several files. No batch search then!')
            # with open(out_docids, 'w', encoding='utf-8') as o:
            #     for b in tqdm(range(0, len(queries), batch)):
            #         hits = searcher.batch_search(queries.iloc[b: b + batch]['query'].values.tolist(), qids[b: b + batch], k=topk, threads=4)
            #         for qid in hits.keys():
            #             for i, h in enumerate(hits[qid]):
            #                 o.write(f'{qid}\tQ0\t{h.docid:15}\t{i + 1:2}\t{h.score:.5f}\tPyserini Batch\n')
        else:
            def to_docids(row, o):
                if not row.query: return
                hits = Dataset.searcher.search(row.query, k=topk, remove_dups=True)
                for i, h in enumerate(hits): o.write(f'{qids[row.name]}\tQ0\t{h.docid}\t{i + 1:2}\t{h.score:.5f}\tPyserini\n')

            #queries.progress_apply(to_docids, axis=1)
            max_docs_per_file = 400000
            file_index = 0
            for i, doc in tqdm(queries.iterrows(), total=len(queries)):
                if i % max_docs_per_file == 0:
                    if i > 0: out_file.close()
                    output_path = join(f'{out_docids.replace(ranker,"split_"+str(file_index)+"."+ranker)}')
                    out_file = open(output_path, 'w', encoding='utf-8', newline='\n')
                    file_index += 1
                to_docids(doc, out_file)
                if i % 100000 == 0: print(f'wrote {i} files to {out_docids.replace(ranker,"split_"+ str(file_index - 1) + "." + ranker)}')
