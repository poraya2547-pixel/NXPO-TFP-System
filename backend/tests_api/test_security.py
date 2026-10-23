"""Step 8: session expiry, cookie policy and request boundaries (isolated test DB only)."""
import pytest

from app import db
from conftest import ORIGIN, find, post_event


@pytest.mark.parametrize("expiry", ["absolute", "idle"])
def test_expired_session_cannot_act_or_download(client, fresh_db, expiry):
    view = client.get('/api/v1/view').json()
    old = client.cookies.get('tfp_session')
    with db.tx(fresh_db) as conn:
        sid = conn.execute('SELECT id FROM sessions WHERE token_hash = %s', (db._hash(old),)).fetchone()[0]
    ref = db.PostgresStore(fresh_db).put_download(sid, b'private test content', 'test.txt', 'text/plain')
    assert client.get('/api/v1/downloads/' + ref).status_code == 200
    with db.tx(fresh_db) as conn:
        if expiry == 'absolute':
            conn.execute("UPDATE sessions SET expires_at = now() - interval '1 minute' WHERE id = %s", (sid,))
        else:
            conn.execute("UPDATE sessions SET last_seen = now() - interval '100 days' WHERE id = %s", (sid,))
    assert post_event(client, view['csrf_token'], trigger='pick_role_visitor').status_code == 403
    assert client.get('/api/v1/downloads/' + ref).status_code == 404
    assert client.get('/api/v1/pending').json() == {'pending': False, 'status': None}
    new = client.get('/api/v1/view')
    assert client.cookies.get('tfp_session') != old
    assert find(new.json(), type='button', id='pick_role_visitor')
    assert client.get('/api/v1/downloads/' + ref).status_code == 404


def test_https_cookie_is_secure_host_only(client, monkeypatch):
    monkeypatch.setenv('TFP_COOKIE_SECURE', '1')
    cookie = client.get('/api/v1/view').headers['set-cookie'].lower()
    assert 'secure' in cookie and 'httponly' in cookie and 'samesite=lax' in cookie
    assert 'domain=' not in cookie and 'path=/' in cookie


def test_oversized_event_is_rejected_before_processing(client):
    csrf = client.get('/api/v1/view').json()['csrf_token']
    response = client.post('/api/v1/events', content=b'x' * 65537,
                           headers={'Origin': ORIGIN, 'X-CSRF-Token': csrf, 'Content-Type': 'application/json'})
    assert response.status_code == 413


def test_asset_and_download_paths_do_not_expose_files(client):
    client.get('/api/v1/view')
    for path in ['/api/v1/assets/secrets.toml', '/api/v1/downloads/secrets.toml',
                 '/api/v1/assets/%2e%2e%2fconfig.py', '/api/v1/downloads/%2e%2e%2fconfig.py']:
        response = client.get(path)
        assert response.status_code == 404
        assert 'GEMINI_API_KEY' not in response.text and 'Traceback' not in response.text
