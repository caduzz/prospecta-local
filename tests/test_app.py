import asyncio
import json

import httpx
import pytest
from fastapi.testclient import TestClient

import app as module

HEADERS = {'X-Prospecta': 'local'}


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(module, 'DATA', tmp_path)
    monkeypatch.setattr(module, 'WORKER', False)
    with TestClient(module.app) as client:
        client.post('/api/auth/setup', json={'name': 'Admin', 'email': 'admin@test.dev', 'password': 'senha-forte-1'}, headers=HEADERS)
        yield client


def configure(client, provider='gemini'):
    data = module.DEFAULTS | {'provider': provider, 'openai_key': 'openai-secret-test', 'gemini_key': 'gemini-secret-test', 'offers': 'Software para clínicas'}
    response = client.put('/api/settings', json=data, headers=HEADERS)
    assert response.status_code == 200
    return response.json()


def test_keys_switch_preserve_remove_and_encryption(client):
    s = configure(client)
    assert s['gemini_configured'] and s['openai_configured']
    assert 'secret-test' not in json.dumps(s)
    with module.db() as c:
        stored = c.execute('SELECT value FROM settings').fetchone()[0]
        assert 'secret-test' not in stored
    s['provider'] = 'openai'
    s['openai_key'] = ''
    s['gemini_key'] = ''
    r = client.put('/api/settings', json=s, headers=HEADERS).json()
    assert r['provider'] == 'openai' and r['openai_configured'] and r['gemini_configured']
    r = client.put('/api/settings', json=r | {'remove_openai': True}, headers=HEADERS).json()
    assert not r['openai_configured'] and r['gemini_configured']


def test_origin_and_host_protection(client):
    assert client.put('/api/settings', json=module.DEFAULTS).status_code == 403
    assert client.put('/api/settings', json=module.DEFAULTS, headers=HEADERS | {'Origin': 'https://evil.test'}).status_code == 403
    assert client.get('/api/settings', headers={'Host': 'evil.test'}).status_code == 400


def test_lead_dedup_and_stage(client):
    lead = {'name': 'Empresa', 'website': 'https://www.example.com/'}
    assert client.post('/api/leads', json=lead, headers=HEADERS).status_code == 200
    assert client.post('/api/leads', json=lead | {'website': 'https://example.com/contato'}, headers=HEADERS).status_code == 409
    lead_id = client.get('/api/leads').json()[0]['id']
    assert client.patch(f'/api/leads/{lead_id}', json={'stage': 'Ganho'}, headers=HEADERS).status_code == 200
    assert client.get('/api/leads').json()[0]['stage'] == 'Ganho'
    assert client.post('/api/leads', json=lead | {'website': 'javascript:alert(1)'}, headers=HEADERS).status_code == 400


@pytest.mark.parametrize('provider', ['openai', 'gemini'])
def test_provider_requests_and_parsing(client, monkeypatch, provider):
    configure(client, provider)
    calls = []
    real_client = httpx.AsyncClient
    def handler(request):
        calls.append(request)
        body = json.loads(request.content)
        if provider == 'openai':
            assert request.headers['Authorization'] == 'Bearer openai-secret-test'
            assert body['tools'] == [{'type': 'web_search'}]
            return httpx.Response(200, json={'output': [{'type': 'message', 'content': [{'type': 'output_text', 'text': '{"leads":[]}', 'annotations': [{'type': 'url_citation', 'url': 'https://example.com', 'title': 'Fonte'}]}]}], 'usage': {'total_tokens': 10}})
        assert request.headers['x-goog-api-key'] == 'gemini-secret-test'
        assert body['tools'] == [{'google_search': {}}]
        return httpx.Response(200, json={'candidates': [{'content': {'parts': [{'text': '{"leads":[]}'}]}, 'groundingMetadata': {'groundingChunks': [{'web': {'uri': 'https://example.com', 'title': 'Fonte'}}]}}], 'usageMetadata': {'totalTokenCount': 10}})
    monkeypatch.setattr(module.httpx, 'AsyncClient', lambda **kwargs: real_client(transport=httpx.MockTransport(handler), **kwargs))
    text, sources, usage, _ = asyncio.run(module.generate(module.settings(), 'test', True))
    assert json.loads(text) == {'leads': []}
    assert sources[0]['url'] == 'https://example.com'
    assert len(calls) == 1


def test_missing_key_and_limit(client):
    campaign = {'segment': 'Clínicas', 'location': 'Salvador'}
    assert client.post('/api/runs', json=campaign, headers=HEADERS).status_code == 400
    configure(client)
    client.put('/api/settings', json=client.get('/api/settings').json() | {'places_key': 'places-test'}, headers=HEADERS)
    with module.db() as c:
        for _ in range(10):
            c.execute("INSERT INTO runs (status) VALUES ('erro')")
    assert client.post('/api/runs', json=campaign, headers=HEADERS).status_code == 429


def test_error_does_not_echo_provider_secrets(client, monkeypatch):
    configure(client)
    real_client = httpx.AsyncClient
    transport = httpx.MockTransport(lambda req: httpx.Response(401, json={'error': 'gemini-secret-test'}))
    monkeypatch.setattr(module.httpx, 'AsyncClient', lambda **kwargs: real_client(transport=transport, **kwargs))
    r = client.post('/api/test', json={}, headers=HEADERS)
    assert r.status_code == 400 and 'secret-test' not in r.text


def test_home(client):
    r = client.get('/')
    assert r.status_code == 200 and 'prospecta' in r.text
    assert client.get('/static/app.js').status_code == 200


def test_gemini_retired_model_message(client, monkeypatch):
    configure(client)
    real_client = httpx.AsyncClient
    transport = httpx.MockTransport(lambda req: httpx.Response(404, json={'error': {'message': 'This model is no longer available to new users. Please update your code to use models/gemini-3.5-flash-lite for the latest features'}}))
    monkeypatch.setattr(module.httpx, 'AsyncClient', lambda **kwargs: real_client(transport=transport, **kwargs))
    r = client.post('/api/test', json={}, headers=HEADERS)
    assert r.status_code == 400
    assert 'Google recomenda gemini-3.5-flash-lite' in r.json()['detail']


def test_stale_settings_cannot_restore_old_model(client):
    s = configure(client)
    r = client.put('/api/settings', json=s | {'gemini_model': 'gemini-3.5-flash-lite'}, headers=HEADERS)
    assert r.status_code == 200
    stale = client.put('/api/settings', json=s | {'gemini_model': 'gemini-2.5-flash-lite'}, headers=HEADERS)
    assert stale.status_code == 409
    assert client.get('/api/settings').json()['gemini_model'] == 'gemini-3.5-flash-lite'
