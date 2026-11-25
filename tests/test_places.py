import asyncio
import json
import sqlite3

import httpx
import pytest
from fastapi.testclient import TestClient

import app as module

HEADERS = {'X-Prospecta': 'local'}
ADMIN = {'name': 'Admin', 'email': 'admin@test.dev', 'password': 'senha-forte-1'}


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(module, 'DATA', tmp_path)
    monkeypatch.setattr(module, 'WORKER', False)
    with TestClient(module.app) as client:
        client.post('/api/auth/setup', json=ADMIN, headers=HEADERS)
        yield client


def configure(client, **extra):
    data = module.DEFAULTS | {'offers': 'Sistema de vendas pelo WhatsApp', 'places_key': 'places-secret-test'} | extra
    assert client.put('/api/settings', json=data | {'revision': client.get('/api/settings').json().get('revision', 0)}, headers=HEADERS).status_code == 200


def place(pid, name, phone=None, site='', city='Petrolina', status='OPERATIONAL'):
    phone = f"+55 87 9{int.from_bytes(pid.encode(), 'big') % 10 ** 8:08d}" if phone is None else phone
    return {'id': pid, 'displayName': {'text': name}, 'formattedAddress': f'Rua A, 10 - Centro, {city} - PE, 56300-000, Brasil', 'internationalPhoneNumber': phone,
            'websiteUri': site, 'businessStatus': status, 'googleMapsUri': f'https://maps.google.com/?cid={pid}', 'primaryType': 'liquor_store'}


def leads():
    with module.db() as c:
        return {row['name']: dict(row) for row in c.execute('SELECT * FROM leads')}


@pytest.mark.parametrize('phone,mobile', [
    ('5587992011147', True), ('+55 (87) 99201-1147', True), ('558738611234', False), ('5587386112345', False),
    ('5508001234567', False), ('', False), ('87992011147', False),
])
def test_mobile_vs_landline(phone, mobile):
    assert module.is_mobile(phone) is mobile
    assert module.is_mobile(module.clean_phone('(87) 99201-1147')) and not module.is_mobile(module.clean_phone('(87) 3861-1234'))


@pytest.mark.parametrize('signals,expected', [
    ({'site_nao_abre': True, 'sem_site': True, 'sem_https': True}, 'site_nao_abre'),
    ({'so_rede_social': True, 'sem_whatsapp_no_site': True}, 'so_rede_social'),
    ({'sem_whatsapp_no_site': True, 'nao_mobile': True, 'sem_https': True}, 'sem_whatsapp_no_site'),
    ({'nao_mobile': True, 'sem_https': True}, 'nao_mobile'),
    ({'sem_https': True}, 'sem_https'),
    ({}, None),
])
def test_main_signal_priority(signals, expected):
    assert module.main_signal(dict.fromkeys(module.SIGNALS, False) | signals) == expected


def test_diagnose_checks(monkeypatch):
    pages = {
        'https://ok.test/': (200, 'https://ok.test/', '<meta name="viewport" content="width=device-width"><a href="https://wa.me/55879">Zap</a>'),
        'https://plain.test/': (200, 'https://plain.test/', '<html>sem nada</html>'),
        'http://velho.test/': (200, 'http://velho.test/', '<meta name=viewport><a href="https://api.whatsapp.com/send?phone=1">'),
        'https://quebrado.test/': (500, 'https://quebrado.test/', ''),
    }

    async def fake_fetch(url):
        if url not in pages:
            return None
        status, final, html = pages[url]
        return httpx.Response(status, text=html, request=httpx.Request('GET', final))
    monkeypatch.setattr(module, 'fetch_site', fake_fetch)
    run = lambda url: {k for k, v in asyncio.run(module.diagnose(url)).items() if v}
    assert run('') == {'sem_site'}
    assert run('https://www.instagram.com/loja') == {'so_rede_social'}
    assert run('https://linktr.ee/loja') == {'so_rede_social'}
    assert run('https://quebrado.test/') == {'site_nao_abre'}
    assert run('https://naoexiste.test/') == {'site_nao_abre'}
    assert run('https://ok.test/') == set()
    assert run('https://plain.test/') == {'sem_whatsapp_no_site', 'nao_mobile'}
    assert run('http://velho.test/') == {'sem_https'}


def test_fetch_site_blocks_private_addresses():
    assert asyncio.run(module.fetch_site('http://127.0.0.1:8000/')) is None
    assert asyncio.run(module.fetch_site('http://192.168.0.1/')) is None
    assert asyncio.run(module.fetch_site('file:///etc/passwd')) is None


