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
    monkeypatch.setattr(module, 'in_window', lambda s: True)
    with TestClient(module.app) as client:
        yield client


def configure(client, **extra):
    data = module.DEFAULTS | {'gemini_key': 'gemini-secret-test', 'offers': 'Software', 'smtp_host': 'smtp.test', 'smtp_user': 'eu@empresa.test', 'smtp_key': 'senha-app-test',
                              'imap_host': 'imap.test', 'evolution_instance': 'prospecta', 'evolution_key': 'evo-secret-test'} | extra
    response = client.put('/api/settings', json=data, headers=HEADERS)
    assert response.status_code == 200, response.text
    return response.json()


def add(client, name, **fields):
    assert client.post('/api/leads', json={'name': name} | fields, headers=HEADERS).status_code == 200
    return next(l for l in client.get('/api/leads').json() if l['name'] == name)


def lead(lead_id):
    with module.db() as c:
        return dict(c.execute('SELECT * FROM leads WHERE id=?', (lead_id,)).fetchone())


def messages(lead_id):
    with module.db() as c:
        return [dict(r) for r in c.execute('SELECT * FROM messages WHERE lead_id=? ORDER BY id', (lead_id,))]


def test_contacts_are_normalized_and_validated(client):
    l = add(client, 'Clínica Sol', email='Contato@ClinicaSol.com.br', phone='(71) 99876-5432', instagram='https://www.instagram.com/clinicasol/')
    assert (l['email'], l['phone'], l['instagram'], l['outreach']) == ('contato@clinicasol.com.br', '5571998765432', 'clinicasol', 'Não contatado')
    assert client.post('/api/leads', json={'name': 'Outra', 'email': 'invalido'}, headers=HEADERS).status_code == 400
    assert client.patch(f"/api/leads/{l['id']}", json={'phone': '123'}, headers=HEADERS).status_code == 400
    assert client.patch(f"/api/leads/{l['id']}", json={'instagram': '@novo.perfil'}, headers=HEADERS).status_code == 200
    assert lead(l['id'])['instagram'] == 'novo.perfil'


def test_secrets_are_not_exposed(client):
    s = configure(client)
    assert s['smtp_configured'] and s['evolution_configured']
    assert 'senha-app-test' not in json.dumps(s) and 'evo-secret-test' not in json.dumps(s)
    with module.db() as c:
        assert 'senha-app-test' not in c.execute('SELECT value FROM settings').fetchone()[0]


def test_dispatch_requires_channel_and_contact(client):
    l = add(client, 'Empresa A', email='a@empresa.test')
    body = {'lead_ids': [l['id']], 'channel': 'email', 'template': 'Olá {empresa}'}
    assert client.post('/api/dispatch', json=body, headers=HEADERS).status_code == 400
    configure(client)
    no_email = add(client, 'Empresa B', phone='71999998888')
    r = client.post('/api/dispatch', json=body | {'lead_ids': [l['id'], no_email['id']]}, headers=HEADERS).json()
    assert (r['queued'], r['skipped']) == (1, 1)
    assert lead(l['id'])['outreach'] == 'Na fila'
    assert messages(l['id'])[0]['body'] == 'Olá Empresa A'
    assert client.post('/api/dispatch', json=body, headers=HEADERS).json()['queued'] == 0


def test_queue_send_followups_and_give_up(client, monkeypatch):
    configure(client, followup_max=2, followup_days=3)
    l = add(client, 'Empresa A', email='a@empresa.test')
    client.post('/api/dispatch', json={'lead_ids': [l['id']], 'channel': 'email', 'subject': 'Ideia para {empresa}', 'template': 'Oi'}, headers=HEADERS)
    sent = []

    async def fake_deliver(s, message, lead):
        sent.append((message['kind'], message['subject']))
        return f'<id-{len(sent)}@test>'
    monkeypatch.setattr(module, 'deliver', fake_deliver)

    def run_cycle():
        with module.db() as c:
            c.execute("UPDATE leads SET next_followup='2000-01-01 00:00:00' WHERE next_followup IS NOT NULL")
            c.execute("DELETE FROM kv WHERE key='next_send'")
        module.schedule_followups(module.settings())
        asyncio.run(module.process_queue(module.settings()))

    asyncio.run(module.process_queue(module.settings()))
    state = lead(l['id'])
    assert (state['outreach'], state['stage'], state['attempts']) == ('Aguardando', 'Em contato', 0)
    assert state['next_followup'] > module.now()
    run_cycle()
    run_cycle()
    assert sent == [('inicial', 'Ideia para Empresa A'), ('followup', 'Re: Ideia para Empresa A'), ('followup', 'Re: Ideia para Empresa A')]
    assert lead(l['id'])['attempts'] == 2
    run_cycle()
    assert lead(l['id'])['outreach'] == 'Sem resposta' and len(sent) == 3


def test_send_failure_marks_lead(client, monkeypatch):
    configure(client)
    l = add(client, 'Empresa A', email='a@empresa.test')
    client.post('/api/dispatch', json={'lead_ids': [l['id']], 'channel': 'email', 'template': 'Oi'}, headers=HEADERS)

    async def failing(*args):
        raise ValueError('O servidor recusou o endereço do destinatário.')
    monkeypatch.setattr(module, 'deliver', failing)
    asyncio.run(module.process_queue(module.settings()))
    assert lead(l['id'])['outreach'] == 'Falha no envio'
    assert messages(l['id'])[0]['status'] == 'erro'
    assert client.get('/api/outreach').json()['failed'][0]['name'] == 'Empresa A'


