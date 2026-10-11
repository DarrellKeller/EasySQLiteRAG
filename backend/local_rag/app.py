import asyncio
import threading
from contextlib import asynccontextmanager
import httpx
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from .llm import ModelOutputError, generate_answer
from .models import (ChatResponse, Chunk, ChunkPage, IssuePage, MapPage, NodePage,
                     PublicConfig, SearchRequest, SearchResponse, Theme)
from .settings import Settings
from .store import Store


class Embedder:
    def __init__(self, settings):
        self.settings=settings;self.model=None;self.lock=threading.Lock()

    def encode(self, query):
        if self.settings.embedding_provider != 'model2vec':
            raise ValueError('The selected embedding provider needs an adapter. Ask your coding agent to configure it.')
        with self.lock:
            if self.model is None:
                try:
                    from model2vec import StaticModel
                    self.model=StaticModel.from_pretrained(self.settings.embedding_model)
                except ImportError:
                    raise ValueError('Install backend embedding dependencies, or use Keyword mode.') from None
                except Exception:
                    raise ValueError('The embedding model could not be loaded. Check the model download, or use Keyword mode.') from None
            return self.model.encode([query])[0]


def create_app(settings: Settings | None = None):
    settings=settings or Settings.from_env();store=Store(settings.database_path);embedder=Embedder(settings)

    @asynccontextmanager
    async def lifespan(app):
        store.initialize()
        async with httpx.AsyncClient(timeout=120) as client:
            app.state.model_client=client
            yield

    app=FastAPI(title='Local RAG',lifespan=lifespan)
    app.state.store=store;app.state.embedder=embedder

    @app.exception_handler(HTTPException)
    async def http_error(request, error):
        return JSONResponse({'error':str(error.detail)},status_code=error.status_code)

    @app.exception_handler(RequestValidationError)
    async def request_error(request,error):
        return JSONResponse({'error':'Invalid request. Check the query, filters and search mode.'},status_code=422)

    @app.exception_handler(ValueError)
    async def data_error(request,error):
        return JSONResponse({'error':str(error)},status_code=400)

    @app.exception_handler(KeyError)
    async def missing_source(request,error):
        return JSONResponse({'error':'Source passage not found.'},status_code=404)

    @app.exception_handler(ModelOutputError)
    async def model_error(request,error):
        return JSONResponse({'error':str(error)},status_code=502)

    @app.get('/api/config',response_model=PublicConfig)
    def config():
        return PublicConfig(theme=Theme(primary=settings.theme_primary,secondary=settings.theme_secondary),**store.counts())

    @app.get('/api/nodes',response_model=NodePage)
    def nodes(parent_id: str | None=None,cursor: str | None=None,limit: int=Query(100,ge=1,le=500)):
        records,next_cursor=store.nodes(parent_id,cursor,limit)
        return NodePage(nodes=records,next_cursor=next_cursor)

    @app.get('/api/nodes/{node_id}/chunks',response_model=ChunkPage)
    def preview(node_id: str,limit: int=Query(1,ge=1,le=20)):
        return ChunkPage(chunks=store.preview(node_id,limit))

    @app.get('/api/chunks/{chunk_id}',response_model=Chunk)
    def chunk(chunk_id: str):
        return store.get_chunk(chunk_id)

    @app.get('/api/issues',response_model=IssuePage)
    def issues():
        return IssuePage(issues=store.issues())

    async def retrieve(body):
        total=await asyncio.to_thread(store.eligible_count,body)
        if not total: return [],'No indexed passages in this scope.'
        lexical=await asyncio.to_thread(store.lexical,body) if body.mode != 'semantic' else []
        semantic=[]
        if body.mode != 'keyword':
            vector=await asyncio.to_thread(embedder.encode,body.query)
            semantic=await asyncio.to_thread(store.exact,body,vector,settings.embedding_model,settings.embedding_config_id)
        # Rank-based fusion; independent candidate pools within the same scope.
        scores={};chunks={}
        for ranking in [lexical,semantic]:
            for rank,item in enumerate(ranking,1):
                chunks[item.id]=item;scores[item.id]=scores.get(item.id,0)+1/(60+rank)
        results=[chunks[id] for id in sorted(scores,key=lambda id:(-scores[id],id))[:80]]
        note='Ranked matches; this is not an exhaustive list.'
        if any(item.coverage_note for item in results): note+=' Some retrieved sources have reported gaps.'
        return results,note

    @app.post('/api/search',response_model=SearchResponse)
    async def search(body: SearchRequest):
        results,note=await retrieve(body)
        return SearchResponse(results=results,coverage_note=note)

    @app.post('/api/chat',response_model=ChatResponse)
    async def chat(body: SearchRequest,request: Request):
        evidence,note=await retrieve(body)
        if not evidence:
            return ChatResponse(answer='I do not have enough evidence in this scope to answer.',citations=[],insufficient_evidence=True,coverage_note=note)
        answer=await generate_answer(settings,body,evidence[:8],request.app.state.model_client)
        chunks={item.id:item for item in evidence}
        return ChatResponse(answer=answer.answer,citations=[chunks[id] for id in answer.citation_ids],insufficient_evidence=answer.insufficient_evidence,coverage_note=note)

    @app.get('/api/map',response_model=MapPage)
    async def map_data(scope_node_id: str | None=None,group_ids: list[str]=Query(default=[]),query: str='',mode: str='hybrid',cursor: str | None=None,limit: int=Query(5000,ge=1,le=5000)):
        if len(query)>4000 or len(group_ids)>100 or mode not in ['hybrid','keyword','semantic']:
            raise HTTPException(422,'Invalid map query or filters.')
        body=SearchRequest(query=query or ' ',scope_node_id=scope_node_id,group_ids=group_ids,mode=mode)
        matches=None;note=None
        if query.strip():
            results,note=await retrieve(body);matches=[item.id for item in results]
        points,groups,total,next_cursor=await asyncio.to_thread(store.map_page,body,cursor,limit,settings.embedding_config_id,settings.embedding_model,matches)
        return MapPage(points=points,groups=groups,total_points=total,next_cursor=next_cursor,coverage_note=note)

    # Unregistered API routes must never fall through to a static SPA response.
    @app.api_route('/api/{path:path}',methods=['GET','POST','PUT','DELETE','PATCH'])
    def unknown_api(path: str):
        raise HTTPException(404,'API route not found.')

    if settings.frontend_dist.is_dir():
        app.mount('/',StaticFiles(directory=settings.frontend_dist,html=True),name='frontend')
    else:
        @app.get('/')
        def build_needed():
            return {'message':'Build the Vite frontend with npm --prefix frontend run build, then restart the backend.'}
    return app


app=create_app()