def test_places_search_filters_and_dedup(client, monkeypatch):
    configure(client, chains='Ambev\nAtacadão')
    pages = [
        ([place('p1', 'Distribuidora Sol', site='https://www.instagram.com/distsol'),
          place('p2', 'Bebidas Fixo', phone='+55 87 3861-1234'),
          place('p3', 'Depósito Fechado', status='CLOSED_PERMANENTLY'),
          place('p4', 'Sem Telefone', phone=''),
          place('p5', 'Ambev Revenda Petrolina'),
          place('p6', 'Rede Norte Petrolina', site='https://redenorte.com.br'),
          place('p7', 'Rede Norte Juazeiro', site='https://redenorte.com.br/juazeiro', city='Juazeiro')], 'TOKEN2'),
        ([place('p8', 'Distribuidora Lua', site='https://lua.com.br')], None),
    ]
    queries = []

    async def fake_search(s, query, page_token=None, page_size=20, fields=None):
        queries.append((query, page_token))
        return pages[len(queries) - 1]
    monkeypatch.setattr(module, 'places_search', fake_search)
    with module.db() as c:
        run_id = c.execute("INSERT INTO runs (status) VALUES ('executando')").lastrowid
    asyncio.run(module.prospect(run_id, module.settings(), module.Campaign(segment='distribuidora de bebidas', location='Petrolina', limit=60)))
    assert queries == [('distribuidora de bebidas em Petrolina', None), ('distribuidora de bebidas em Petrolina', 'TOKEN2')]
    saved = leads()
    assert set(saved) == {'Distribuidora Sol', 'Bebidas Fixo', 'Distribuidora Lua'}
    assert saved['Distribuidora Sol']['tem_whatsapp'] == 1 and saved['Distribuidora Sol']['instagram'] == 'distsol' and saved['Distribuidora Sol']['place_id'] == 'p1'
    assert (saved['Bebidas Fixo']['tem_whatsapp'], saved['Bebidas Fixo']['outreach']) == (0, 'Sem WhatsApp')
    assert saved['Distribuidora Lua']['location'] == 'Petrolina' and 'Centro' in saved['Distribuidora Lua']['address']
    run = client.get('/api/runs').json()[0]
    log = run['log']
    assert run['status'] == 'concluído' and run['count'] == 3
    assert (log['encontrados'], log['novos'], log['sem_whatsapp'], log['descartados']) == (8, 2, 1, 5)
    assert log['motivos'] == {'não está em funcionamento': 1, 'sem telefone': 1, 'rede/franquia': 3}
    # Segunda busca: os mesmos place_id não duplicam.
    queries.clear()
    with module.db() as c:
        run_id = c.execute("INSERT INTO runs (status) VALUES ('executando')").lastrowid
    asyncio.run(module.prospect(run_id, module.settings(), module.Campaign(segment='distribuidora de bebidas', location='Petrolina', limit=60)))
    assert len(leads()) == 3
    assert client.get('/api/runs').json()[0]['log']['duplicados'] == 3


def test_place_id_dedup_even_with_shared_social_site(client, monkeypatch):
    configure(client)

    async def fake_search(*args, **kwargs):
        return [place('a', 'Loja A', site='https://instagram.com/a'), place('b', 'Loja B', site='https://instagram.com/b'), place('a', 'Loja A de novo')], None
    monkeypatch.setattr(module, 'places_search', fake_search)
    with module.db() as c:
        run_id = c.execute("INSERT INTO runs (status) VALUES ('executando')").lastrowid
    asyncio.run(module.prospect(run_id, module.settings(), module.Campaign(segment='lojas', location='Petrolina')))
    assert set(leads()) == {'Loja A', 'Loja B'}


def test_places_error_reason(client, monkeypatch):
    configure(client)
    real_client = httpx.AsyncClient
    transport = httpx.MockTransport(lambda req: httpx.Response(403, json={'error': {'message': 'Places API (New) has not been used in project 123 before or it is disabled.'}}))
    monkeypatch.setattr(module.httpx, 'AsyncClient', lambda **kwargs: real_client(transport=transport, **kwargs))
    detail = client.post('/api/places/test', json={}, headers=HEADERS).json()['detail']
    assert 'Ative a API' in detail and 'has not been used' in detail and 'places-secret-test' not in detail


