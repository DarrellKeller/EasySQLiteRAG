import asyncio
import threading
from time import perf_counter
from contextlib import asynccontextmanager
import httpx
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from .llm import ModelOutputError, generate_answer
from .models import (ChatResponse, Chunk, ChunkPage, IssuePage, MapPage, NodePage,
                     PublicConfig, SearchRequest, SearchResponse, SearchTrace, TraceStep, Theme)
from .settings import Settings
from .store import Store
from .context import unique_passages


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
            self.model.tokenizer.no_truncation()
            if len(self.model.tokenizer.encode(query, add_special_tokens=False).ids) > self.settings.embedding_max_tokens:
                raise ValueError('The query exceeds the configured embedding token cap. Shorten it, use Keyword mode, or rebuild with a reviewed larger embedding cap.')
            return self.model.encode([query], max_length=self.settings.embedding_max_tokens)[0]


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
        trace=getattr(request.state,'trace',None)
        return JSONResponse({'error':str(error),'trace':trace.model_dump() if trace else None},status_code=400)

    @app.exception_handler(KeyError)
    async def missing_source(request,error):
        return JSONResponse({'error':'Source passage not found.'},status_code=404)

    @app.exception_handler(ModelOutputError)
    async def model_error(request,error):
        trace=getattr(request.state,'trace',None)
        return JSONResponse({'error':str(error),'trace':trace.model_dump() if trace else None},status_code=502)

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

    async def retrieve(body, request):
        trace=SearchTrace(query=body.query,mode=body.mode,scope_node_id=body.scope_node_id,group_ids=body.group_ids)
        request.state.trace=trace

        async def step(name,detail,operation):
            started=perf_counter()
            entry=TraceStep(name=name,status='completed',detail=detail)
            trace.steps.append(entry)
            try:
                return await operation()
            except (ValueError,ModelOutputError):
                entry.status='failed'
                raise
            finally:
                entry.duration_ms=round((perf_counter()-started)*1000,2)

        total=await step('Filters','Apply hierarchy and group filters before ranking.',lambda: asyncio.to_thread(store.eligible_count,body))
        trace.steps[-1].result_count=total
        if not total:
            trace.steps.append(TraceStep(name='Retrieval',status='skipped',detail='No eligible passages; no keyword search, embedding or vector search ran.'))
            return [],'No indexed passages in this scope.',trace

        lexical=[]
        if body.mode != 'semantic':
            expression=store.match_expression(body.query)
            lexical=await step('Keyword search',f'SQLite FTS5 MATCH: {expression or "(no searchable terms)"}. BM25 ordering; limit 80.',lambda: asyncio.to_thread(store.lexical,body))
            trace.steps[-1].result_count=len(lexical)
            trace.steps[-1].result_ids=[item.id for item in lexical]
        else:
            trace.steps.append(TraceStep(name='Keyword search',status='skipped',detail='Semantic mode selected.'))
        semantic=[]
        if body.mode != 'keyword':
            vector=await step('Query embedding',f'{settings.embedding_provider}: {settings.embedding_model}; original query; no expansion.',lambda: asyncio.to_thread(embedder.encode,body.query))
            metrics={}
            semantic=await step('Vector search','Exact cosine similarity over scoped embeddings; limit 80.',lambda: asyncio.to_thread(store.exact,body,vector,settings.embedding_model,settings.embedding_config_id,metrics=metrics))
            trace.steps[-1].detail+=f' Scored {metrics["scored_vectors"]} vectors of {metrics["dimensions"]} dimensions; config {settings.embedding_config_id}.'
            trace.steps[-1].result_count=len(semantic)
            trace.steps[-1].result_ids=[item.id for item in semantic]
        else:
            trace.steps.append(TraceStep(name='Vector search',status='skipped',detail='Keyword mode selected; no embedding call.'))
        # Rank-based fusion; independent candidate pools within the same scope.
        merge_started=perf_counter()
        scores={};chunks={}
        for ranking in [lexical,semantic]:
            for rank,item in enumerate(ranking,1):
                chunks[item.id]=item;scores[item.id]=scores.get(item.id,0)+1/(60+rank)
        ranked_ids=sorted(scores,key=lambda id:(-scores[id],id))
        results,duplicates=unique_passages([chunks[id] for id in ranked_ids])
        results=results[:80]
        trace.steps.append(TraceStep(name='Result merge',status='completed',detail=f'Reciprocal rank fusion k=60 over independent keyword/vector pools; no protected prefix; deduplicate identical text before limit 80 ({duplicates} repeats removed; source locations retained). No query expansion or synonym/typo correction ran.',duration_ms=round((perf_counter()-merge_started)*1000,2),result_count=len(results),result_ids=[item.id for item in results]))
        note='Ranked matches; this is not an exhaustive list.'
        if any(item.coverage_note for item in results): note+=' Some retrieved sources have reported gaps.'
        return results,note,trace

    @app.post('/api/search',response_model=SearchResponse)
    async def search(body: SearchRequest,request: Request):
        results,note,trace=await retrieve(body,request)
        trace.steps.append(TraceStep(name='Answer generation',status='skipped',detail='Sources only; no answer-model call.'))
        return SearchResponse(results=results,coverage_note=note,trace=trace)

    @app.post('/api/chat',response_model=ChatResponse)
    async def chat(body: SearchRequest,request: Request):
        evidence,note,trace=await retrieve(body,request)
        if not evidence:
            trace.steps.append(TraceStep(name='Answer generation',status='skipped',detail='No matching evidence; no answer-model call.'))
            return ChatResponse(answer='I do not have enough evidence in this scope to answer.',citations=[],insufficient_evidence=True,coverage_note=note,trace=trace)
        seeds=evidence[:settings.retrieval_cap]
        started=perf_counter()
        evidence=await asyncio.to_thread(store.expand_context,body,seeds,settings.context_neighbors)
        trace.steps.append(TraceStep(name='Section context',status='completed',detail=f'Top {len(seeds)} unique ranked seeds; configured retrieval cap {settings.retrieval_cap}. Add up to {settings.context_neighbors} preceding/following chunks from the same node, within explicit filters. Source order retained.',duration_ms=round((perf_counter()-started)*1000,2),result_count=len(evidence),result_ids=[c.id for c in evidence]))
        started=perf_counter()
        evidence,assembly=await asyncio.to_thread(store.assemble_context,evidence)
        trace.steps.append(TraceStep(name='Context assembly',status='completed',detail=f"Join verified adjacent passages in source order; {assembly['joins']} joins, {assembly['duplicates_removed']} identical passages removed, {assembly['overlap_tokens_removed']} exact overlapping words removed. Preserve source locations; do not bridge missing passages or sections. Oversized joins fall back to complete original chunks.",duration_ms=round((perf_counter()-started)*1000,2),result_count=len(evidence),result_ids=[c.id for c in evidence]))
        packing=TraceStep(name='Evidence packing',status='completed',detail='Count selected model tokens; preserve complete passages.')
        trace.steps.append(packing)
        generation=TraceStep(name='Answer generation',status='completed',detail=f'{settings.llm_provider}: {settings.llm_model}; complete passages within token budget; Pydantic JSON/citation validation; at most one repair retry.')
        trace.steps.append(generation);started=perf_counter()
        try:
            answer=await generate_answer(settings,body,evidence,request.app.state.model_client,packing)
        except ModelOutputError:
            generation.status='failed'
            raise
        finally:
            generation.duration_ms=round((perf_counter()-started)*1000,2)
        chunks={item.id:item for chunk in evidence for item in [chunk,*chunk._parts]}
        return ChatResponse(answer=answer.answer,citations=[chunks[id] for id in answer.citation_ids],insufficient_evidence=answer.insufficient_evidence,coverage_note=note,trace=trace)

    @app.get('/api/map',response_model=MapPage)
    async def map_data(request: Request,scope_node_id: str | None=None,group_ids: list[str]=Query(default=[]),query: str='',mode: str='hybrid',cursor: str | None=None,limit: int=Query(5000,ge=1,le=5000)):
        if len(query)>4000 or len(group_ids)>100 or mode not in ['hybrid','keyword','semantic']:
            raise HTTPException(422,'Invalid map query or filters.')
        body=SearchRequest(query=query or ' ',scope_node_id=scope_node_id,group_ids=group_ids,mode=mode)
        matches=None;note=None;trace=None
        if query.strip():
            results,note,trace=await retrieve(body,request);matches=[item.id for item in results]
        map_started=perf_counter()
        points,groups,total,next_cursor=await asyncio.to_thread(store.map_page,body,cursor,limit,settings.embedding_config_id,settings.embedding_model,matches)
        if trace:
            trace.steps.append(TraceStep(name='Map',status='completed',detail='Return stored coordinates for matched passages; no answer-model call.',duration_ms=round((perf_counter()-map_started)*1000,2),result_count=len(points),result_ids=[point['chunk_id'] for point in points]))
        return MapPage(points=points,groups=groups,total_points=total,next_cursor=next_cursor,coverage_note=note,trace=trace)

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
