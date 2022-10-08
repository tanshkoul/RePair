import csv
import json
import pandas as pd
from pyserini.search.lucene import LuceneSearcher
from src.common.fix_context_encoding import fix_context_encoding
from src.common.create_toy_dataset import create_toy_dataset

searcher = LuceneSearcher.from_prebuilt_index('msmarco-v1-passage')


def fetchDocument(doc_id, searcher):
    try:
        doc = searcher.doc(doc_id)
        json_doc = json.loads(doc.raw())
        return json_doc['contents']
    except:
        raise ValueError('the provided value is not found in the passage')


def msmarco(qrels_file, queries_file):
    target_passage_location = '../Data/msmarco/target/qrels.target.tsv'
    target_query_location = '../Data/msmarco/target/queries.target.tsv'
    queries_source = pd.read_csv(queries_file, sep="\t", index_col=False)
    with open(qrels_file) as qrels:
        qrels_source = csv.reader(qrels,delimiter='\t')
        next(qrels_source)
        with open(target_passage_location, 'w') as target_passage_file,open(target_query_location, 'w') as target_query_file:
            target_passage_file.write("pid\tpassage\n")
            target_query_file.write("qid\tquery\n")
            for line in qrels_source:
                fetch_qid = queries_source.loc[queries_source['qid'] == int(line[0])]
                retrieved_passage = fetchDocument((line[2]),searcher)
                target_query_file.write(f"{fetch_qid['qid'].squeeze()}\t{fetch_qid['query'].squeeze()}\n")
                target_passage_file.write(f'{line[2]}\t{retrieved_passage}\n')
        target_passage_file.close()
        target_query_file.close()
    qrels.close()
    print(f"fixing encoding issue for file present in {target_passage_location}\n\n\n")
    fix_context_encoding(target_passage_location)
    print(f"fix complete, overwritten the target passage with encoding fix..\n\n\n")
    print(f"creating toy dataset for ")
    create_toy_dataset(pd.read_csv(target_passage_location, sep="\t", index_col=False, chunksize=300))
    create_toy_dataset(pd.read_csv(target_query_location, sep="\t", index_col=False, chunksize=300))

    return "finished creating target files and toy dataset with fixes to encoding"