def test_places_request_shape(client, monkeypatch):
    configure(client)
    seen = {}
    real_client = httpx.AsyncClient

    def handler(request):
        seen['mask'] = request.headers['X-Goog-FieldMask']
        seen['key'] = request.headers['X-Goog-Api-Key']
        seen['body'] = json.loads(request.content)
        return httpx.Response(200, json={'places': [place('x', 'X')], 'nextPageToken': 'N'})
    monkeypatch.setattr(module.httpx, 'AsyncClient', lambda **kwargs: real_client(transport=httpx.MockTransport(handler), **kwargs))
    found, token = asyncio.run(module.places_search(module.settings(), 'bares em Petrolina', 'T1'))
    assert token == 'N' and found[0]['id'] == 'x'
    assert seen['key'] == 'places-secret-test'
    assert seen['mask'] == ','.join('places.' + f for f in module.PLACES_FIELDS) + ',nextPageToken'
    assert seen['body'] == {'textQuery': 'bares em Petrolina', 'languageCode': 'pt-BR', 'regionCode': 'BR', 'pageSize': 20, 'pageToken': 'T1'}


@pytest.mark.parametrize('text,ok', [
    ('Olá, tudo bem? Vi o negócio de vocês no Google Maps e reparei que o link leva só pro Instagram. Trabalho ajudando empresas a venderem mais pelo WhatsApp, posso te mostrar como?', True),
    ('Olá! Achei excelente o trabalho de vocês. Posso mostrar?', False),
    ('Olá! Vi as 5 estrelas de vocês no Google. Posso mostrar?', False),
    ('Olá! Podemos fazer uma reunião de 10 minutos?', False),
    ('Olá, tudo bem? ' + 'x' * 280 + '?', False),
    ('Olá\nlinha 2\nlinha 3?', False),
    ('Olá, tudo bem? Posso te mostrar.', False),
])
def test_message_validation(text, ok):
    assert (module.message_problems(text) == []) is ok


def test_draft_regenerates_once_then_falls_back(client, monkeypatch):
    configure(client, gemini_key='gemini-test', draft_mode='ia')
    lead = {'name': 'Distribuidora Sol', 'segment': 'bebidas', 'location': 'Petrolina', 'contact': 'Carlos Silva', 'sinal_principal': 'so_rede_social'}
    answers = ['Parabéns pelo trabalho incrível! Posso mostrar?', 'Olá, Carlos, tudo bem? Vi o negócio de vocês no Google Maps. Ajudo empresas a vender pelo WhatsApp, posso te mostrar?']
    prompts = []

    async def fake(s, prompt, search=False):
        prompts.append(prompt)
        return answers[len(prompts) - 1], [], {}, ''
    monkeypatch.setattr(module, 'generate', fake)
    text, origin = asyncio.run(module.write_draft(module.settings(), lead))
    assert origin == 'IA' and text.startswith('Olá, Carlos') and len(prompts) == 2
    assert '"sinal_principal": "o link do Google leva só para rede social"' in prompts[0] and 'rejeitada' in prompts[1]
    assert 'Google Maps' in prompts[0] and 'Sistema de vendas pelo WhatsApp' in prompts[0]
    answers[1] = 'Achei maravilhoso! Vamos marcar 15 minutos?'
    prompts.clear()
    text, origin = asyncio.run(module.write_draft(module.settings(), lead))
    assert origin.startswith('modelo fixo')
    assert text == 'Olá, Carlos, tudo bem? Vi o negócio de vocês no Google Maps e reparei que o link de vocês leva só pra rede social. Trabalho ajudando empresas a organizar e vender mais pelo WhatsApp, posso te mostrar como?'
    assert module.message_problems(text) == []


def test_enrichment_fills_diagnosis_and_draft(client, monkeypatch):
    configure(client, first_message='Olá, {saudacao}! Tudo bem? Falo com algum representante ou responsável pelo atendimento contábil da {empresa} aí de {cidade}?')
    with module.db() as c:
        c.execute("INSERT INTO leads (identity,name,segment,location,contact,website,phone,sources,place_id,tem_whatsapp) VALUES ('place:z','Bar Z','bares','Petrolina','','','5587992011147','[]','z',1)")

    async def no_fetch(url):
        return None
    monkeypatch.setattr(module, 'fetch_site', no_fetch)
    asyncio.run(module.enrich_once())
    asyncio.run(module.enrich_once())
    lead = leads()['Bar Z']
    assert lead['sinal_principal'] == 'sem_site' and json.loads(lead['diagnostico'])['sem_site']
    assert (lead['draft'], lead['draft_status']) == ('Olá, {saudacao}! Tudo bem? Falo com algum representante ou responsável pelo atendimento contábil da Bar Z aí de Petrolina?', 'modelo')
    card = next(l for l in client.get('/api/leads').json() if l['name'] == 'Bar Z')
    assert card['sinal_principal'] == 'sem_site'


