import sys
import pandas as pd
from os.path import exists
from common.add_col_name import add_colname
from dal.msmarco import msmarco

dataset_name = sys.argv[1:] #msmarco, aol,yandex
raw_data_location  = f'./Raw/{dataset_name[0]}/'
clean_data_location = f'./Data/{dataset_name[0]}/'
def add_headers(filename,colname,datasetname):

    if (exists(clean_data_location+filename)!=True):
        return add_colname(filename, colname, datasetname)
    else:
        print(f'..fetching queries from {clean_data_location + filename}')
        file_store =  pd.read_csv(clean_data_location + filename,sep='\t', chunksize = 10)
        print(next(file_store))

# convert this code to a loop later
add_headers('qrels.train.tsv',["qid","did","pid","relevancy"],dataset_name[0])
add_headers('queries.train.tsv',["qid","query"],dataset_name[0])

for data in dataset_name:
    if(data == 'msmarco'):
        if(exists('.'+clean_data_location+'/target/qrels.target.tsv')!= True & exists('.'+clean_data_location+'/target/qrels.target.tsv')!= True):
            msmarco('.'+clean_data_location + 'qrels.train.tsv','.'+clean_data_location + 'queries.train.tsv')
        else:
            qrels_file = pd.read_csv('.'+clean_data_location+'target/qrels.target.tsv',sep='\t',chunksize=10)
            queries_file = pd.read_csv('.'+clean_data_location+'target/queries.target.tsv',sep='\t',chunksize=10)
            print('file already exists. reading them now.')
            print(next(qrels_file))
            print(next(queries_file))
    elif(data == 'aol'):
        print('processing aol...')
    else:
        print('processing yandex...')