@pytest.mark.parametrize('text,outreach,stage', [
    ('Obrigado, mas não temos interesse no momento.', 'Recusou', 'Perdido'),
    ('Tenho interesse sim, qual o valor?', 'Interessado', 'Em contato'),
    ('Quem é você?', 'Respondeu', 'Novo'),
])
def test_replies_are_classified_and_stop_followups(client, text, outreach, stage):
    configure(client, gemini_key='')
    s = module.settings()
    s.pop('gemini_key', None)
    l = add(client, 'Empresa A', email='a@empresa.test')
    with module.db() as c:
        c.execute("UPDATE leads SET outreach='Aguardando', next_followup='2000-01-01 00:00:00' WHERE id=?", (l['id'],))
        c.execute("INSERT INTO messages (lead_id,direction,channel,kind,body,status) VALUES (?,'out','email','followup','x','na fila')", (l['id'],))
    assert asyncio.run(module.receive(s, l['id'], 'email', '<r1@test>', text))
    assert not asyncio.run(module.receive(s, l['id'], 'email', '<r1@test>', text))
    state = lead(l['id'])
    assert (state['outreach'], state['stage'], state['unread'], state['next_followup']) == (outreach, stage, 1, None)
    assert [m['status'] for m in messages(l['id'])] == ['cancelado', 'recebido']
    conv = client.get('/api/conversations').json()[0]
    assert conv['last_direction'] == 'in' and conv['unread'] == 1
    assert client.get(f"/api/leads/{l['id']}/messages").json()['lead']['unread'] == 0


def test_poll_email_matches_sender(client, monkeypatch):
    configure(client)
    l = add(client, 'Empresa A', email='a@empresa.test')
    with module.db() as c:
        c.execute("INSERT INTO messages (lead_id,direction,channel,kind,body,status,sent) VALUES (?,'out','email','inicial','Oi','enviado',?)", (l['id'], module.now()))
    seen = {}

    def fake_fetch(s, last_uid, since):
        seen['uid'] = last_uid
        return [{'from': 'a@empresa.test', 'subject': 'Re: Oi', 'body': 'Pode me ligar amanhã', 'id': '<x@test>'},
                {'from': 'spam@outro.test', 'subject': 'Promo', 'body': 'Compre', 'id': '<y@test>'}], 42
    monkeypatch.setattr(module, 'fetch_email_sync', fake_fetch)
    asyncio.run(module.poll_inbound(module.settings()))
    assert lead(l['id'])['outreach'] == 'Interessado'
    assert len(messages(l['id'])) == 2
    asyncio.run(module.poll_inbound(module.settings()))
    assert seen['uid'] == 42


def test_whatsapp_send_and_receive(client, monkeypatch):
    configure(client)
    l = add(client, 'Empresa W', phone='71 99876-5432')
    calls = []
    real_client = httpx.AsyncClient

    def handler(request):
        calls.append((request.url.path, json.loads(request.content or b'{}'), request.headers.get('apikey')))
        if request.url.path.startswith('/message/sendText'):
            return httpx.Response(201, json={'key': {'id': 'OUT1', 'fromMe': True}})
        jid = json.loads(request.content)['where']['key']['remoteJid']
        records = [{'key': {'id': 'IN1', 'fromMe': False, 'remoteJid': jid}, 'message': {'conversation': 'Não quero, obrigado'}, 'messageTimestamp': 4102444800},
                   {'key': {'id': 'OUT1', 'fromMe': True}, 'message': {'conversation': 'Oi'}, 'messageTimestamp': 4102444800}] if '5571998765432' in jid else []
        return httpx.Response(200, json={'messages': {'records': records}})
    monkeypatch.setattr(module.httpx, 'AsyncClient', lambda **kwargs: real_client(transport=httpx.MockTransport(handler), **kwargs))
    assert client.post(f"/api/leads/{l['id']}/messages", json={'channel': 'whatsapp', 'body': 'Oi'}, headers=HEADERS).status_code == 200
    assert calls[0] == ('/message/sendText/prospecta', {'number': '5571998765432', 'text': 'Oi'}, 'evo-secret-test')
    assert lead(l['id'])['outreach'] == 'Aguardando'
    asyncio.run(module.poll_inbound(module.settings()))
    assert {c[1]['where']['key']['remoteJid'] for c in calls[1:]} == {'5571998765432@s.whatsapp.net', '557198765432@s.whatsapp.net'}
    state = lead(l['id'])
    assert (state['outreach'], state['stage']) == ('Recusou', 'Perdido')
    assert [m['direction'] for m in messages(l['id'])] == ['out', 'in']


def test_agent_saves_contacts(client, monkeypatch):
    configure(client)

    async def fake(s, prompt, search=False):
        if search:
            return 'relatório', [{'url': 'https://example.com', 'title': 'Site'}], {}, ''
        return json.dumps({'leads': [{'name': 'Empresa real', 'website': 'https://example.com', 'email': 'mailto:Oi@Example.com', 'phone': '+55 (71) 3333-4444',
                                      'instagram': '@empresareal', 'draft': 'Olá!', 'source_urls': ['https://example.com']}]}), [], {}, ''
    monkeypatch.setattr(module, 'generate', fake)
    with module.db() as c:
        run_id = c.execute("INSERT INTO runs (status) VALUES ('executando')").lastrowid
    asyncio.run(module.prospect(run_id, module.settings(), module.Campaign(segment='Clínicas', location='Salvador')))
    l = client.get('/api/leads').json()[0]
    assert (l['email'], l['phone'], l['instagram']) == ('oi@example.com', '557133334444', 'empresareal')


def test_strip_quoted_reply():
    text = 'Tenho interesse.\n\nEm seg., 10 de nov. de 2026 às 10:00, Eu <eu@x.com> escreveu:\n> mensagem antiga'
    assert module.strip_quoted(text) == 'Tenho interesse.'