def test_landline_leads_stay_out_of_whatsapp_dispatch(client):
    configure(client, evolution_instance='p', evolution_key='k')
    with module.db() as c:
        c.execute("INSERT INTO leads (identity,name,phone,draft,sources,tem_whatsapp,outreach) VALUES ('f','Fixo','558738611234','Oi?','[]',0,'Sem WhatsApp')")
        lead_id = c.execute("SELECT id FROM leads WHERE name='Fixo'").fetchone()[0]
    r = client.post('/api/dispatch', json={'lead_ids': [lead_id], 'channel': 'whatsapp'}, headers=HEADERS).json()
    assert r['queued'] == 0 and r['skipped'] == 1


def test_team_roles_and_signature(client, monkeypatch):
    assert client.post('/api/team', json={'name': 'João', 'email': 'joao@test.dev', 'password': 'senha-joao-1'}, headers=HEADERS).status_code == 200
    configure(client, evolution_instance='p', evolution_key='k')
    member = TestClient(module.app)
    assert member.get('/api/leads').status_code == 401
    assert member.post('/api/auth/login', json={'email': 'joao@test.dev', 'password': 'errada'}, headers=HEADERS).status_code == 401
    assert member.post('/api/auth/login', json={'email': 'JOAO@test.dev', 'password': 'senha-joao-1'}, headers=HEADERS).status_code == 200
    assert member.get('/api/auth/status').json()['user']['name'] == 'João'
    assert member.put('/api/settings', json=module.DEFAULTS, headers=HEADERS).status_code == 403
    assert member.get('/api/team').status_code == 403
    with module.db() as c:
        c.execute("INSERT INTO leads (identity,name,phone,draft,sources,tem_whatsapp) VALUES ('w','Loja W','5587992011147','Olá, tudo bem?','[]',1)")
        lead_id = c.execute("SELECT id FROM leads WHERE name='Loja W'").fetchone()[0]
    assert member.post('/api/dispatch', json={'lead_ids': [lead_id], 'channel': 'whatsapp'}, headers=HEADERS).json()['queued'] == 1
    sent = []

    async def fake_evolution(s, method, path, payload=None):
        if path == 'instance/connectionState':
            return {'instance': {'state': 'open'}}
        sent.append(payload['text'])
        return {'key': {'id': f'X{len(sent)}'}}
    monkeypatch.setattr(module, 'evolution', fake_evolution)
    monkeypatch.setattr(module, 'in_window', lambda s: True)
    asyncio.run(module.process_queue(module.settings()))
    assert sent == ['*João:*\nOlá, tudo bem?']
    with module.db() as c:
        assert c.execute('SELECT owner_id FROM leads WHERE id=?', (lead_id,)).fetchone()[0] is not None
        c.execute("UPDATE leads SET next_followup='2000-01-01 00:00:00' WHERE id=?", (lead_id,))
    module.schedule_followups(module.settings())
    with module.db() as c:
        c.execute("DELETE FROM kv WHERE key='next_send'")
    asyncio.run(module.process_queue(module.settings()))
    assert sent[1].startswith('*João:*\n')
    msgs = client.get(f'/api/leads/{lead_id}/messages').json()['messages']
    assert msgs[0]['user_name'] == 'João'
    # Desativar encerra a sessão do membro.
    joao = next(u for u in client.get('/api/team').json() if u['name'] == 'João')
    assert client.patch(f"/api/team/{joao['id']}", json={'active': False}, headers=HEADERS).status_code == 200
    assert member.get('/api/leads').status_code == 401


def test_last_admin_cannot_be_removed_and_setup_is_one_time(client):
    admin = client.get('/api/team').json()[0]
    assert client.patch(f"/api/team/{admin['id']}", json={'role': 'member'}, headers=HEADERS).status_code == 400
    assert client.patch(f"/api/team/{admin['id']}", json={'active': False}, headers=HEADERS).status_code == 400
    assert client.post('/api/auth/setup', json=ADMIN | {'email': 'outro@test.dev'}, headers=HEADERS).status_code == 409


def test_password_is_hashed_and_login_is_rate_limited(client, monkeypatch):
    monkeypatch.setattr(module, 'LOGIN_FAILURES', {})
    with module.db() as c:
        stored = c.execute('SELECT password FROM users').fetchone()[0]
    assert stored.startswith('scrypt$') and 'senha-forte-1' not in stored
    other = TestClient(module.app)
    for _ in range(5):
        assert other.post('/api/auth/login', json={'email': 'admin@test.dev', 'password': 'x'}, headers=HEADERS).status_code == 401
    assert other.post('/api/auth/login', json=ADMIN, headers=HEADERS).status_code == 429


