import json
import numpy as np
import pytest
from fastapi.testclient import TestClient
from local_rag.app import create_app
from local_rag.settings import Settings


@pytest.fixture
def app(tmp_path):
    return create_app(Settings(database_path=tmp_path/'empty.sqlite3',frontend_dist=tmp_path/'dist'))


def seed(store):
    """Temporary test-only records; never loaded by the app or shipped as data."""
    with store.connection() as db:
        db.execute("INSERT INTO sources VALUES('s','Test source','temporary','hash','ready')")
        db.executemany("INSERT INTO nodes(id,source_id,parent_id,title,kind,description,path_json) VALUES(?,?,?,?,?,?,?)",[
            ('root','s',None,'Test root','collection','Root description','["Root"]'),
            ('inside','s','root','Test section','section','Section description','["Root","Section"]'),
            ('outside','s',None,'Other section','section','Other description','["Other"]'),
        ])
        db.execute("INSERT INTO groups VALUES('g','Test group')")
        for i in range(100):
            db.execute("INSERT INTO chunks(id,node_id,title,text,path_json,input_hash) VALUES(?,?,?,?,?,?)",(f'a{i:03}','outside','Match','keyword evidence','["Other"]','hash'))
        db.execute("INSERT INTO chunks(id,node_id,group_id,title,text,path_json,locator,input_hash) VALUES('z','inside','g','Match','keyword evidence','[\"Root\",\"Section\"]','temporary row','hash')")
        db.execute("INSERT INTO embeddings VALUES('z','minishlab/potion-base-2M','potion-base-2M:cosine:v1',2,'hash',?)",(np.array([1,0],dtype='<f4').tobytes(),))
        db.execute("INSERT INTO map_points VALUES('point','z',0.2,0.4,'test-projection','potion-base-2M:cosine:v1')")


def test_empty_app_and_no_fabricated_data(app):
    with TestClient(app) as client:
        assert client.get('/api/config').json()['total_chunks']==0
        assert client.get('/api/nodes').json()['nodes']==[]
        assert client.get('/api/map').json()['points']==[]
        assert client.get('/api/issues').json()['issues']==[]
        answer=client.post('/api/chat',json={'query':'Unsupported question'}).json()
        assert answer['insufficient_evidence'] is True and answer['citations']==[]


def test_keyword_filters_before_limit_and_fts_updates(app):
    with TestClient(app) as client:
        seed(app.state.store)
        body={'query':'keyword','mode':'keyword','scope_node_id':'inside','group_ids':['g']}
        data=client.post('/api/search',json=body).json()
        assert [item['id'] for item in data['results']]==['z']
        with app.state.store.connection() as db: db.execute("UPDATE chunks SET text='different material' WHERE id='z'")
        assert client.post('/api/search',json=body).json()['results']==[]
        with app.state.store.connection() as db: db.execute("DELETE FROM chunks WHERE id='z'")
        assert client.get('/api/map').json()['points']==[]


def test_scoped_exact_semantic_search_and_changed_embeddings(app):
    with TestClient(app) as client:
        seed(app.state.store)
        app.state.embedder.encode=lambda query: np.array([1,0],dtype=np.float32)
        body={'query':'unshared vocabulary','mode':'semantic','scope_node_id':'inside'}
        assert client.post('/api/search',json=body).json()['results'][0]['id']=='z'
        with app.state.store.connection() as db: db.execute("UPDATE embeddings SET config_id='changed' WHERE chunk_id='z'")
        response=client.post('/api/search',json=body)
        assert response.status_code==400 and 'Rebuild' in response.json()['error']
        assert client.get('/api/map').json()['points']==[]


def test_unknown_filters_are_rejected_and_node_counts_include_descendants(app):
    with TestClient(app) as client:
        seed(app.state.store)
        roots=client.get('/api/nodes').json()['nodes']
        assert next(item for item in roots if item['id']=='root')['chunk_count']==1
        assert client.get('/api/map?scope_node_id=missing').status_code==400
        assert client.post('/api/search',json={'query':'keyword','mode':'keyword','group_ids':['unknown']}).status_code==400
        assert client.post('/api/search',json={'query':'keyword','mode':'unexpected'}).status_code==422
        assert client.post('/api/search',json={'query':'keyword','unexpected':True}).status_code==422


def test_map_pagination_source_preview_and_issue_reporting(app):
    with TestClient(app) as client:
        seed(app.state.store)
        with app.state.store.connection() as db:
            db.execute("INSERT INTO ingestion_issues(id,node_id,title,message,locator,question,affected_count) VALUES('gap','inside','Missing content','Rows lacked text','temporary rows','Is another export available?',4)")
        page=client.get('/api/map?scope_node_id=inside&group_ids=g&limit=1').json()
        assert page['total_points']==1 and page['points'][0]['chunk_id']=='z'
        assert client.get('/api/chunks/z').json()['locator']=='temporary row'
        issue=client.get('/api/issues').json()['issues'][0]
        assert issue['affected_count']==4 and issue['question'] and issue['path']==['Root','Section']
        assert client.get('/api/chunks/missing').status_code==404
        assert client.get('/api/unknown').status_code==404


def test_static_mount_never_serves_private_files(tmp_path):
    dist=tmp_path/'dist';dist.mkdir();(dist/'index.html').write_text('Local RAG')
    (tmp_path/'.env').write_text('SECRET=private')
    app=create_app(Settings(database_path=tmp_path/'private.sqlite3',frontend_dist=dist))
    with TestClient(app) as client:
        assert client.get('/').text=='Local RAG'
        assert client.get('/.env').status_code==404
        assert client.get('/private.sqlite3').status_code==404
        assert client.get('/api/unknown').status_code==404


def test_hybrid_merges_independent_scoped_pools_without_duplicates(app):
    with TestClient(app) as client:
        seed(app.state.store)
        with app.state.store.connection() as db:
            db.execute("INSERT INTO chunks(id,node_id,group_id,title,text,path_json,input_hash) VALUES('semantic-only','inside','g','Different words','alternate evidence','[]','hash')")
            db.execute("INSERT INTO embeddings VALUES('semantic-only','minishlab/potion-base-2M','potion-base-2M:cosine:v1',2,'hash',?)",(np.array([1,0],dtype='<f4').tobytes(),))
            db.execute("INSERT INTO embeddings VALUES('a000','minishlab/potion-base-2M','potion-base-2M:cosine:v1',2,'hash',?)",(np.array([1,0],dtype='<f4').tobytes(),))
        app.state.embedder.encode=lambda query: np.array([1,0],dtype=np.float32)
        response=client.post('/api/search',json={'query':'keyword','mode':'hybrid','scope_node_id':'inside','group_ids':['g']})
        assert response.status_code==200
        ids=[item['id'] for item in response.json()['results']]
        assert set(ids)=={'z','semantic-only'} and len(ids)==2
