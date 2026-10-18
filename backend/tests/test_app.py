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


def test_trace_reports_actual_keyword_query_filters_and_no_model_call(app):
    with TestClient(app) as client:
        seed(app.state.store)
        app.state.embedder.encode=lambda query: pytest.fail('Keyword search must not embed')
        response=client.post('/api/search',json={'query':'"keyword evidence"','mode':'keyword','scope_node_id':'inside','group_ids':['g']})
        trace=response.json()['trace']
        assert trace['query']=='"keyword evidence"' and trace['expansions']==[]
        assert trace['scope_node_id']=='inside' and trace['group_ids']==['g']
        steps={step['name']:step for step in trace['steps']}
        assert steps['Filters']['result_count']==1
        assert 'MATCH: "keyword evidence"' in steps['Keyword search']['detail']
        assert steps['Keyword search']['result_ids']==['z']
        assert steps['Vector search']['status']=='skipped'
        assert steps['Answer generation']['status']=='skipped'
        assert all(step['duration_ms']>=0 for step in trace['steps'])


def test_trace_scored_vectors_and_map_search(app):
    with TestClient(app) as client:
        seed(app.state.store)
        app.state.embedder.encode=lambda query: np.array([1,0],dtype=np.float32)
        response=client.get('/api/map?query=keyword&scope_node_id=inside')
        trace=response.json()['trace']
        steps={step['name']:step for step in trace['steps']}
        assert 'Scored 1 vectors of 2 dimensions' in steps['Vector search']['detail']
        assert steps['Result merge']['result_ids']==['z']
        assert steps['Map']['result_ids']==['z']
        assert client.get('/api/map').json()['trace'] is None


def test_partial_trace_survives_embedding_and_generation_errors(app,monkeypatch):
    from local_rag.llm import ModelOutputError
    with TestClient(app) as client:
        seed(app.state.store)
        def unavailable(query): raise ValueError('Embedding unavailable')
        app.state.embedder.encode=unavailable
        response=client.post('/api/search',json={'query':'keyword','scope_node_id':'inside'})
        assert response.status_code==400
        assert response.json()['trace']['steps'][-1]['status']=='failed'
        assert response.json()['trace']['steps'][1]['result_ids']==['z']
        async def failed_generation(*args): raise ModelOutputError('Ollama unavailable')
        monkeypatch.setattr('local_rag.app.generate_answer',failed_generation)
        response=client.post('/api/chat',json={'query':'keyword','mode':'keyword','scope_node_id':'inside'})
        assert response.status_code==502
        assert response.json()['trace']['steps'][-1]['name']=='Answer generation'
        assert response.json()['trace']['steps'][-1]['status']=='failed'


def test_empty_trace_does_not_claim_search_or_inference_ran(app):
    with TestClient(app) as client:
        trace=client.post('/api/chat',json={'query':'Anything'}).json()['trace']
        assert [step['status'] for step in trace['steps']]==['completed','skipped','skipped']
        assert trace['steps'][0]['result_count']==0


def test_fused_consensus_hits_are_not_displaced_by_a_protected_prefix(app):
    from local_rag.models import Chunk
    def chunk(id): return Chunk(id=id,node_id='inside',title='Evidence',text=f'Actual text {id}',path=[])
    with TestClient(app) as client:
        seed(app.state.store)
        lexical=[chunk('keyword-best')]+[chunk(f'common-{i}') for i in range(30)]
        semantic=[chunk(f'common-{i}') for i in range(30)]
        app.state.store.lexical=lambda *a: lexical
        def exact(*a,metrics=None,**kw):
            metrics.update(scored_vectors=31,dimensions=2);return semantic
        app.state.store.exact=exact
        app.state.embedder.encode=lambda query: np.array([1,0],dtype=np.float32)
        ids=[c['id'] for c in client.post('/api/search',json={'query':'keyword'}).json()['results']]
        assert ids[:5]==[f'common-{i}' for i in range(5)]
        assert len(ids)==len(set(ids))
        assert 'keyword-best' in ids


def test_context_uses_source_order_and_respects_group_and_section(app):
    from local_rag.models import SearchRequest
    with TestClient(app):
        seed(app.state.store)
        with app.state.store.connection() as db:
            db.execute("UPDATE chunks SET source_order=20 WHERE id='z'")
            for id,order,group,node in [('before',10,'g','inside'),('after',30,'g','inside'),('wrong-group',21,None,'inside'),('wrong-section',22,'g','outside')]:
                db.execute("INSERT INTO chunks(id,node_id,group_id,title,text,path_json,input_hash,source_order) VALUES(?,?,?,?,?,?,?,?)",(id,node,group,'Section','Full exception','[]','hash',order))
        request=SearchRequest(query='keyword',scope_node_id='inside',group_ids=['g'])
        context=app.state.store.expand_context(request,[app.state.store.get_chunk('z')])
        assert [c.id for c in context]==['z','before','after']
        assert all(c.text for c in context)


