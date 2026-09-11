"""Exact-text groups and pair counts, rebuilt atomically with matching results."""
import re


def refresh_workspace_cache(conn, company_id='xm'):
    conn.execute('DROP TABLE IF EXISTS pg_temp.xm_group_build')
    conn.execute('''CREATE TEMP TABLE xm_group_build ON COMMIT DROP AS
      SELECT d.id document_id,d.document_type,r.sent_at,
        first_value(d.id) OVER(PARTITION BY d.document_type,r.raw_text ORDER BY r.sent_at DESC NULLS LAST,d.id) group_id
      FROM xm.documents d JOIN xm.raw_messages r ON r.id=d.raw_message_id
      WHERE d.company_id=%s AND d.active''',(company_id,))
    conn.execute('DELETE FROM xm.group_matches WHERE company_id=%s',(company_id,))
    conn.execute('DELETE FROM xm.document_group_members WHERE company_id=%s',(company_id,))
    conn.execute('DELETE FROM xm.document_groups WHERE company_id=%s',(company_id,))
    conn.execute('''INSERT INTO xm.document_groups(group_id,company_id,document_type,duplicate_count,last_seen_at)
      SELECT group_id,%s,document_type,count(*),max(sent_at) FROM xm_group_build GROUP BY group_id,document_type''',(company_id,))
    conn.execute('''INSERT INTO xm.document_group_members(document_id,group_id,company_id)
      SELECT document_id,group_id,%s FROM xm_group_build''',(company_id,))
    conn.execute('''INSERT INTO xm.group_matches(company_id,buyer_group_id,property_group_id,match_id,score)
      SELECT DISTINCT ON (b.group_id,p.group_id) m.company_id,b.group_id,p.group_id,m.id,m.score
      FROM xm.matches m JOIN xm.document_group_members b ON b.document_id=m.buyer_request_id
      JOIN xm.document_group_members p ON p.document_id=m.property_listing_id
      WHERE m.company_id=%s AND m.score>=60 ORDER BY b.group_id,p.group_id,m.score DESC,m.id''',(company_id,))
    conn.execute('''UPDATE xm.document_groups g SET hot_count=c.hot,warm_count=c.warm
      FROM (SELECT group_id,count(*) FILTER(WHERE score>=80) hot,count(*) FILTER(WHERE score<80) warm
        FROM (SELECT buyer_group_id group_id,score FROM xm.group_matches WHERE company_id=%s
          UNION ALL SELECT property_group_id,score FROM xm.group_matches WHERE company_id=%s) pairs GROUP BY group_id) c
      WHERE g.group_id=c.group_id AND g.company_id=%s''',(company_id,company_id,company_id))
    conn.execute('''INSERT INTO xm.workspace_cache_state(company_id,refreshed_at) VALUES(%s,now())
      ON CONFLICT(company_id) DO UPDATE SET refreshed_at=excluded.refreshed_at''',(company_id,))
    conn.execute('ANALYZE xm.document_groups')
    conn.execute('ANALYZE xm.document_group_members')
    conn.execute('ANALYZE xm.group_matches')


def ready(conn):
    return bool(conn.execute("SELECT 1 FROM xm.workspace_cache_state WHERE company_id='xm'").fetchone())


def sources(conn, direction, search, phones, statuses, clause, date_params, offset):
    from parser import normalize_phone
    from fastapi import HTTPException
    kind='buyer_request' if direction=='buyer' else 'property_listing'
    params=[kind]
    filters=[];selected=set(statuses.split(','))
    if 'hot' in selected:filters.append('g.hot_count>0')
    if 'warm' in selected:filters.append('g.warm_count>0')
    if 'unmatched' in selected:filters.append('g.hot_count+g.warm_count=0')
    # No text equality or matching aggregation on the interactive read path.
    query='''WITH eligible AS (
      SELECT DISTINCT ON (g.group_id) d.id,g.group_id,r.sent_at,count(*) OVER(PARTITION BY g.group_id) duplicate_count
      FROM xm.document_groups g JOIN xm.document_group_members gm ON gm.group_id=g.group_id
      JOIN xm.documents d ON d.id=gm.document_id JOIN xm.raw_messages r ON r.id=d.raw_message_id
      WHERE g.company_id='xm' AND d.active AND g.document_type=%s AND ('''+(' OR '.join(filters) or 'false')+')'
    if search.strip():
        query+=" AND (d.normalized_text ILIKE %s OR coalesce(d.contact_name,'') ILIKE %s)"
        params+=['%'+search.strip()+'%']*2
    if phones.strip() and direction=='property':
        numbers=[normalize_phone(v) for v in re.split(r'[,;\n]+',phones) if v.strip()]
        if any(not n.startswith('628') or not 10<=len(n)<=15 for n in numbers):
            raise HTTPException(400,'Nomor tidak valid. Pisahkan beberapa nomor dengan koma atau baris baru.')
        query+=' AND (d.contact_phones && %s::text[] OR d.contact_phone=ANY(%s))';params += [numbers,numbers]
    query+=clause;params+=date_params
    query+=''' ORDER BY g.group_id,r.sent_at DESC NULLS LAST,d.id
      ), page AS (SELECT * FROM eligible ORDER BY sent_at DESC NULLS LAST,id LIMIT 201 OFFSET %s)
      SELECT d.*,r.raw_text,r.chat_name,r.sent_at,p.duplicate_count,g.last_seen_at,
        g.hot_count,g.warm_count,g.hot_count+g.warm_count match_count
      FROM page p JOIN xm.documents d ON d.id=p.id JOIN xm.raw_messages r ON r.id=d.raw_message_id
      JOIN xm.document_groups g ON g.group_id=p.group_id ORDER BY p.sent_at DESC NULLS LAST,p.id'''
    params.append(max(0,offset))
    rows=conn.execute(query,params).fetchall()
    return {'rows':rows[:200],'has_more':len(rows)>200}


def recommendations(conn, direction, ids):
    kind='buyer_request' if direction=='buyer' else 'property_listing'
    relation,other=('buyer_group_id','property_group_id') if direction=='buyer' else ('property_group_id','buyer_group_id')
    sources=conn.execute('''SELECT d.*,r.raw_text,r.chat_name,r.sent_at FROM xm.documents d
      JOIN xm.raw_messages r ON r.id=d.raw_message_id WHERE d.company_id='xm' AND d.active AND d.id=ANY(%s) AND d.document_type=%s''',(ids,kind)).fetchall()
    rows=conn.execute(f'''SELECT s.document_id source_id,m.score,m.explanation,m.id match_id,d.*,r.raw_text,r.chat_name,r.sent_at,g.duplicate_count,g.last_seen_at
      FROM xm.document_group_members s JOIN xm.group_matches gm ON gm.{relation}=s.group_id
      JOIN xm.matches m ON m.id=gm.match_id JOIN xm.document_groups g ON g.group_id=gm.{other}
      JOIN xm.documents d ON d.id=g.group_id JOIN xm.raw_messages r ON r.id=d.raw_message_id
      WHERE s.company_id='xm' AND s.document_id=ANY(%s) AND d.active
      ORDER BY m.score DESC,g.last_seen_at DESC NULLS LAST,d.id''',(ids,)).fetchall()
    return {'groups':[{'source':s,'recommendations':[r for r in rows if r['source_id']==s['id']]} for s in sources]}