def test_migration_keeps_existing_leads(tmp_path, monkeypatch):
    monkeypatch.setattr(module, 'DATA', tmp_path)
    monkeypatch.setattr(module, 'WORKER', False)
    conn = sqlite3.connect(tmp_path / 'prospecta.db')
    conn.executescript('''CREATE TABLE leads (id INTEGER PRIMARY KEY, identity TEXT UNIQUE, name TEXT, website TEXT, segment TEXT, location TEXT, contact TEXT, reason TEXT, draft TEXT, stage TEXT DEFAULT 'Novo', sources TEXT, created TEXT DEFAULT CURRENT_TIMESTAMP, phone TEXT DEFAULT '');
        INSERT INTO leads (identity,name,phone,sources) VALUES ('a','Celular','5587992011147','[]'), ('b','Fixo','558738611234','[]');''')
    conn.commit()
    conn.close()
    with TestClient(module.app):
        rows = leads()
    assert set(rows) == {'Celular', 'Fixo'}
    assert rows['Celular']['tem_whatsapp'] == 1 and rows['Fixo']['tem_whatsapp'] == 0
    assert {'place_id', 'diagnostico', 'sinal_principal', 'motivo_descarte', 'tem_whatsapp'} <= set(rows['Celular'])


def test_whatsapp_qr_flow(client, monkeypatch):
    configure(client, evolution_instance='prospecta', evolution_key='evo-k')
    calls = []
    state = {'value': 'connecting'}

    async def fake_evolution(s, method, path, payload=None):
        calls.append(path)
        if path == 'instance/connectionState':
            return {'instance': {'state': state['value']}}
        return {'base64': 'data:image/png;base64,AAAA', 'pairingCode': None}
    monkeypatch.setattr(module, 'evolution', fake_evolution)
    r = client.post('/api/whatsapp/connect', json={}, headers=HEADERS).json()
    assert r == {'state': 'connecting', 'qr': 'data:image/png;base64,AAAA'}
    state['value'] = 'open'
    assert client.get('/api/whatsapp/state').json() == {'state': 'open'}
    assert client.post('/api/whatsapp/connect', json={}, headers=HEADERS).json() == {'state': 'open'}
    assert "img-src 'self' data:" in client.get('/').headers['Content-Security-Policy']


def test_message_cannot_echo_prompt_fields():
    assert module.message_problems('Olá, tudo bem? Seus sistemas e serviços ajudam a vender mais?')
    assert module.message_problems('Olá, tudo bem? Vi o sinal_principal de vocês, posso mostrar?')


def test_admin_renames_member_and_signature_follows(client):
    client.post('/api/team', json={'name': 'Joao', 'email': 'joao2@test.dev', 'password': 'senha-joao-1'}, headers=HEADERS)
    joao = next(u for u in client.get('/api/team').json() if u['email'] == 'joao2@test.dev')
    assert client.patch(f"/api/team/{joao['id']}", json={'name': 'João Matheus'}, headers=HEADERS).status_code == 200
    assert client.patch(f"/api/team/{joao['id']}", json={'name': 'J'}, headers=HEADERS).status_code == 422
    assert next(u for u in client.get('/api/team').json() if u['id'] == joao['id'])['name'] == 'João Matheus'
    assert module.sign('Oi', 'whatsapp', joao['id']) == '*João Matheus:*\nOi'


