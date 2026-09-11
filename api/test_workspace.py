"""Database regressions. Set XM_TEST_DATABASE_URL to an isolated PostgreSQL DB."""
import os
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch


def connect_test_db():
    import psycopg
    from psycopg.rows import dict_row
    return psycopg.connect(os.environ['XM_TEST_DATABASE_URL'], row_factory=dict_row)


@unittest.skipUnless(os.getenv('XM_TEST_DATABASE_URL'), 'requires isolated XM_TEST_DATABASE_URL')
class WorkspaceDatabaseRegression(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import workspace
        cls.module = workspace
        cls.patch = patch.object(workspace, 'connect', connect_test_db)
        cls.patch.start()
        cls.job = uuid.uuid4()
        cls.tag = 'group-test-' + str(cls.job)
        with connect_test_db() as conn:
            conn.execute(Path(__file__).with_name('schema.sql').read_text())
            conn.execute("INSERT INTO xm.imports(id,agent_name,file_name,file_path,file_sha256) VALUES(%s,%s,'test','test',%s)", (cls.job,cls.tag,cls.tag))
            for index in range(205):
                for copy in range(2):
                    cls.add(conn, cls.tag+' buyer '+str(index), 'buyer_request', copy)
            cls.property_ids = [cls.add(conn, cls.tag+' property', 'property_listing', copy) for copy in range(2)]
            buyers = conn.execute("SELECT id FROM xm.documents WHERE import_id=%s AND normalized_text=%s ORDER BY id", (cls.job,cls.tag+' buyer 0')).fetchall()
            for buyer in buyers:
                for target in cls.property_ids:
                    conn.execute('INSERT INTO xm.matches(id,buyer_request_id,property_listing_id,score) VALUES(%s,%s,%s,90)', (uuid.uuid4(),buyer['id'],target))
            conn.commit()

    @classmethod
    def add(cls, conn, text, kind, copy):
        raw, doc = uuid.uuid4(),uuid.uuid4()
        conn.execute("""INSERT INTO xm.raw_messages(id,import_id,agent_name,chat_id,chat_name,message_position,sent_at,raw_text,message_hash,classification)
         VALUES(%s,%s,%s,%s,'test',%s,%s,%s,%s,%s)""", (raw,cls.job,cls.tag,str(raw),copy,'2026-09-0'+str(copy+1),text,str(raw),kind))
        conn.execute("""INSERT INTO xm.documents(id,raw_message_id,import_id,agent_name,document_type,normalized_text)
         VALUES(%s,%s,%s,%s,%s,%s)""",(doc,raw,cls.job,cls.tag,kind,text))
        return doc

    @classmethod
    def tearDownClass(cls):
        with connect_test_db() as conn:
            conn.execute('DELETE FROM xm.raw_messages WHERE import_id=%s',(cls.job,))
            conn.execute('DELETE FROM xm.imports WHERE id=%s',(cls.job,))
            conn.commit()
        cls.patch.stop()

    def test_group_before_pagination(self):
        first = self.module.workspace(search=self.tag)
        second = self.module.workspace(search=self.tag, offset=200)
        self.assertEqual((len(first['rows']),len(second['rows'])),(200,5))
        self.assertTrue(first['has_more'])
        self.assertFalse(second['has_more'])
        rows=first['rows']+second['rows']
        self.assertEqual(len({r['raw_text'] for r in rows}),205)
        self.assertTrue(all(r['duplicate_count']==2 for r in rows))

    def test_reverse_recommendations_and_counts(self):
        sources=self.module.workspace(direction='property',search=self.tag)['rows']
        self.assertEqual(len(sources),1)
        source=sources[0]
        self.assertEqual(source['duplicate_count'],2)
        targets=self.module.recommendations(self.module.Batch(direction='property',ids=[source['id']]))['groups'][0]['recommendations']
        self.assertEqual(len(targets),source['match_count'])
        self.assertEqual(len({r['raw_text'] for r in targets}),len(targets))

    def test_filtered_copy_preserves_group_matches(self):
        sources = self.module.workspace(search=self.tag,statuses='hot',date_from='2026-09-02')['rows']
        self.assertEqual(len(sources),1)
        for source in sources:
            targets=self.module.recommendations(self.module.Batch(ids=[source['id']]))['groups'][0]['recommendations']
            self.assertEqual(source['match_count'],len(targets))
            self.assertEqual(source['duplicate_count'],1)
            self.assertEqual(len(targets),1)

    def test_different_signature_is_not_merged(self):
        values=[{'id':uuid.uuid4(),'raw_text':'same stock Contact A'}, {'id':uuid.uuid4(),'raw_text':'same stock Contact B'}]
        self.assertEqual(len(self.module.group_identical(values)),2)

    def test_cached_workspace_equivalent_to_uncached(self):
        from workspace_cache import refresh_workspace_cache
        cases=[dict(search=self.tag),dict(search=self.tag,offset=200),
               dict(search=self.tag,statuses='hot'),dict(direction='property',search=self.tag),
               dict(search=self.tag,date_from='2026-09-01',date_to='2026-09-01')]
        baseline=[self.module.workspace(**args) for args in cases]
        calendar=self.module.workspace_dates('property','2026-09-01','2026-10-01')
        with connect_test_db() as conn:
            refresh_workspace_cache(conn)
            conn.commit()
        try:
            for args,expected in zip(cases,baseline):
                actual=self.module.workspace(**args)
                self.assertEqual(actual['has_more'],expected['has_more'])
                fields=['id','raw_text','hot_count','warm_count','match_count','duplicate_count']
                self.assertEqual([[r[k] for k in fields] for r in actual['rows']],[[r[k] for k in fields] for r in expected['rows']])
            self.test_reverse_recommendations_and_counts()
            self.assertEqual(self.module.workspace_dates('property','2026-09-01','2026-10-01'),calendar)
        finally:
            with connect_test_db() as conn:
                conn.execute('DELETE FROM xm.workspace_cache_state')
                conn.commit()


if __name__ == '__main__': unittest.main()
