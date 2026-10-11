"""Remove repeated evidence and reconnect known adjacent source passages."""
import hashlib
import re
from .models import Chunk, SourceReference


def text_key(text: str) -> str:
    # Whitespace-only differences are extraction/layout noise. Keep case,
    # punctuation, numbers and qualifications; never deduplicate by similarity.
    return ' '.join(text.split())


def references(chunk: Chunk) -> list[SourceReference]:
    return chunk.source_refs or [SourceReference(
        id=chunk.id, node_id=chunk.node_id, title=chunk.title, path=chunk.path,
        locator=chunk.locator, source_url=chunk.source_url)]


def unique_passages(chunks: list[Chunk]) -> tuple[list[Chunk], int]:
    """Retain the highest-ranked body once and all eligible source occurrences."""
    result=[]; positions={}; removed=0
    for chunk in chunks:
        key=text_key(chunk.text)
        if key not in positions:
            positions[key]=len(result); result.append(chunk)
            continue
        index=positions[key]; first=result[index]; refs=references(first)
        ids={ref.id for ref in refs}
        refs=refs+[ref for ref in references(chunk) if ref.id not in ids]
        notes=list(dict.fromkeys(c.coverage_note for c in [first,chunk] if c.coverage_note))
        result[index]=first.model_copy(update={'source_refs':refs,'coverage_note':' '.join(notes) or None})
        removed+=1
    return result, removed


def join_text(left: str, right: str) -> tuple[str, int]:
    """Trim only an exact suffix/prefix overlap at a verified adjacent boundary."""
    a=re.findall(r'\S+',left); b=list(re.finditer(r'\S+',right))
    words=[match.group() for match in b]
    # Short common words/phrases are not reliable evidence of chunk overlap.
    for count in range(min(len(a),len(words)),7,-1):
        if a[-count:]==words[:count]:
            tail=right[b[count-1].end():].lstrip()
            return left.rstrip()+('\n\n'+tail if tail else ''),count
    return left.rstrip()+'\n\n'+right.lstrip(),0


def assemble_passages(chunks: list[Chunk], section_orders: dict[str,list[str]]):
    """Join contiguous selected runs, never bridge an unselected source passage."""
    unique,duplicates=unique_passages(chunks)
    by_id={c.id:c for c in unique}; priorities={c.id:i for i,c in enumerate(unique)}
    removed_ids={c.id for c in chunks if c.id not in by_id}
    runs=[]; grouped=set()
    for node_id,order in section_orders.items():
        run=[]
        for id in order:
            if id in by_id:
                run.append(by_id[id]); grouped.add(id)
            elif id in removed_ids:
                # Its exact body is already retained; this is not missing text.
                continue
            elif run:
                runs.append(run); run=[]
        if run: runs.append(run)
    runs.extend([chunk] for chunk in unique if chunk.id not in grouped)
    runs.sort(key=lambda run:min(priorities[c.id] for c in run))
    result=[]; overlaps=0; joins=0
    for run in runs:
        if len(run)==1:
            result.append(run[0]); continue
        primary=min(run,key=lambda c:priorities[c.id])
        text=run[0].text
        for following in run[1:]:
            text,removed=join_text(text,following.text); overlaps+=removed
        refs=[]; seen=set()
        for part in run:
            for ref in references(part):
                if ref.id not in seen: refs.append(ref); seen.add(ref.id)
        locators=list(dict.fromkeys(ref.locator for ref in refs if ref.locator))
        notes=list(dict.fromkeys(c.coverage_note for c in run if c.coverage_note))
        identity='\0'.join([*(ref.id for ref in refs),text])
        combined=primary.model_copy(update={
            'id':'context-'+hashlib.sha256(identity.encode()).hexdigest()[:20],
            'text':text, 'locator':'; '.join(locators), 'source_refs':refs,
            'coverage_note':' '.join(notes) or None})
        # If the joined run cannot fit, pack complete components in retrieval
        # priority order instead; never clip or discard an otherwise fitting seed.
        combined._parts=sorted(run,key=lambda c:priorities[c.id])
        result.append(combined); joins+=len(run)-1
    return result, {'input_passages':len(chunks),'duplicates_removed':duplicates,
                    'joins':joins,'overlap_tokens_removed':overlaps}