def test_auto_dispatch_only_new_leads(client, monkeypatch):
    configure(client, evolution_instance='prospecta', evolution_key='evo-k')
    with module.db() as c:
        c.execute("INSERT INTO leads (identity,name,phone,draft,sources,tem_whatsapp,place_id,diagnostico,created) VALUES ('old','Antigo','5587992011147','Olá, tudo bem?','[]',1,'old','{}','2020-01-01 00:00:00')")
    s = client.get('/api/settings').json()
    r = client.put('/api/settings', json=s | {'auto_dispatch': True}, headers=HEADERS).json()
    assert r['auto_dispatch'] and r['auto_since']
    assert module.auto_dispatch(module.settings()) == 0

    async def fake_search(*args, **kwargs):
        return [place('n1', 'Nova Distribuidora'), place('n2', 'Fixo Novo', phone='+55 87 3861-1234')], None

    async def no_fetch(url):
        return None
    monkeypatch.setattr(module, 'places_search', fake_search)
    monkeypatch.setattr(module, 'fetch_site', no_fetch)
    with module.db() as c:
        admin_id = c.execute('SELECT id FROM users').fetchone()[0]
        run_id = c.execute("INSERT INTO runs (status,user_id) VALUES ('executando',?)", (admin_id,)).lastrowid
    asyncio.run(module.prospect(run_id, module.settings(), module.Campaign(segment='bebidas', location='Petrolina')))
    asyncio.run(module.enrich_once())
    asyncio.run(module.enrich_once())
    rows = leads()
    assert rows['Nova Distribuidora']['outreach'] == 'Para aprovar' and rows['Nova Distribuidora']['owner_id'] == admin_id
    assert rows['Antigo']['outreach'] == 'Não contatado' and rows['Fixo Novo']['outreach'] == 'Sem WhatsApp'
    with module.db() as c:
        assert c.execute("SELECT COUNT(*) FROM messages WHERE status='na fila'").fetchone()[0] == 0
    pending = client.get('/api/approvals').json()
    assert [(a['name'], a['user_name']) for a in pending] == [('Nova Distribuidora', 'Admin')]
    assert 'da Nova Distribuidora aí de Petrolina?' in pending[0]['preview'] and '{saudacao}' not in pending[0]['preview']
    assert client.get('/api/outreach').json()['approvals'] == 1
    # Nada sai antes da aprovação; aprovado, entra na fila normal.
    assert client.post('/api/approvals/approve', json={'ids': [pending[0]['id']]}, headers=HEADERS).status_code == 200
    with module.db() as c:
        assert tuple(c.execute("SELECT status, user_id FROM messages WHERE id=?", (pending[0]['id'],)).fetchone()) == ('na fila', admin_id)
    assert leads()['Nova Distribuidora']['outreach'] == 'Na fila'
    assert client.get('/api/outreach').json()['auto_dispatch'] is True


def test_auto_dispatch_off_by_default(client):
    assert client.get('/api/settings').json()['auto_dispatch'] is False
    assert module.auto_dispatch(module.settings()) == 0


@pytest.mark.parametrize('name,expected', [
    ('DISTRIBUIDORA DE BEBIDAS BIG BROTHER', 'Distribuidora de Bebidas Big Brother'),
    ('Agropecuaria Labrunier', 'Agropecuaria Labrunier'),
    ('Distribuidora"Biritas"', 'Distribuidora"Biritas"'),
])
def test_nice_name(name, expected):
    assert module.nice_name(name) == expected


@pytest.mark.parametrize('hour,text', [(6, 'bom dia'), (11, 'bom dia'), (12, 'boa tarde'), (17, 'boa tarde'), (18, 'boa noite'), (2, 'boa noite')])
def test_greeting_by_hour(hour, text):
    assert module.greeting(hour) == text
    assert module.fill_greeting('Olá, {saudacao}!', hour) == f'Olá, {text}!'


def test_template_message_and_greeting_at_send_time(client, monkeypatch):
    configure(client, evolution_instance='prospecta', evolution_key='evo-k', first_message='Olá, {saudacao}! Tudo bem? Falo com algum representante ou responsável pelo atendimento contábil da {empresa} aí de {cidade}?')
    lead = {'name': 'AGROPECUARIA LABRUNIER', 'location': 'Petrolina', 'segment': 'agro', 'contact': ''}
    text, origin = asyncio.run(module.write_draft(module.settings(), lead))
    assert origin == 'modelo'
    assert text == 'Olá, {saudacao}! Tudo bem? Falo com algum representante ou responsável pelo atendimento contábil da Agropecuaria Labrunier aí de Petrolina?'
    sent = []

    async def fake_evolution(s, method, path, payload=None):
        sent.append(payload['text'])
        return {'key': {'id': 'S1'}}
    monkeypatch.setattr(module, 'evolution', fake_evolution)
    with module.db() as c:
        c.execute("INSERT INTO leads (identity,name,location,phone,sources,tem_whatsapp) VALUES ('ag','AGROPECUARIA LABRUNIER','Petrolina','5587992011147','[]',1)")
        row = c.execute("SELECT * FROM leads WHERE identity='ag'").fetchone()
    asyncio.run(module.deliver(module.settings(), {'channel': 'whatsapp', 'body': text, 'user_id': None}, row))
    assert sent[0] == text.replace('{saudacao}', module.greeting())


