import heapq
import json
import re
import sqlite3
from contextlib import contextmanager
from pathlib import Path
import numpy as np
from .models import Chunk, Node, SearchRequest

SCHEMA = """
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS sources (
 id TEXT PRIMARY KEY, title TEXT NOT NULL, locator TEXT NOT NULL,
 content_hash TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'ready'
);
CREATE TABLE IF NOT EXISTS nodes (
 id TEXT PRIMARY KEY, source_id TEXT REFERENCES sources(id), parent_id TEXT REFERENCES nodes(id),
 title TEXT NOT NULL, kind TEXT NOT NULL, description TEXT NOT NULL, path_json TEXT NOT NULL,
 status TEXT NOT NULL DEFAULT 'ready', source_url TEXT, coverage_note TEXT
);
CREATE INDEX IF NOT EXISTS nodes_parent ON nodes(parent_id);
CREATE TABLE IF NOT EXISTS groups (id TEXT PRIMARY KEY, title TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS chunks (
 id TEXT PRIMARY KEY, node_id TEXT NOT NULL REFERENCES nodes(id), group_id TEXT REFERENCES groups(id),
 title TEXT NOT NULL, text TEXT NOT NULL, path_json TEXT NOT NULL,
 locator TEXT NOT NULL DEFAULT '', source_url TEXT, coverage_note TEXT, input_hash TEXT NOT NULL, source_order INTEGER
);
CREATE INDEX IF NOT EXISTS chunks_node ON chunks(node_id);
CREATE INDEX IF NOT EXISTS chunks_group ON chunks(group_id);
CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(title,text,content='chunks',content_rowid='rowid');
CREATE TRIGGER IF NOT EXISTS chunks_ai AFTER INSERT ON chunks BEGIN
 INSERT INTO chunks_fts(rowid,title,text) VALUES(new.rowid,new.title,new.text); END;
CREATE TRIGGER IF NOT EXISTS chunks_ad AFTER DELETE ON chunks BEGIN
 INSERT INTO chunks_fts(chunks_fts,rowid,title,text) VALUES('delete',old.rowid,old.title,old.text); END;
CREATE TRIGGER IF NOT EXISTS chunks_au AFTER UPDATE ON chunks BEGIN
 INSERT INTO chunks_fts(chunks_fts,rowid,title,text) VALUES('delete',old.rowid,old.title,old.text);
 INSERT INTO chunks_fts(rowid,title,text) VALUES(new.rowid,new.title,new.text); END;
CREATE TABLE IF NOT EXISTS embeddings (
 chunk_id TEXT PRIMARY KEY REFERENCES chunks(id) ON DELETE CASCADE,
 model TEXT NOT NULL, config_id TEXT NOT NULL, dimensions INTEGER NOT NULL CHECK(dimensions>0),
 input_hash TEXT NOT NULL, vector BLOB NOT NULL
);
CREATE TABLE IF NOT EXISTS map_points (
 id TEXT PRIMARY KEY, chunk_id TEXT UNIQUE NOT NULL REFERENCES chunks(id) ON DELETE CASCADE,
 x REAL NOT NULL, y REAL NOT NULL, projection_version TEXT NOT NULL, embedding_config_id TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS ingestion_issues (
 id TEXT PRIMARY KEY, node_id TEXT REFERENCES nodes(id), title TEXT NOT NULL, message TEXT NOT NULL,
 locator TEXT NOT NULL, question TEXT, status TEXT NOT NULL DEFAULT 'open',
 affected_count INTEGER NOT NULL DEFAULT 1, affected_unit TEXT NOT NULL DEFAULT 'records',
 severity TEXT NOT NULL DEFAULT 'warning', resolution TEXT
);
"""


