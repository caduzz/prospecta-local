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
    with TestClient(module.app) as client:
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


def test_agent_saves_only_sourced_records(client, monkeypatch):
    configure(client)
    async def fake(*args, **kwargs):
        return json.dumps({'leads': [{'name': 'Empresa real', 'website': 'https://example.com', 'source_urls': ['https://example.com']}, {'name': 'Sem fonte', 'source_urls': ['https://invented.test']}]}), [{'url': 'https://example.com', 'title': 'Site'}], {}, ''
    monkeypatch.setattr(module, 'generate', fake)
    with module.db() as c:
        run_id = c.execute("INSERT INTO runs (status) VALUES ('executando')").lastrowid
    asyncio.run(module.prospect(run_id, module.settings(), module.Campaign(segment='Clínicas', location='Salvador')))
    assert len(client.get('/api/leads').json()) == 1
    assert client.get('/api/runs').json()[0]['status'] == 'concluído'
    asyncio.run(module.prospect(run_id, module.settings(), module.Campaign(segment='Clínicas', location='Salvador')))
    assert len(client.get('/api/leads').json()) == 1


def test_missing_key_and_limit(client):
    campaign = {'segment': 'Clínicas', 'location': 'Salvador'}
    assert client.post('/api/runs', json=campaign, headers=HEADERS).status_code == 400
    configure(client)
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


def test_research_then_extraction(client, monkeypatch):
    configure(client)
    calls = []
    async def fake(s, prompt, search=False):
        calls.append((prompt, search))
        if search:
            return 'Empresa real: exemplo.com', [{'url': 'https://example.com', 'title': 'Site'}], {'totalTokenCount': 10}, ''
        return json.dumps({'leads':[{'name':'Empresa real','source_urls':['https://example.com']}]}), [], {'totalTokenCount': 5}, ''
    monkeypatch.setattr(module, 'generate', fake)
    with module.db() as c:
        run_id = c.execute("INSERT INTO runs (status) VALUES ('executando')").lastrowid
    asyncio.run(module.prospect(run_id, module.settings(), module.Campaign(segment='Academias',location='Petrolina')))
    assert [c[1] for c in calls] == [True, False]
    assert 'https://example.com' in calls[1][0]
    assert len(client.get('/api/leads').json()) == 1
    assert client.get('/api/runs').json()[0]['usage']['total_tokens'] == 15


def test_no_sources_is_empty_result(client, monkeypatch):
    configure(client)
    async def fake(*args, **kwargs):
        return 'Nenhuma evidência', [], {'totalTokenCount': 8}, ''
    monkeypatch.setattr(module, 'generate', fake)
    with module.db() as c:
        run_id = c.execute("INSERT INTO runs (status) VALUES ('executando')").lastrowid
    asyncio.run(module.prospect(run_id, module.settings(), module.Campaign(segment='Academias',location='Petrolina')))
    run = client.get('/api/runs').json()[0]
    assert run['status'] == 'sem resultados'
    assert run['usage']['totalTokenCount'] == 8
    assert client.get('/api/leads').json() == []
