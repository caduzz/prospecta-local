from datetime import date

import pytest
from fastapi.testclient import TestClient

import app as module
import receita

HEADERS = {'X-Prospecta': 'local'}
ADMIN = {'name': 'Admin', 'email': 'admin@test.dev', 'password': 'senha-forte-1'}


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(module, 'DATA', tmp_path)
    monkeypatch.setattr(module, 'WORKER', False)
    with TestClient(module.app) as client:
        client.post('/api/auth/setup', json=ADMIN, headers=HEADERS)
        yield client


def estab(basico, opened, fantasia='', uf='PE', city='2521', status='02', matriz='1', ddd='87', tel='99201114', email=''):
    row = [''] * 30
    row[0], row[1], row[2], row[3], row[4], row[5] = basico, '0001', '00', matriz, fantasia, status
    row[10], row[11], row[13], row[14], row[15], row[17], row[18], row[19], row[20] = opened, '5611201', 'RUA', 'DAS FLORES', '10', 'CENTRO', '56300000', uf, city
    row[21], row[22], row[27] = ddd, tel, email
    return row


def test_helpers():
    assert receita.parse_cities('Petrolina/PE, Juazeiro - ba') == [('Petrolina', 'PE'), ('Juazeiro', 'BA')]
    with pytest.raises(ValueError):
        receita.parse_cities('Petrolina')
    assert receita.cutoff(6, date(2026, 11, 18)) == '20260518'
    assert receita.cutoff(12, date(2026, 1, 31)) == '20250128'
    assert receita.mobile_fix('87', '99201114') == '5587999201114'
    assert receita.mobile_fix('087', '38611234') == '558738611234'
    assert receita.mobile_fix('', '38611234') == ''
    assert receita.clean_name('', 'MARIA DA SILVA 12345678901') == 'MARIA DA SILVA'
    assert receita.clean_name('', 'PADARIA BOM PAO LTDA') == 'PADARIA BOM PAO'
    assert receita.clean_name('BOM PAO', 'X LTDA') == 'BOM PAO'
    assert receita.clean_name('********', 'SABOR & CIA EIRELI') == 'SABOR & CIA'
    assert receita.titled('RUA DAS FLORES, 10, SALA 2, CENTRO, Petrolina - PE') == 'Rua das Flores, 10, Sala 2, Centro, Petrolina - PE'


def test_import_base_filters_city_date_status_and_branch(monkeypatch):
    today = date.today()
    recent = f'{today.year}{today.month:02d}01'
    files = {name: 1 for name in ['Municipios.zip', 'Cnaes.zip', 'Simples.zip'] + [f'Estabelecimentos{i}.zip' for i in range(10)] + [f'Empresas{i}.zip' for i in range(10)]}
    data = {
        'Municipios.zip': [['2521', 'PETROLINA'], ['3669', 'JUAZEIRO'], ['9999', 'PETROLINA']],
        'Cnaes.zip': [['5611201', 'Restaurantes e similares']],
        'Estabelecimentos0.zip': [
            estab('11111111', recent, 'Sabor do Vale'),                       # entra
            estab('22222222', '20100101', 'Antiga'),                          # aberta há muito tempo
            estab('33333333', recent, 'Baixada', status='08'),                # não está ativa
            estab('44444444', recent, 'Filial', matriz='2'),                  # filial
            estab('55555555', recent, 'Outra UF', uf='MG', city='9999'),      # mesmo nome de cidade, outra UF
            estab('66666666', recent, '', email='DONO@GMAIL.COM'),            # sem fantasia: usa razão social
        ],
        'Empresas0.zip': [['11111111', 'SABOR DO VALE LTDA', '2062', '49', '1000,00', '01', ''], ['66666666', 'JOSE SOUZA 12345678901', '2135', '50', '0', '01', '']],
        'Simples.zip': [['66666666', 'S', '20260101', '00000000', 'S', '20260101', '00000000']],
    }
    monkeypatch.setattr(receita, 'list_month', lambda client, month=None: ('2026-11', files))
    monkeypatch.setattr(receita, 'csv_rows', lambda client, month, name, size, progress=None, stop=None: iter(data.get(name, [])))
    month, rows = receita.import_base([('Petrolina', 'PE')], 3)
    by_cnpj = {r['cnpj']: r for r in rows}
    assert month == '2026-11' and set(by_cnpj) == {'11111111000100', '66666666000100'}
    first = by_cnpj['11111111000100']
    assert first['nome'] == 'Sabor do Vale' and first['razao'] == 'SABOR DO VALE LTDA' and first['atividade'] == 'Restaurantes e similares'
    assert first['phone'] == '5587999201114' and first['cidade'] == 'Petrolina' and first['mei'] == 0 and first['abertura'].startswith(str(today.year))
    second = by_cnpj['66666666000100']
    assert second['nome'] == 'JOSE SOUZA' and second['mei'] == 1 and second['email'] == 'dono@gmail.com'
    with pytest.raises(ValueError, match='Cidade não encontrada'):
        receita.import_base([('Cidade Inexistente', 'PE')], 3)