def test_saving_template_refreshes_drafts_but_keeps_manual_edits(client):
    configure(client)
    with module.db() as c:
        c.execute("INSERT INTO leads (identity,name,location,phone,sources,tem_whatsapp,draft,draft_status) VALUES ('a','Loja A','Petrolina','5587992011147','[]',1,'texto antigo da IA','IA')")
        c.execute("INSERT INTO leads (identity,name,location,phone,sources,tem_whatsapp,draft,draft_status,outreach) VALUES ('b','Loja B','Petrolina','5587992011148','[]',1,'x','IA','Aguardando')")
        lead_c = c.execute("INSERT INTO leads (identity,name,location,phone,sources,tem_whatsapp,draft) VALUES ('c','Loja C','Petrolina','5587992011149','[]',1,'')").lastrowid
    assert client.patch(f'/api/leads/{lead_c}', json={'draft': 'Minha mensagem própria?'}, headers=HEADERS).status_code == 200
    configure(client, first_message='Oi, {saudacao}! Aqui é sobre a {empresa}?')
    rows = leads()
    assert rows['Loja A']['draft'] == 'Oi, {saudacao}! Aqui é sobre a Loja A?'
    assert rows['Loja B']['draft'] == 'x'
    assert (rows['Loja C']['draft'], rows['Loja C']['draft_status']) == ('Minha mensagem própria?', 'editado')


def test_approval_edit_and_reject(client):
    configure(client, evolution_instance='prospecta', evolution_key='evo-k')
    with module.db() as c:
        c.execute("INSERT INTO leads (identity,name,location,phone,sources,tem_whatsapp,draft) VALUES ('a','Loja A','Petrolina','5587992011147','[]',1,'Olá?')")
        lead = c.execute("SELECT * FROM leads WHERE identity='a'").fetchone()
        module.enqueue(c, lead, 'whatsapp', 'Olá?', None, review=True)
    item = client.get('/api/approvals').json()[0]
    assert client.patch(f"/api/approvals/{item['id']}", json={'body': 'Olá, {saudacao}! Tudo certo?'}, headers=HEADERS).status_code == 200
    assert client.get('/api/approvals').json()[0]['body'] == 'Olá, {saudacao}! Tudo certo?'
    assert leads()['Loja A']['draft_status'] == 'editado'
    assert client.get('/api/conversations').json() == []
    assert client.post('/api/approvals/reject', json={'all': True}, headers=HEADERS).status_code == 200
    assert client.get('/api/approvals').json() == [] and leads()['Loja A']['outreach'] == 'Não contatado'
    assert client.patch(f"/api/approvals/{item['id']}", json={'body': 'x'}, headers=HEADERS).status_code == 404


@pytest.mark.parametrize('name,expected', [
    ('JK DISTRIBUIDORA DE BEBIDAS VALE DO GRANDE RIO PETROLINA-PE', 'Jk Distribuidora de Bebidas Vale do Grande Rio'),
    ('Depósito Central - Petrolina', 'Depósito Central'),
    ('Petrolina Bebidas', 'Petrolina Bebidas'),
    ('Petrolina', 'Petrolina'),
])
def test_company_name_drops_repeated_city(name, expected):
    assert module.company_name({'name': name, 'location': 'Petrolina'}) == expected


def test_queue_waits_while_whatsapp_disconnected(client, monkeypatch):
    configure(client, evolution_instance='prospecta', evolution_key='evo-k')
    monkeypatch.setattr(module, 'in_window', lambda s: True)
    with module.db() as c:
        c.execute("INSERT INTO leads (identity,name,phone,sources,tem_whatsapp,draft) VALUES ('w','Loja W','5587992011147','[]',1,'Oi?')")
        lead = c.execute("SELECT * FROM leads WHERE identity='w'").fetchone()
        module.enqueue(c, lead, 'whatsapp', 'Oi?', None)
    sent = []

    async def fake_evolution(s, method, path, payload=None):
        if path == 'instance/connectionState':
            return {'instance': {'state': 'connecting'}}
        sent.append(payload)
        return {'key': {'id': 'Z1'}}
    monkeypatch.setattr(module, 'evolution', fake_evolution)
    asyncio.run(module.process_queue(module.settings()))
    assert sent == [] and leads()['Loja W']['outreach'] == 'Na fila'
    assert 'desconectado' in client.get('/api/outreach').json()['errors']['whatsapp']


def test_number_without_whatsapp_is_marked(client, monkeypatch):
    configure(client, evolution_instance='prospecta', evolution_key='evo-k')
    monkeypatch.setattr(module, 'in_window', lambda s: True)
    with module.db() as c:
        c.execute("INSERT INTO leads (identity,name,phone,sources,tem_whatsapp,draft) VALUES ('w','Loja Fixa','5587988422577','[]',1,'Oi?')")
        lead = c.execute("SELECT * FROM leads WHERE identity='w'").fetchone()
        module.enqueue(c, lead, 'whatsapp', 'Oi?', None)

    async def fake_evolution(s, method, path, payload=None):
        if path == 'instance/connectionState':
            return {'instance': {'state': 'open'}}
        if path == 'chat/whatsappNumbers':
            return [{'number': payload['numbers'][0], 'exists': False}]
        raise ValueError('A Evolution API retornou erro (HTTP 400).')
    monkeypatch.setattr(module, 'evolution', fake_evolution)
    asyncio.run(module.process_queue(module.settings()))
    row = leads()['Loja Fixa']
    assert (row['tem_whatsapp'], row['outreach']) == (0, 'Sem WhatsApp')
    with module.db() as c:
        assert c.execute('SELECT status FROM messages').fetchone()[0] == 'cancelado'