def test_chat_sends_both_pools_and_section_context(app,monkeypatch):
    from local_rag.models import Chunk,ModelAnswer
    captured=[]
    with TestClient(app) as client:
        seed(app.state.store)
        with app.state.store.connection() as db:
            db.execute("INSERT INTO chunks(id,node_id,title,text,path_json,input_hash,source_order) VALUES('neighbor','inside','Continuation','Complete exception','[]','hash',2)")
            db.execute("UPDATE chunks SET source_order=1 WHERE id='z'")
        lexical=[app.state.store.get_chunk('z')]
        semantic=[app.state.store.get_chunk('neighbor')]
        app.state.store.lexical=lambda *a:lexical
        def exact(*a,metrics=None,**kw):metrics.update(scored_vectors=2,dimensions=2);return semantic
        app.state.store.exact=exact;app.state.embedder.encode=lambda query:np.array([1,0],dtype=np.float32)
        async def generate(settings,body,evidence,client,packing):
            captured.extend(evidence);packing.result_ids=[c.id for c in evidence]
            return ModelAnswer(answer='Complete exception [1].',citation_ids=['neighbor'],insufficient_evidence=False)
        monkeypatch.setattr('local_rag.app.generate_answer',generate)
        data=client.post('/api/chat',json={'query':'keyword','scope_node_id':'inside'}).json()
        assert len(captured)==1
        assert captured[0].text=='keyword evidence\n\nComplete exception'
        assert [r.id for r in captured[0].source_refs]==['z','neighbor']
        assert data['citations'][0]['id']=='neighbor'
        assert set(next(t for t in data['trace']['steps'] if t['name']=='Section context')['result_ids'])=={'z','neighbor'}


def test_search_removes_identical_text_before_limit_and_preserves_scoped_sources(app):
    with TestClient(app) as client:
        seed(app.state.store)
        data=client.post('/api/search',json={'query':'keyword','mode':'keyword'}).json()
        assert len(data['results'])==1
        assert len(data['results'][0]['source_refs'])==80
        assert 'repeats removed' in next(s['detail'] for s in data['trace']['steps'] if s['name']=='Result merge')
        scoped=client.post('/api/search',json={'query':'keyword','mode':'keyword','scope_node_id':'inside'}).json()
        assert [c['id'] for c in scoped['results']]==['z']
        assert scoped['results'][0]['source_refs']==[]


def test_assembled_context_never_crosses_an_excluded_group_gap(app):
    from local_rag.models import SearchRequest
    with TestClient(app):
        seed(app.state.store)
        with app.state.store.connection() as db:
            db.execute("UPDATE chunks SET source_order=1 WHERE id='z'")
            for id,order,group in [('excluded',2,None),('after',3,'g')]:
                db.execute("INSERT INTO chunks(id,node_id,group_id,title,text,path_json,input_hash,source_order) VALUES(?,?,?,?,?,?,?,?)",(id,'inside',group,'Section',id,'[]','hash',order))
        req=SearchRequest(query='keyword',scope_node_id='inside',group_ids=['g'])
        expanded=app.state.store.expand_context(req,[app.state.store.get_chunk('z')])
        context,_=app.state.store.assemble_context(expanded)
        assert [c.id for c in context]==['z','after']


def test_chat_retrieval_cap_limits_seeds_before_context_packing(app,monkeypatch):
    from local_rag.models import Chunk,ModelAnswer
    captured=[]
    with TestClient(app) as client:
        seed(app.state.store)
        ranked=[Chunk(id=f'c{i}',node_id='inside',title='Evidence',text=f'Distinct fact {i}',path=[]) for i in range(10)]
        app.state.store.lexical=lambda *a:ranked
        async def generate(settings,body,evidence,client,packing):
            captured.extend(evidence)
            return ModelAnswer(answer='Fact zero [1].',citation_ids=['c0'],insufficient_evidence=False)
        monkeypatch.setattr('local_rag.app.generate_answer',generate)
        data=client.post('/api/chat',json={'query':'keyword','mode':'keyword'}).json()
        assert [c.id for c in captured]==[f'c{i}' for i in range(3)]
        context=next(s for s in data['trace']['steps'] if s['name']=='Section context')
        assert context['result_count']==3 and 'retrieval cap 3' in context['detail']


def test_grounded_table_relations_retain_anchors_if_indexed_evidence_is_removed(app):
    import sqlite3
    with TestClient(app):
        seed(app.state.store)
        with app.state.store.connection() as db:
            db.execute("INSERT INTO node_relations VALUES('link','root','inside','references','Shared key documented in source','source table note','z')")
            with pytest.raises(sqlite3.IntegrityError):
                db.execute("INSERT INTO node_relations VALUES('invalid','root','unknown','references','Unsupported target','source table note',NULL)")
            db.execute("DELETE FROM chunks WHERE id='z'")
            relation=db.execute("SELECT * FROM node_relations WHERE id='link'").fetchone()
            assert relation['source_locator']=='source table note' and relation['evidence_chunk_id'] is None
            assert db.execute('PRAGMA foreign_key_check').fetchall()==[]


def test_embedding_query_cap_is_explicit_and_never_silently_truncates():
    from local_rag.app import Embedder
    from types import SimpleNamespace
    embedder=Embedder(Settings(embedding_max_tokens=4))
    class Tokenizer:
        def no_truncation(self):pass
        def encode(self,text,**kwargs):return SimpleNamespace(ids=list(range(len(text))))
    def encode(texts,**kwargs):
        assert kwargs['max_length']==4
        return np.array([[1,0]],dtype=np.float32)
    embedder.model=SimpleNamespace(tokenizer=Tokenizer(),encode=encode)
    assert list(embedder.encode('fits'))==[1,0]
    with pytest.raises(ValueError,match='exceeds the configured embedding token cap'):
        embedder.encode('too long')