def seed(rows):
    with module.db() as c:
        for r in rows:
            base = dict.fromkeys(module.CNPJ_FIELDS, '') | {'mei': 0, 'uf': 'PE', 'cidade': 'Petrolina', 'atividade': 'Restaurantes e similares'} | r
            c.execute(f"INSERT INTO cnpj_empresas ({','.join(module.CNPJ_FIELDS)}, mes_base) VALUES ({','.join('?' * (len(module.CNPJ_FIELDS) + 1))})",
                      tuple(base[f] for f in module.CNPJ_FIELDS) + ('2026-11',))


def days_ago(n):
    from datetime import timedelta
    return (date.today() - timedelta(days=n)).isoformat()


def test_search_creates_leads_and_skips_accountants_mei_and_old(client):
    assert client.post('/api/cnpj/buscar', json={}, headers=HEADERS).status_code == 400
    accountant = '5587999990000'
    seed([
        {'cnpj': '10000000000101', 'nome': 'SABOR DO VALE', 'razao': 'SABOR DO VALE LTDA', 'abertura': days_ago(20), 'phone': '5587999201114', 'email': 'sabor@gmail.com'},
        {'cnpj': '10000000000102', 'nome': 'Loja A', 'abertura': days_ago(30), 'phone': accountant, 'email': 'fiscal@contabilidadexyz.com.br'},
        {'cnpj': '10000000000103', 'nome': 'Loja B', 'abertura': days_ago(40), 'phone': accountant, 'phone2': '5587999112233'},
        {'cnpj': '10000000000104', 'nome': 'Loja C', 'abertura': days_ago(50), 'phone': accountant},
        {'cnpj': '10000000000105', 'nome': 'Microempreendedor', 'abertura': days_ago(10), 'phone': '5587999445566', 'mei': 1},
        {'cnpj': '10000000000106', 'nome': 'Antiga', 'abertura': days_ago(400), 'phone': '5587999778899'},
        {'cnpj': '10000000000107', 'nome': 'Padaria Fixo', 'abertura': days_ago(60), 'phone': '558738611234'},
        {'cnpj': '10000000000108', 'nome': 'Clinica Juazeiro', 'abertura': days_ago(5), 'phone': '5574999001122', 'cidade': 'Juazeiro', 'uf': 'BA', 'atividade': 'Clínica médica', 'cnae': '8630503'},
    ])
    info = client.get('/api/cnpj').json()
    assert info['total'] == 8 and {c['cidade'] for c in info['cidades']} == {'Petrolina', 'Juazeiro'}
    r = client.post('/api/cnpj/buscar', json={'cidade': 'Petrolina/PE', 'meses': 6}, headers=HEADERS)
    assert r.status_code == 200, r.text
    log = r.json()['log']
    with module.db() as c:
        leads = {row['name']: dict(row) for row in c.execute('SELECT * FROM leads')}
    assert set(leads) == {'Sabor do Vale', 'Loja B', 'Padaria Fixo'}
    sabor = leads['Sabor do Vale']
    assert sabor['outreach'] == 'Não contatado' and sabor['tem_whatsapp'] == 1 and sabor['cnpj'] == '10000000000101' and sabor['email'] == 'sabor@gmail.com'
    assert sabor['diagnostico'] == '{}' and 'CNPJ 10.000.000/0001-01' in sabor['reason'] and sabor['segment'] == 'Restaurantes e similares'
    assert leads['Loja B']['phone'] == '5587999112233'
    assert leads['Padaria Fixo']['outreach'] == 'Sem WhatsApp'
    assert log['motivos'] == {'contato de escritório contábil': 2} and log['descartados'] == 2
    again = client.post('/api/cnpj/buscar', json={'cidade': 'Petrolina/PE', 'meses': 6}, headers=HEADERS).json()['log']
    assert again['novos'] == 0 and again['duplicados'] == 3
    health = client.post('/api/cnpj/buscar', json={'meses': 1, 'excluir_mei': False, 'atividade': 'clinica'}, headers=HEADERS).json()['log']
    assert health['encontrados'] == 0
    with_mei = client.post('/api/cnpj/buscar', json={'meses': 1, 'excluir_mei': False, 'excluir_saude': False, 'atividade': 'clinica'}, headers=HEADERS).json()['log']
    assert with_mei['novos'] == 1
    runs = client.get('/api/runs').json()
    assert runs[0]['provider'] == 'receita' and runs[0]['status'] == 'concluído'