def test_signature_can_be_turned_off(client):
    with module.db() as c:
        admin_id = c.execute('SELECT id FROM users').fetchone()[0]
    assert module.sign('Oi', 'whatsapp', admin_id) == '*Admin:*\nOi'
    configure(client, sign_messages=False)
    assert module.sign('Oi', 'whatsapp', admin_id) == 'Oi'
    assert module.sign('Oi', 'email', admin_id) == 'Oi'
    assert client.get('/api/settings').json()['sign_messages'] is False


def test_first_message_never_repeats_for_same_number(client, monkeypatch):
    configure(client, evolution_instance='prospecta', evolution_key='evo-k')
    monkeypatch.setattr(module, 'in_window', lambda s: True)
    with module.db() as c:
        a = c.execute("INSERT INTO leads (identity,name,phone,sources,tem_whatsapp,draft) VALUES ('a','Loja A','5587992011147','[]',1,'Oi?')").lastrowid
        b = c.execute("INSERT INTO leads (identity,name,phone,sources,tem_whatsapp,draft) VALUES ('b','Loja A Filial','5587992011147','[]',1,'Oi?')").lastrowid
    sent = []

    async def fake_evolution(s, method, path, payload=None):
        if path == 'instance/connectionState':
            return {'instance': {'state': 'open'}}
        sent.append(payload['number'])
        return {'key': {'id': f'K{len(sent)}'}}
    monkeypatch.setattr(module, 'evolution', fake_evolution)
    # Os dois cadastros com o mesmo número: só um entra na fila.
    r = client.post('/api/dispatch', json={'lead_ids': [a, b], 'channel': 'whatsapp'}, headers=HEADERS).json()
    assert (r['queued'], r['repeated']) == (1, 1)
    assert leads()['Loja A Filial']['outreach'] == 'Já contatado'
    asyncio.run(module.process_queue(module.settings()))
    assert sent == ['5587992011147']
    # Mesmo que alguém volte o status para "Não contatado", não entra de novo.
    client.patch(f'/api/leads/{a}', json={'outreach': 'Não contatado'}, headers=HEADERS)
    assert client.post('/api/dispatch', json={'lead_ids': [a], 'channel': 'whatsapp'}, headers=HEADERS).json()['queued'] == 0
    # Envio manual da primeira mensagem pelo outro cadastro é bloqueado.
    client.patch(f'/api/leads/{b}', json={'outreach': 'Não contatado'}, headers=HEADERS)
    r = client.post(f'/api/leads/{b}/messages', json={'channel': 'whatsapp', 'body': 'Oi'}, headers=HEADERS)
    assert r.status_code == 409 and 'Loja A' in r.json()['detail']
    assert sent == ['5587992011147']


def test_queue_cancels_duplicate_already_in_queue(client, monkeypatch):
    configure(client, evolution_instance='prospecta', evolution_key='evo-k')
    monkeypatch.setattr(module, 'in_window', lambda s: True)
    with module.db() as c:
        a = c.execute("INSERT INTO leads (identity,name,phone,sources,tem_whatsapp) VALUES ('a','Loja A','5587992011147','[]',1)").lastrowid
        b = c.execute("INSERT INTO leads (identity,name,phone,sources,tem_whatsapp) VALUES ('b','Loja B','5587992011147','[]',1)").lastrowid
        for lead_id in (a, b):
            module.enqueue(c, c.execute('SELECT * FROM leads WHERE id=?', (lead_id,)).fetchone(), 'whatsapp', 'Oi?', None)
    sent = []

    async def fake_evolution(s, method, path, payload=None):
        if path == 'instance/connectionState':
            return {'instance': {'state': 'open'}}
        sent.append(payload['number'])
        return {'key': {'id': f'Q{len(sent)}'}}
    monkeypatch.setattr(module, 'evolution', fake_evolution)
    for _ in range(2):
        with module.db() as c:
            c.execute("DELETE FROM kv WHERE key='next_send'")
        asyncio.run(module.process_queue(module.settings()))
    assert sent == ['5587992011147']
    assert leads()['Loja B']['outreach'] == 'Já contatado'
