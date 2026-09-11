"""Rebuild extracted documents from original bubbles, preserving document IDs."""
import json
import uuid
from db import connect
from parser import parse_message
from embedding import embed
from qdrant import upsert, _request, COLLECTION


def glossary_values(conn):
    return {r['alias']: r['canonical'] for r in conn.execute('SELECT * FROM xm.glossary').fetchall()}


def reindex_documents():
    with connect() as conn:
        # Serialize maintenance with imports and other recomputations.
        conn.execute('SELECT pg_advisory_xact_lock(9042026)')
        glossary = glossary_values(conn)
        rows = conn.execute("SELECT r.*, d.id document_id, d.qdrant_point_id FROM xm.raw_messages r LEFT JOIN xm.documents d ON d.raw_message_id=r.id WHERE r.company_id='xm' AND r.duplicate_of IS NULL ORDER BY r.id").fetchall()
        batch = []
        parsed_cache = {}
        with conn.pipeline() as pipeline:
            for row_number,row in enumerate(rows,1):
                cache_key=(row['raw_text'],row['author'])
                if cache_key not in parsed_cache: parsed_cache[cache_key]=parse_message(*cache_key,glossary)
                parsed=parsed_cache[cache_key]
                values = parsed.dict()
                conn.execute('UPDATE xm.raw_messages SET classification=%s, confidence=%s, extracted=%s::jsonb WHERE id=%s', (parsed.classification, parsed.confidence, json.dumps(values), row['id']))
                if parsed.classification == 'ignored':
                    if row['document_id']:
                        conn.execute('UPDATE xm.documents SET active=false WHERE id=%s', (row['document_id'],))
                        if row['qdrant_point_id']:
                            _request('POST', f'/collections/{COLLECTION}/points/payload?wait=true', {'payload':{'active':False},'points':[str(row['qdrant_point_id'])]})
                    continue
                doc_id = row['document_id'] or uuid.uuid4()
                point_id = row['qdrant_point_id'] or uuid.uuid5(uuid.NAMESPACE_URL, f'xm:{doc_id}')
                values['document_type'] = values.pop('classification')
                values['extraction_confidence'] = values.pop('confidence')
                values['primary_category'] = parsed.categories[0] if parsed.categories else None
                values['review_status'] = 'review' if parsed.confidence < .7 or not parsed.categories or len(parsed.categories) > 2 else 'auto'
                values.update(active=True, qdrant_point_id=point_id)
                # Column names are fixed ParsedDocument fields, never user input.
                if row['document_id']:
                    conn.execute('UPDATE xm.documents SET '+ ','.join(f'{key}=%s' for key in values) + ',updated_at=now() WHERE id=%s', (*values.values(), doc_id))
                else:
                    values.update(id=doc_id, raw_message_id=row['id'], import_id=row['import_id'], agent_name=row['agent_name'])
                    conn.execute('INSERT INTO xm.documents ('+','.join(values)+') VALUES ('+','.join(['%s']*len(values))+')', tuple(values.values()))
                batch.append({'id': str(point_id), 'vector': embed(parsed.normalized_text), 'payload': {'company_id':'xm','postgres_id':str(doc_id),'document_type':parsed.classification,'agent_name':row['agent_name'],'transaction_type':parsed.transaction_type,'categories':parsed.categories,'locations':parsed.locations,'active':True}})
                if row_number % 2000 == 0: print(f'Reindex {row_number}/{len(rows)} messages',flush=True)
                if len(batch) >= 128:
                    pipeline.sync()
                    upsert(batch)
                    batch=[]
        if batch:
            upsert(batch)
        conn.commit()
        return len(rows)