def test_cnpj_leads_get_template_and_go_to_approval(client, monkeypatch):
    data = module.DEFAULTS | {'offers': 'Contabilidade', 'evolution_instance': 'prospecta', 'evolution_key': 'evo-k'}
    s = client.put('/api/settings', json=data | {'revision': client.get('/api/settings').json().get('revision', 0)}, headers=HEADERS).json()
    assert client.put('/api/settings', json=data | {'auto_dispatch': True, 'revision': s['revision']}, headers=HEADERS).status_code == 200
    seed([{'cnpj': '20000000000101', 'nome': 'NOVA PADARIA', 'abertura': days_ago(15), 'phone': '5587999201114'}])
    client.post('/api/cnpj/buscar', json={'meses': 3}, headers=HEADERS)
    module.asyncio.run(module.enrich_once())
    with module.db() as c:
        lead = c.execute('SELECT * FROM leads').fetchone()
        message = c.execute('SELECT * FROM messages').fetchone()
    assert 'Nova Padaria' in lead['draft'] and 'Petrolina' in lead['draft'] and lead['outreach'] == 'Para aprovar'
    assert message['status'] == 'aprovacao'


def test_import_is_admin_only_and_validates(client):
    assert client.post('/api/cnpj/importar', json={'cidades': 'Petrolina'}, headers=HEADERS).status_code == 400
    client.post('/api/team', json={'name': 'Ana', 'email': 'ana@test.dev', 'password': 'senha-forte-2', 'role': 'member'}, headers=HEADERS)
    client.post('/api/auth/logout', headers=HEADERS)
    client.post('/api/auth/login', json={'email': 'ana@test.dev', 'password': 'senha-forte-2'}, headers=HEADERS)
    assert client.post('/api/cnpj/importar', json={'cidades': 'Petrolina/PE'}, headers=HEADERS).status_code == 403
    assert client.get('/api/cnpj').status_code == 200


def test_spin_variations_are_stable_per_lead_and_vary_between_leads():
    assert module.spin('{Olá|Oi} {empresa}', __import__('random').Random(1)) in ('Olá {empresa}', 'Oi {empresa}')
    assert module.spin('{saudacao} sem opções') == '{saudacao} sem opções'
    template = module.DEFAULTS['first_message']
    lead = lambda i: {'id': i, 'name': 'PADARIA BOM PAO', 'location': 'Petrolina', 'segment': '', 'contact': ''}
    first = module.render(template, lead(1))
    assert first == module.render(template, lead(1))
    assert '|' not in first and 'Padaria Bom Pao' in first and 'Petrolina' in first and '{saudacao}' in first
    assert len({module.render(template, lead(i)) for i in range(40)}) > 10
    assert module.render(module.DEFAULTS['followup_text'], lead(1), 'followup0') != '' and '|' not in module.render(module.DEFAULTS['followup_text'], lead(1), 'followup0')
    assert module.DEFAULTS['send_interval'] == 600 and module.DEFAULTS['send_daily_limit'] == 40


def test_same_number_in_two_leads_gets_only_one_followup(client):
    s = module.settings()
    with module.db() as c:
        for name in ('Matheus', 'matheus'):
            c.execute("""INSERT INTO leads (identity,name,phone,sources,tem_whatsapp,outreach,channel,attempts,next_followup) VALUES (?,?,'5587981407282','[]',1,'Aguardando','whatsapp',0,'2000-01-01 00:00:00')""", (name, name))
    module.schedule_followups(s)
    with module.db() as c:
        queued = c.execute("SELECT COUNT(*) FROM messages WHERE kind='followup' AND status='na fila'").fetchone()[0]
        skipped = c.execute("SELECT motivo_descarte FROM leads WHERE name='matheus'").fetchone()[0]
    assert queued == 1 and 'já recebe o de Matheus' in skipped
    module.schedule_followups(s)
    with module.db() as c:
        assert c.execute("SELECT COUNT(*) FROM messages WHERE kind='followup'").fetchone()[0] == 1
