import asyncio
import json
import httpx
import pytest
from local_rag.llm import ModelOutputError, generate_answer, validate_answer
from local_rag.models import Chunk, SearchRequest
from local_rag.settings import Settings

EVIDENCE=[Chunk(id='test-id',node_id='test-node',title='Temporary test evidence',text='The recorded value is seven.',path=['Test'])]
GOOD={'answer':'The recorded value is seven [1].','citation_ids':['test-id'],'insufficient_evidence':False}


@pytest.mark.parametrize('content',[
    'not JSON',
    json.dumps({**GOOD,'insufficient_evidence':'false'}),
    json.dumps({**GOOD,'unexpected':'extra'}),
    json.dumps({**GOOD,'citation_ids':['invented']}),
    json.dumps({**GOOD,'citation_ids':['test-id','test-id']}),
    json.dumps({**GOOD,'answer':'Unmatched reference [2].'}),
    json.dumps({**GOOD,'citation_ids':[]}),
])
def test_rejects_bad_output(content):
    with pytest.raises(ValueError): validate_answer(content,EVIDENCE)


def test_valid_schema_and_insufficient_evidence():
    assert validate_answer(json.dumps(GOOD),EVIDENCE).citation_ids==['test-id']
    assert validate_answer(json.dumps({'answer':'Insufficient evidence.','citation_ids':[],'insufficient_evidence':True}),EVIDENCE).insufficient_evidence


def call_with_responses(contents):
    calls=[]
    async def run():
        def handler(request):
            calls.append(json.loads(request.content))
            return httpx.Response(200,json={'message':{'content':contents[min(len(calls)-1,len(contents)-1)]}})
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await generate_answer(Settings(),SearchRequest(query='What is the value?'),EVIDENCE,client)
    return run,calls


def test_schema_sent_to_ollama_and_one_repair_can_succeed():
    run,calls=call_with_responses(['invalid',json.dumps(GOOD)])
    assert asyncio.run(run()).answer==GOOD['answer']
    assert len(calls)==2
    assert calls[0]['format']['additionalProperties'] is False
    assert calls[0]['stream'] is False and calls[0]['options']['temperature']==0
    assert 'Answer simply' in calls[0]['messages'][0]['content']


def test_invalid_output_stops_after_one_repair():
    run,calls=call_with_responses(['invalid'])
    with pytest.raises(ModelOutputError): asyncio.run(run())
    assert len(calls)==2


def test_context_overflow_fails_before_model_request():
    calls=[]
    async def run():
        def handler(request):
            calls.append(request)
            return httpx.Response(200,json={'message':{'content':json.dumps(GOOD)}})
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await generate_answer(Settings(context_tokens=2048),SearchRequest(query='x'*4000),EVIDENCE,client)
    with pytest.raises(ModelOutputError): asyncio.run(run())
    assert not calls
