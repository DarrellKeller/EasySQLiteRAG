import json
from local_rag.context import assemble_passages, unique_passages
from local_rag.models import Chunk, SearchRequest
from local_rag.ingestion import navigation_only, content_hash


def chunk(id,text,node='section',**kwargs):
    return Chunk(id=id,node_id=node,title=node,text=text,path=['Source',node],locator=id,**kwargs)


def test_identical_bodies_are_removed_but_original_locations_survive():
    first=chunk('a','The limit is 15 percent.')
    duplicate=chunk('b','The limit is\n15 percent.','other-section')
    changed=chunk('c','The limit is 25 percent.')
    result,removed=unique_passages([first,duplicate,changed])
    assert [c.id for c in result]==['a','c'] and removed==1
    assert [r.id for r in result[0].source_refs]==['a','b']
    assert result[0].source_refs[1].node_id=='other-section'
    assert first.source_refs==[]  # Does not mutate original stored evidence.


def test_adjacent_context_is_in_source_order_with_exact_overlap_once():
    overlap='These eight shared words belong to the original paragraph.'
    a=chunk('a','First condition. '+overlap)
    b=chunk('b',overlap+' Final exception: no fee.')
    result,stats=assemble_passages([b,a],{'section':['a','b']})
    assert len(result)==1 and result[0].text.startswith('First condition.')
    assert result[0].text.count(overlap)==1
    assert result[0].text.endswith('Final exception: no fee.')
    assert [r.id for r in result[0].source_refs]==['a','b']
    assert [c.id for c in result[0]._parts]==['b','a']
    assert stats['joins']==1 and stats['overlap_tokens_removed']==9


def test_does_not_bridge_an_unselected_passage_or_a_different_section():
    a=chunk('a','First condition.')
    c=chunk('c','Third condition.')
    d=chunk('d','Different condition.','other')
    result,_=assemble_passages([a,c,d],{'section':['a','missing','c'],'other':['d']})
    assert [item.id for item in result]==['a','c','d']


def test_short_common_boundary_words_are_not_deleted():
    result,_=assemble_passages([chunk('a','First condition applies to the owner.'),
        chunk('b','owner. A second exception applies.')],{'section':['a','b']})
    assert 'owner.\n\nowner.' in result[0].text


def test_oversized_join_falls_back_to_complete_original_passages(monkeypatch):
    from local_rag.llm import pack_evidence
    from local_rag.settings import Settings
    class Tokenizer:
        def apply_chat_template(self,messages,**kwargs):
            return list(range(sum(len(m['content']) for m in messages)//4+16))
    a=chunk('a','a'*24000); b=chunk('b','b'*24000)
    joined,_=assemble_passages([a,b],{'section':['a','b']})
    _,messages,included,skipped,count,budget=pack_evidence(Settings(),SearchRequest(query='Question'),joined,Tokenizer())
    assert included=={'a'} and joined[0].id in skipped and 'b' in skipped
    assert json.loads(messages[1]['content'])['evidence'][0]['text']==a.text
    assert count<=budget


def test_navigation_detection_uses_confirmed_headings_not_shortness():
    headings={'Part One','Chapter Two'}
    assert navigation_only('Part One\nChapter Two',headings)
    assert not navigation_only('Part One\nThe fee is zero.',headings)
    assert not navigation_only('The fee is zero.',headings)
    assert not navigation_only('',headings)
    assert content_hash('The fee\nis zero.')==content_hash('The fee is zero.')
