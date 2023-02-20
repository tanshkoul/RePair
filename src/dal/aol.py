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

            print('Creating jsonl collections for indexing ...')
            print(f'Raw documents should be downloaded already at {homedir}/aol-ia/downloaded_docs/ as explained here: https://github.com/terrierteam/aolia-tools')
            index_item_str = '.'.join(index_item)
            Aol.create_jsonl(aolia, index_item, f'{homedir}/aol-ia/{index_item_str}')
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
        print(f'Converting aol docs into jsonl collection for {index_item}')
        if not os.path.isdir(output): os.makedirs(output)
        output_jsonl_file = open(f'{output}/docs.json', 'w', encoding='utf-8', newline='\n')
        for i, doc in enumerate(aolia.docs_iter()):  # doc returns doc_id, title, text, url, ia_url
            did = doc.doc_id
            doc = {'title': doc.title, 'url': doc.url, 'text': doc.text}
            doc = ' '.join([doc[item] for item in index_item])
            output_jsonl_file.write(json.dumps({'id': did, 'contents': doc}) + '\n')
            if i % 100000 == 0: print(f'Converted {i:,} docs, writing into file {output_jsonl_file.name} ...')
        output_jsonl_file.close()

    @staticmethod
    def to_txt(did):
        # no need to tell what type of content, the index already know that based on the index_item
        if not Dataset.searcher.doc(did): return None # it happens because the did may not have text. to drop these queries
        else: return json.loads(Dataset.searcher.doc(str(did)).raw())['contents'].lower()
        
    @staticmethod
    def to_pair(input, output, index_item, cat=True):
        queries = pd.read_csv(f'{input}/queries.tsv', sep='\t', index_col=False, names=['qid', 'query'], converters={'query': str.lower}, header=None)
        # the column order in the file is [qid, uid, did, uid]!!!! STUPID!!
        qrels = pd.read_csv(f'{input}/qrels', encoding='UTF-8', sep='\t', index_col=False, names=['qid', 'uid', 'did', 'rel'], header=None)
        #not considering uid
        # docid is a hash of the URL. qid is the a hash of the *noramlised query* ==> two uid may have same qid then, same docid.
        queries_qrels = pd.merge(queries, qrels, on='qid', how='inner', copy=False)

        doccol = 'docs' if cat else 'doc'
        del queries, qrels
        queries_qrels['ctx'] = ''
        queries_qrels = queries_qrels.astype('category')
        queries_qrels[doccol] = queries_qrels['did'].progress_apply(Aol.to_txt)

        # no uid for now + some cleansings ...
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
                if pd.isna(row.query): return
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
    @staticmethod
    def aggregate(original, changes, splits, output, ranker, metric):
        def to_norm(tf_txt):
            return tf_txt.replace('\"', '')
        for change in changes:
            map_split = list()
            pred = pd.read_csv(join(output, change), sep='\r\r', skip_blank_lines=False, converters={change : to_norm}, names=[change], engine='python',
                               index_col=False, header=None, encoding='utf-8')
            assert len(original['qid']) == len(pred[change])
            for split in splits:
                print(f'appending {split} for {change} maps')
                map_split.append(pd.read_csv(join(output, f'{change}.{split}.{ranker}.{metric}'), sep='\t', usecols=[1, 2],
                                                 names=['qid', f'{change}.{ranker}.{metric}'], encoding='utf-8', engine='python', index_col=False,
                                                 skipfooter=1))
            pred_metric_values = pd.concat(map_split, ignore_index=True)
            original[change] = pred  # to know the actual change
            original = original.merge(pred_metric_values, how='left',
                                      on='qid')  # to know the metric value of the change
            original[f'{change}.{ranker}.{metric}'].fillna(0, inplace=True)
            original[f'{change}.{ranker}.{metric}'] = original[f'{change}.{ranker}.{metric}'].astype(float)

        print(f'Saving original queries, all their changes, and their {metric} values based on {ranker} ...')
        original.to_csv(f'{output}/{ranker}.{metric}.agg.all.tsv', sep='\t', encoding='UTF-8', index=False)
        print(f'Saving original queries, better changes, and {metric} values based on {ranker} ...')
        with open(f'{output}/{ranker}.{metric}.agg.best.tsv', mode='w', encoding='UTF-8') as agg_best:
            agg_best.write(f'qid\torder\tquery\t{ranker}.{metric}\n')
            for index, row in tqdm(original.iterrows(), total=original.shape[0]):
                agg_best.write(f'{row.qid}\t-1\t{row.query}\t{row["original." + ranker + "." + metric]}\n')
                best_results = list()
                for change in changes:
                    if row[f'{change}.{ranker}.{metric}'] > 0 and row[f'{change}.{ranker}.{metric}'] >= row[
                        f'original.{ranker}.{metric}']: best_results.append(
                        (row[change], row[f'{change}.{ranker}.{metric}'], change))
                best_results = sorted(best_results, key=lambda x: x[1], reverse=True)
                for i, (query, metric_value, change) in enumerate(best_results): agg_best.write(
                    f'{row.qid}\t{change}\t{query}\t{metric_value}\n')

    @staticmethod
    def box(input, qrels, output):

        checks = {'gold': 'True',
                  'platinum': 'golden_q_metric > original_q_metric',
                  'diamond': 'golden_q_metric > original_q_metric and golden_q_metric == 1'}
        ranker, metric = input.columns[-1].split('.')

        for c in checks.keys():
            print(f'Boxing {c} queries for {ranker}.{metric} ...')
            ds = {'qid': list(), 'query': list(), f'{ranker}.{metric}': list(), 'query_': list(),
                  f'{ranker}.{metric}_': list()}
            groups = input.groupby('qid')
            for _, group in tqdm(groups, total=len(groups)):
                if len(group) >= 2:
                    original_q, original_q_metric = group.iloc[0], group.iloc[0][f'{ranker}.{metric}']
                    golden_q, golden_q_metric = group.iloc[1], group.iloc[1][f'{ranker}.{metric}']
                    for i in range(1,
                                   2):  # len(group)): #IMPORTANT: We can have more than one golden query with SAME metric value. Here we skip them so the qid will NOT be replicated!
                        if (group.iloc[i][f'{ranker}.{metric}'] < golden_q[f'{ranker}.{metric}']): break
                        if not eval(checks[
                                        c]): break  # for gold this is always true since we put >= metric values in *.agg.best.tsv
                        ds['qid'].append(original_q['qid'])
                        ds['query'].append(original_q['query'])
                        ds[f'{ranker}.{metric}'].append(original_q_metric)
                        ds['query_'].append(group.iloc[i]['query'])
                        ds[f'{ranker}.{metric}_'].append(
                            golden_q_metric)  # TODO: we can add golden queries with same metric value as a list here

            df = pd.DataFrame.from_dict(ds)
            # df.drop_duplicates(subset=['qid'], inplace=True)
            del ds
            df.to_csv(f'{output}/{c}.tsv', sep='\t', encoding='utf-8', index=False, header=False)
            df.to_csv(f'{output}/{c}.original.tsv', sep='\t', encoding='utf-8', index=False, header=False,
                      columns=['qid', 'query'])
            df.to_csv(f'{output}/{c}.change.tsv', sep='\t', encoding='utf-8', index=False, header=False,
                      columns=['qid', 'query_'])
            print(f'{c}  has {df.shape[0]} queries')
            qrels = df.merge(qrels, on='qid', how='inner')
            qrels.to_csv(f'{output}/{c}.qrels.tsv', sep='\t', encoding='utf-8', index=False, header=False,
                         columns=['qid', 'did', 'pid', 'rel'])
            qrels.drop_duplicates(subset=['qid', 'pid'], inplace=True)
            qrels.to_csv(f'{output}/{c}.qrels.tsv_', sep='\t', encoding='utf-8', index=False, header=False,
                         columns=['qid', 'did', 'pid', 'rel'])