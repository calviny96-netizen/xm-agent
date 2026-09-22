"""Access policy and account lifecycle regressions; DB tests use an isolated DB."""
import asyncio
import json
import os
import unittest
import uuid
from unittest.mock import patch

from fastapi import HTTPException, Response
from starlette.requests import Request
from search_terms import normalize_terms, search_filter


def request(path='/', method='GET', cookie=''):
    return Request({'type': 'http', 'path': path, 'method': method,
                    'headers': [(b'cookie', cookie.encode())], 'query_string': b''})


class AccessPolicyTests(unittest.TestCase):
    def check(self, user, path, method='GET'):
        from app import require_login
        async def next_handler(_request):
            return Response(status_code=204)
        with patch('app.current_user', return_value=user):
            return asyncio.run(require_login(request(path, method), next_handler)).status_code

    def test_user_cannot_write_settings_or_manage_accounts(self):
        user = {'id':uuid.UUID(int=1), 'workspace_id':'xm-test', 'role': 'user', 'is_locked': False}
        for path, method in [('/settings','PUT'),('/glossary','PUT'),('/search-default','PUT'),
                             ('/imports','POST'),('/index/recompute','POST'),('/matches/recompute','POST'),
                             ('/locations/import','POST'),('/auth/users','GET'),('/auth/users/','POST'),
                             ('/auth/users/123','PUT')]:
            with self.subTest(path=path):
                self.assertEqual(self.check(user, path, method), 403)
                self.assertEqual(self.check({'id':uuid.UUID(int=1),'workspace_id':'xm','role':'admin','is_locked':False}, path, method), 204)

    def test_active_user_can_read_and_match(self):
        user = {'id':uuid.UUID(int=1),'workspace_id':'xm-test','role':'user','is_locked':False}
        for path, method in [('/settings','GET'),('/search-default','GET'),('/workspace','GET'),
                             ('/workspace/recommendations','POST'),('/export/pdf','POST'),('/preferences','PUT')]:
            self.assertEqual(self.check(user,path,method),204)

    def test_locked_account_cannot_access_data_even_as_admin(self):
        for role in ('admin','user'):
            user = {'id':uuid.UUID(int=1),'workspace_id':'xm-test','role':role,'is_locked':True}
            for path, method in [('/stats','GET'),('/settings','GET'),('/workspace','GET'),
                                 ('/workspace/recommendations','POST'),('/export/pdf','POST'),('/auth/users','GET')]:
                self.assertEqual(self.check(user,path,method),403)
            self.assertEqual(self.check(user,'/auth/me'),204)
            self.assertEqual(self.check(user,'/auth/logout','POST'),204)
        self.assertEqual(self.check(None,'/workspace'),401)

    def test_multi_phrase_validation_and_literal_wildcards(self):
        self.assertEqual(normalize_terms(' XM Darmo, XM Citraland\nXM Darmo;;'), ['XM Darmo','XM Citraland'])
        self.assertEqual(search_filter('100%_sale')[1][0], [r'%100\%\_sale%'])
        with self.assertRaises(HTTPException): normalize_terms(['x'*201])
        with self.assertRaises(HTTPException): normalize_terms([str(i) for i in range(21)])


@unittest.skipUnless(os.getenv('XM_TEST_DATABASE_URL'), 'requires isolated XM_TEST_DATABASE_URL')
class AccountDatabaseTests(unittest.TestCase):
    def setUp(self):
        import auth
        import workspace
        from test_workspace import connect_test_db
        from pathlib import Path
        self.auth, self.workspace, self.connect = auth, workspace, connect_test_db
        self.patches = [patch.object(module, 'connect', connect_test_db) for module in (auth,workspace)]
        for p in self.patches: p.start(); self.addCleanup(p.stop)
        with self.connect() as conn:
            conn.execute(Path(__file__).with_name('schema.sql').read_text())
        self.email = 'test-' + uuid.uuid4().hex + '@example.com'
        self.addCleanup(self.cleanup)

    def cleanup(self):
        with self.connect() as conn:
            conn.execute("DELETE FROM xm.users WHERE email LIKE 'test-%@example.com'")

    def login(self, email, password):
        response = Response()
        user = self.auth.login(self.auth.LoginRequest(email=email,password=password),response)
        cookie = response.headers['set-cookie'].split(';')[0]
        return user, request(cookie=cookie)

    def test_create_edit_lock_unlock_and_password_reset(self):
        a = self.auth
        user = a.create_user(a.CreateUser(email=self.email,display_name='Test Agent',password='test-pass-123'))
        self.assertEqual(user['role'],'user')
        self.assertNotIn('password_hash',user)
        with self.assertRaises(HTTPException) as duplicate:
            a.create_user(a.CreateUser(email=self.email,display_name='Duplicate',password='test-pass-123'))
        self.assertEqual(duplicate.exception.status_code,409)
        logged, session = self.login(self.email,'test-pass-123')
        self.assertFalse(logged['is_locked'])
        a.update_user(user['id'],a.UpdateUser(email=self.email,display_name='Test Agent',is_locked=True))
        self.assertTrue(a.current_user(session)['is_locked'])
        self.assertTrue(self.login(self.email,'test-pass-123')[0]['is_locked'])
        a.update_user(user['id'],a.UpdateUser(email=self.email,display_name='Test Agent',is_locked=False))
        self.assertFalse(a.current_user(session)['is_locked'])
        new_email = 'test-' + uuid.uuid4().hex + '@example.com'
        a.update_user(user['id'],a.UpdateUser(email=new_email,display_name='Updated',password='new-pass-456'))
        self.assertIsNone(a.current_user(session))
        with self.assertRaises(HTTPException): self.login(self.email,'test-pass-123')
        self.assertEqual(self.login(new_email,'new-pass-456')[0]['display_name'],'Updated')

    def test_admin_migration_idempotent(self):
        a = self.auth
        a.create_user(a.CreateUser(email=self.email,display_name='Legacy',password='old-pass-123'))
        with patch.dict(os.environ,{'XM_ADMIN_EMAIL':self.email,'XM_ADMIN_PASSWORD':'secret123'}):
            a.seed_admin()
            user, session = self.login(self.email,'secret123')
            self.assertEqual(user['role'],'admin')
            a.seed_admin()
            self.assertIsNotNone(a.current_user(session))
            with self.assertRaises(HTTPException):
                a.update_user(user['id'],a.UpdateUser(email=self.email,display_name='Admin',is_locked=True))

    def test_search_defaults_shared_and_persisted(self):
        w = self.workspace
        original = w.get_search_default()
        try:
            saved = w.save_search_default(w.SearchDefault(search='XM Darmo\nXM Citraland, Pakuwon'))
            self.assertEqual(saved['terms'], ['XM Darmo','XM Citraland','Pakuwon'])
            self.assertEqual(w.get_search_default(), saved)
            with self.assertRaises(HTTPException): w.save_search_default(w.SearchDefault(search='  , '))
            self.assertEqual(w.get_search_default(), saved)
        finally:
            w.save_search_default(w.SearchDefault(terms=original['terms']))


if __name__ == '__main__': unittest.main()