class Store:
    def __init__(self, path: Path):
        self.path = path

    @contextmanager
    def connection(self):
        with sqlite3.connect(self.path) as db:
            db.row_factory = sqlite3.Row
            db.execute("PRAGMA foreign_keys=ON")
            yield db

    def initialize(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as db:
            db.executescript(SCHEMA)
            if "source_order" not in {row[1] for row in db.execute("PRAGMA table_info(chunks)")}:
                db.execute("ALTER TABLE chunks ADD COLUMN source_order INTEGER")
            db.execute("CREATE INDEX IF NOT EXISTS chunks_section_order ON chunks(node_id, source_order)")

    def counts(self):
        with self.connection() as db:
            return {"total_chunks": db.execute("SELECT count(*) FROM chunks").fetchone()[0],
                    "total_nodes": db.execute("SELECT count(*) FROM nodes").fetchone()[0]}

    def scope(self, db, node_id, group_ids):
        clauses, params = [], []
        if node_id:
            if not db.execute("SELECT 1 FROM nodes WHERE id=?", (node_id,)).fetchone():
                raise ValueError("Unknown hierarchy scope.")
            clauses.append("c.node_id IN (WITH RECURSIVE branch(id) AS (SELECT id FROM nodes WHERE id=? UNION SELECT n.id FROM nodes n JOIN branch b ON n.parent_id=b.id) SELECT id FROM branch)")
            params.append(node_id)
        if group_ids:
            valid = {row[0] for row in db.execute("SELECT id FROM groups")}
            if not set(group_ids).issubset(valid):
                raise ValueError("Unknown group filter.")
            clauses.append("c.group_id IN (" + ",".join("?" for _ in group_ids) + ")")
            params.extend(group_ids)
        return " AND ".join(clauses) or "1", params

    @staticmethod
    def chunk(row):
        return Chunk(id=row['id'], node_id=row['node_id'], title=row['title'], text=row['text'],
                     path=json.loads(row['path_json']), locator=row['locator'],
                     source_url=row['source_url'], coverage_note=row['coverage_note'])

    def get_chunk(self, chunk_id):
        with self.connection() as db:
            row = db.execute("SELECT * FROM chunks WHERE id=?", (chunk_id,)).fetchone()
            if not row:
                raise KeyError("Source passage not found.")
            return self.chunk(row)

    def expand_context(self, request, seeds, neighbors=1):
        """Keep every seed first; append nearest same-section evidence within scope.

        Ingestion records source_order. Legacy databases use insertion order,
        never lexicographic IDs or a neighboring page from a different section.
        """
        result=list(seeds);seen={chunk.id for chunk in seeds}
        if not neighbors:
            return result
        with self.connection() as db:
            where,params=self.scope(db, request.scope_node_id, request.group_ids)
            for seed in seeds:
                position=db.execute("SELECT coalesce(source_order,rowid) FROM chunks WHERE id=?",(seed.id,)).fetchone()
                if not position:
                    continue
                for operator,direction in [("<","DESC"),(">","ASC")]:
                    rows=db.execute("SELECT c.* FROM chunks c WHERE "+where+
                        " AND c.node_id=? AND coalesce(c.source_order,c.rowid) "+operator+" ? ORDER BY coalesce(c.source_order,c.rowid) "+direction+" LIMIT ?",
                        [*params,seed.node_id,position[0],neighbors]).fetchall()
                    for row in rows:
                        if row['id'] not in seen:
                            seen.add(row['id']);result.append(self.chunk(row))
        return result

    def nodes(self, parent, cursor, limit):
        with self.connection() as db:
            if parent and not db.execute("SELECT 1 FROM nodes WHERE id=?", (parent,)).fetchone():
                raise ValueError("Unknown parent node.")
            rows = db.execute("SELECT * FROM nodes WHERE parent_id IS ? AND id>? ORDER BY id LIMIT ?", (parent, cursor or '', limit+1)).fetchall()
            result = []
            for row in rows[:limit]:
                where, params = self.scope(db, row['id'], [])
                result.append(Node(id=row['id'], parent_id=row['parent_id'], title=row['title'], kind=row['kind'],
                    description=row['description'], path=json.loads(row['path_json']), status=row['status'],
                    source_url=row['source_url'], coverage_note=row['coverage_note'],
                    child_count=db.execute("SELECT count(*) FROM nodes WHERE parent_id=?", (row['id'],)).fetchone()[0],
                    chunk_count=db.execute("SELECT count(*) FROM chunks c WHERE "+where,params).fetchone()[0]))
            return result, rows[limit-1]['id'] if len(rows)>limit else None

    def preview(self, node_id, limit):
        with self.connection() as db:
            where, params = self.scope(db, node_id, [])
            return [self.chunk(row) for row in db.execute("SELECT c.* FROM chunks c WHERE "+where+" ORDER BY c.id LIMIT ?", [*params,limit])]

    @staticmethod
    def match_expression(query):
        # Escape tokens/quoted phrases; never execute user-provided FTS syntax.
        terms = [a or b for a,b in re.findall(r'"([^\"]+)"|(\w+(?:[-.]\w+)*)', query)]
        return ' OR '.join('"'+term.replace('"','""')+'"' for term in terms[:40])

    def lexical(self, request, limit=80):
        match = self.match_expression(request.query)
        with self.connection() as db:
            where, params = self.scope(db, request.scope_node_id, request.group_ids)
            if not match:
                return []
            rows = db.execute("SELECT c.* FROM chunks_fts JOIN chunks c ON c.rowid=chunks_fts.rowid WHERE chunks_fts MATCH ? AND "+where+" ORDER BY bm25(chunks_fts),c.id LIMIT ?", [match,*params,limit]).fetchall()
            return [self.chunk(row) for row in rows]

    def eligible_count(self, request):
        with self.connection() as db:
            where, params = self.scope(db, request.scope_node_id, request.group_ids)
            return db.execute("SELECT count(*) FROM chunks c WHERE "+where,params).fetchone()[0]

    def exact(self, request, vector, model, config_id, limit=80, metrics=None):
        query = np.asarray(vector, dtype=np.float32).reshape(-1)
        norm = np.linalg.norm(query)
        if not np.isfinite(query).all() or not np.isfinite(norm) or norm == 0:
            raise ValueError("The embedding model returned an invalid query vector.")
        query /= norm
        best=[]
        with self.connection() as db:
            where, params = self.scope(db, request.scope_node_id, request.group_ids)
            cursor = db.execute("SELECT c.id,e.vector,e.dimensions,e.model,e.config_id FROM chunks c JOIN embeddings e ON e.chunk_id=c.id WHERE "+where,params)
            count=0
            while rows := cursor.fetchmany(1000):
                matrix=[]
                for row in rows:
                    if row['dimensions'] != len(query) or row['model'] != model or row['config_id'] != config_id:
                        raise ValueError("Embedding configuration changed. Rebuild document embeddings and map coordinates.")
                    values=np.frombuffer(row['vector'],dtype='<f4')
                    if len(values)!=len(query) or not np.isfinite(values).all() or np.linalg.norm(values)==0:
                        raise ValueError("An indexed embedding is invalid. Ask your coding agent to repair the index.")
                    matrix.append(values)
                batch=np.stack(matrix);batch/=np.linalg.norm(batch,axis=1,keepdims=True)
                for row, score in zip(rows,batch @ query):
                    item=(float(score),row['id']);count+=1
                    if len(best)<limit: heapq.heappush(best,item)
                    elif item>best[0]: heapq.heapreplace(best,item)
            if not count:
                raise ValueError("No compatible document embeddings are indexed. Use Keyword mode or ask your coding agent to finish indexing.")
        if metrics is not None:
            metrics.update(scored_vectors=count, dimensions=len(query))
        return [self.get_chunk(chunk_id) for _,chunk_id in sorted(best,reverse=True)]

    def map_page(self, request, cursor, limit, config_id, model, search_ids=None):
        with self.connection() as db:
            where, params = self.scope(db, request.scope_node_id, request.group_ids)
            group_where,group_params=self.scope(db,request.scope_node_id,[])
            groups=[dict(row) for row in db.execute("SELECT DISTINCT g.id,g.title FROM groups g JOIN chunks c ON c.group_id=g.id WHERE "+group_where+" ORDER BY g.id",group_params)]
            if search_ids is not None:
                if not search_ids: return [],groups,0,None
                where += " AND c.id IN ("+','.join('?' for _ in search_ids)+')';params.extend(search_ids)
            # A rebuilt embedding configuration must not show stale coordinates.
            base=" FROM map_points p JOIN chunks c ON c.id=p.chunk_id JOIN embeddings e ON e.chunk_id=c.id WHERE "+where+" AND p.embedding_config_id=? AND e.config_id=p.embedding_config_id AND e.model=?"
            params.extend([config_id, model])
            total=db.execute("SELECT count(*)"+base,params).fetchone()[0]
            rows=db.execute("SELECT p.id,p.x,p.y,c.id AS chunk_id,c.node_id,c.title,c.path_json,c.group_id"+base+" AND p.id>? ORDER BY p.id LIMIT ?",[*params,cursor or '',limit+1]).fetchall()
            points=[]
            for row in rows[:limit]:
                point=dict(row);point['path']=json.loads(point.pop('path_json'));points.append(point)
            return points,groups,total,rows[limit-1]['id'] if len(rows)>limit else None

    def issues(self):
        with self.connection() as db:
            rows=db.execute("SELECT i.*,n.title AS source_title,n.path_json FROM ingestion_issues i LEFT JOIN nodes n ON n.id=i.node_id ORDER BY i.id").fetchall()
            result=[]
            for row in rows:
                item=dict(row);item.pop('resolution');item['path']=json.loads(item.pop('path_json') or '[]');result.append(item)
            return result
