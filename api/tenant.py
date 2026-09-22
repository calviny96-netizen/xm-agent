"""Request/job-local workspace ownership. Never accept a workspace ID from a client."""
from contextlib import contextmanager
from contextvars import ContextVar

# Legacy command-line audit scripts operate on the original admin workspace.
_workspace = ContextVar('xm_workspace', default='xm')
_owner = ContextVar('xm_workspace_owner', default=None)


def workspace_id():
    return _workspace.get()


def owner_id():
    return _owner.get()


@contextmanager
def workspace_scope(workspace, owner=None):
    token = _workspace.set(workspace)
    owner_token = _owner.set(owner)
    try:
        yield
    finally:
        _owner.reset(owner_token)
        _workspace.reset(token)


def provision_workspace(conn, user_id, legacy=False):
    """One private namespace per account; new accounts never copy existing data."""
    workspace = 'xm' if legacy else 'xm-user-' + str(user_id)
    row = conn.execute('UPDATE xm.users SET workspace_id=coalesce(workspace_id,%s) WHERE id=%s RETURNING workspace_id',
                       (workspace, user_id)).fetchone()
    workspace = row['workspace_id']
    conn.execute('INSERT INTO xm.match_settings(company_id) VALUES(%s) ON CONFLICT DO NOTHING', (workspace,))
    conn.execute('INSERT INTO xm.app_preferences(company_id) VALUES(%s) ON CONFLICT DO NOTHING', (workspace,))
    return workspace
