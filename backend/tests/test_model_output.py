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


def test_missing_display_markers_are_built_from_validated_ids():
    result=validate_answer(json.dumps({**GOOD,"answer":"The recorded value is seven."}),EVIDENCE)
    assert result.answer == "The recorded value is seven. [1]"
    assert result.citation_ids == ["test-id"]


def test_abstention_without_markers_omits_unclaimed_citations():
    result=validate_answer(json.dumps({**GOOD,"answer":"There is not enough evidence.","insufficient_evidence":True}),EVIDENCE)
    assert result.citation_ids == []
    assert result.answer == "There is not enough evidence."


class GroupingTokenizer:
    """Deterministic token-unit stand-in; tests never download a model."""
    def apply_chat_template(self, messages, **kwargs):
        return list(range((sum(len(m['content']) for m in messages)+3)//4 + 16))


@pytest.fixture(autouse=True)
def local_token_counter(monkeypatch):
    monkeypatch.setattr('local_rag.llm.load_tokenizer', lambda *args: GroupingTokenizer())


def test_large_character_input_is_counted_in_tokens_and_not_cut():
    from local_rag.llm import pack_evidence
    from local_rag.models import TraceStep
    text=('A complete paragraph containing the exception. '*390)+'FINAL EXCEPTION: no fee.'
    chunk=EVIDENCE[0].model_copy(update={'text':text})
    _,messages,included,skipped,count,budget=pack_evidence(Settings(),SearchRequest(query='What is the exception?'),[chunk],GroupingTokenizer())
    sent=json.loads(messages[1]['content'])['evidence'][0]['text']
    assert len(text.encode()) > budget
    assert count <= budget and sent == text
    assert included=={'test-id'} and not skipped


def test_oversized_passage_is_skipped_whole_and_later_evidence_survives():
    from local_rag.llm import pack_evidence
    huge=EVIDENCE[0].model_copy(update={'id':'huge','text':'x'*40000})
    schema,messages,included,skipped,count,budget=pack_evidence(Settings(),SearchRequest(query='What is the value?'),[huge,*EVIDENCE],GroupingTokenizer())
    assert skipped==['huge'] and included=={'test-id'}
    assert json.loads(messages[1]['content'])['evidence'][0]['text']==EVIDENCE[0].text
    assert schema['properties']['citation_ids']['items']['enum']==['test-id']
    assert count <= budget


def test_repair_and_allowed_citation_ids_fit_the_same_budget():
    from local_rag.llm import pack_evidence,REPAIR_PROMPT
    tokenizer=GroupingTokenizer();settings=Settings()
    schema,messages,_,_,_,budget=pack_evidence(settings,SearchRequest(query='What is the value?'),EVIDENCE,tokenizer)
    assert 'test-id' in messages[0]['content']
    repaired=messages+[{'role':'user','content':REPAIR_PROMPT}]
    assert len(tokenizer.apply_chat_template(repaired)) <= budget


def test_tokenizer_mapping_is_rejected_instead_of_counting_dictionary_keys():
    from local_rag.llm import pack_evidence
    class MappingTokenizer:
        def apply_chat_template(self,*args,**kwargs):return {'input_ids':[1]*4000,'attention_mask':[1]*4000}
    with pytest.raises(ModelOutputError,match='unexpected token sequence'):
        pack_evidence(Settings(),SearchRequest(query='Question'),EVIDENCE,MappingTokenizer())
