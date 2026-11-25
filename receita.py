"""Empresas recém-abertas a partir dos dados abertos de CNPJ da Receita Federal.

A Receita publica a base completa todo mês (arquivos .zip com CSV, alguns GB). Para não ocupar disco, os arquivos
são lidos direto do servidor, por partes, e só ficam guardadas as empresas das cidades escolhidas que abriram
dentro do período configurado.
"""
import csv
import io
import os
import re
import threading
import unicodedata
import zipfile
from concurrent.futures import ThreadPoolExecutor
from datetime import date

import httpx

TOKEN = os.environ.get('PROSPECTA_RFB_TOKEN', 'gn672Ad4CF8N6TK')
BASE = 'https://arquivos.receitafederal.gov.br/public.php'
FOLDER = 'Dados/Cadastros/CNPJ'
PARTS = range(10)
ATIVA = '02'
MATRIZ = '1'


class Cancelled(Exception):
    pass


def norm(text):
    text = unicodedata.normalize('NFKD', text or '').encode('ascii', 'ignore').decode()
    return re.sub(r'\s+', ' ', re.sub(r'[^A-Za-z0-9 ]', ' ', text)).strip().upper()


def parse_cities(text):
    """"Petrolina/PE, Juazeiro - BA" -> [('Petrolina', 'PE'), ('Juazeiro', 'BA')]. Erro claro quando falta a UF."""
    cities = []
    for item in re.split(r'[\n;,]', text or ''):
        item = item.strip()
        if not item:
            continue
        match = re.fullmatch(r'(.+?)\s*[/\-–]\s*([A-Za-z]{2})', item)
        if not match:
            raise ValueError(f'Informe a cidade com a UF, por exemplo "Petrolina/PE" (recebido: "{item}").')
        cities.append((match.group(1).strip(), match.group(2).upper()))
    if not cities:
        raise ValueError('Informe pelo menos uma cidade, por exemplo "Petrolina/PE".')
    return cities


def cutoff(months, today=None):
    today = today or date.today()
    year, month = divmod(today.year * 12 + today.month - 1 - months, 12)
    return f'{year:04d}{month + 1:02d}{min(today.day, 28):02d}'


def mobile_fix(ddd, number):
    """Monta o telefone com 55 + DDD. Celular antigo com 8 dígitos (6-9) ganha o 9 na frente."""
    ddd, number = re.sub(r'\D', '', ddd or '').lstrip('0'), re.sub(r'\D', '', number or '')
    if len(ddd) != 2 or len(number) not in (8, 9):
        return ''
    if len(number) == 8 and number[0] in '6789':
        number = '9' + number
    return '55' + ddd + number


SUFFIX = re.compile(r'[\s.,\-]+(LTDA|ME|EPP|EIRELI|S/?A|SLU|MEI|LIMITADA)\.?$', re.I)


SMALL = {'DE', 'DA', 'DO', 'DAS', 'DOS', 'E', 'EM', 'A', 'O', 'NA', 'NO'}


def titled(text):
    """"RUA DAS FLORES, 10, CENTRO, Petrolina - PE" -> "Rua das Flores, 10, Centro, Petrolina - PE" (siglas de UF ficam)."""
    def word(match):
        w = match.group(0)
        if not w.isupper() or (len(w) == 2 and match.end() == len(text)):
            return w
        return w.lower() if w in SMALL and match.start() else w.capitalize()
    return re.sub(r"[^\W\d_]+", word, text or '')


def clean_name(fantasia, razao):
    """Nome fantasia quando existe; senão a razão social sem CPF no fim (comum em MEI) e sem LTDA/ME/EPP."""
    name = (fantasia or '').strip()
    if not name or set(name) <= set('*.- 0'):
        name = (razao or '').strip()
    name = re.sub(r'[\s\-]*\d{3}\.?\d{3}\.?\d{3}-?\d{2}$', '', name).strip()
    while SUFFIX.search(name):
        name = SUFFIX.sub('', name).strip()
    return name or (razao or '').strip()


class RemoteFile(io.RawIOBase):
    """Arquivo remoto que o zipfile consegue ler: mantém um download aberto e só reabre (com Range) quando há salto."""

    def __init__(self, client, url, size, progress=None, stop=None):
        self.client, self.url, self.size, self.pos = client, url, size, 0
        self.progress, self.stop = progress, stop
        self.response = self.chunks = None
        self.buffer, self.stream_pos = b'', -1

    def seekable(self):
        return True

    def readable(self):
        return True

    def tell(self):
        return self.pos

    def seek(self, offset, whence=0):
        self.pos = {0: offset, 1: self.pos + offset, 2: self.size + offset}[whence]
        return self.pos

    def close_stream(self):
        if self.response is not None:
            self.response.close()
        self.response = self.chunks = None
        self.buffer, self.stream_pos = b'', -1

    def open_stream(self):
        self.close_stream()
        request = self.client.build_request('GET', self.url, headers={'Range': f'bytes={self.pos}-'})
        self.response = self.client.send(request, stream=True)
        if self.response.status_code not in (200, 206):
            raise ValueError(f'A Receita Federal respondeu {self.response.status_code} ao baixar a base de CNPJ.')
        self.chunks = self.response.iter_bytes(1 << 20)
        self.stream_pos = self.pos

    def readinto(self, target):
        if self.stop is not None and self.stop.is_set():
            raise Cancelled()
        if self.pos >= self.size:
            return 0
        for attempt in range(6):
            try:
                if self.stream_pos != self.pos:
                    self.open_stream()
                while not self.buffer:
                    self.buffer = next(self.chunks)
                break
            except (httpx.HTTPError, StopIteration):
                if attempt == 5:
                    raise ValueError('A conexão com a Receita Federal caiu várias vezes. Tente atualizar a base mais tarde.')
                self.stream_pos = -1
        n = min(len(target), len(self.buffer))
        target[:n] = self.buffer[:n]
        self.buffer = self.buffer[n:]
        self.pos += n
        self.stream_pos = self.pos
        if self.progress:
            self.progress(n)
        return n

    def close(self):
        self.close_stream()
        super().close()


def http_client():
    return httpx.Client(auth=(TOKEN, ''), timeout=httpx.Timeout(60, connect=20), follow_redirects=True)


def list_month(client, month=None):
    """(mês mais recente publicado, {arquivo: tamanho})."""
    def propfind(path):
        for attempt in range(4):
            try:
                r = client.request('PROPFIND', f'{BASE}/webdav/{path}', headers={'Depth': '1'})
                break
            except httpx.HTTPError:
                if attempt == 3:
                    raise ValueError('O servidor de dados abertos da Receita Federal não respondeu. Tente mais tarde.')
        if r.status_code >= 400:
            raise ValueError(f'Não foi possível listar a base de CNPJ da Receita (HTTP {r.status_code}). '
                             'Se o endereço mudou, defina PROSPECTA_RFB_TOKEN com o código da pasta pública.')
        return re.findall(r'<d:response>(.*?)</d:response>', r.text, re.S)
    if not month:
        months = sorted(set(re.findall(r'/(\d{4}-\d{2})/</d:href>', ''.join(propfind(FOLDER + '/')))))
        if not months:
            raise ValueError('Nenhum mês publicado na base de CNPJ da Receita.')
        month = months[-1]
    files = {}
    for entry in propfind(f'{FOLDER}/{month}/'):
        href = re.search(r'<d:href>([^<]+)', entry)
        size = re.search(r'getcontentlength>(\d+)<', entry)
        if href and size:
            files[href.group(1).rstrip('/').split('/')[-1]] = int(size.group(1))
    return month, files


def csv_rows(client, month, name, size, progress=None, stop=None):
    remote = RemoteFile(client, f'{BASE}/dav/files/{TOKEN}/{FOLDER}/{month}/{name}', size, progress, stop)
    try:
        with zipfile.ZipFile(io.BufferedReader(remote, 1 << 20)) as archive:
            member = archive.infolist()[0]
            with archive.open(member) as raw:
                yield from csv.reader(io.TextIOWrapper(raw, encoding='latin-1', newline=''), delimiter=';', quotechar='"')
    finally:
        remote.close()


def import_base(cities, months, report=None, stop=None, month=None, workers=3):
    """Baixa e filtra a base. Retorna (mês da base, lista de empresas). `report(etapa, lido, total, encontradas)`."""
    stop = stop or threading.Event()
    with http_client() as client:
        month, files = list_month(client, month)
        groups = {'Estabelecimentos': [f'Estabelecimentos{i}.zip' for i in PARTS], 'Empresas': [f'Empresas{i}.zip' for i in PARTS]}
        needed = ['Municipios.zip', 'Cnaes.zip', 'Simples.zip', *groups['Estabelecimentos'], *groups['Empresas']]
        missing = [f for f in needed if f not in files]
        if missing:
            raise ValueError(f'A base de {month} ainda está incompleta na Receita (faltam {", ".join(missing[:3])}). Tente mais tarde.')
        total = sum(files[f] for f in needed)
        state = {'read': 0, 'step': 'Preparando', 'found': 0}
        lock = threading.Lock()

        def progress(n):
            with lock:
                state['read'] += n
                read = state['read']
            if report and read % (8 << 20) < n:
                report(state['step'], read, total, state['found'])

        def rows(name):
            return csv_rows(client, month, name, files[name], progress, stop)

        state['step'] = 'Lendo municípios'
        wanted = {norm(city): uf for city, uf in cities}
        labels = {}
        targets = {}
        for code, description in rows('Municipios.zip'):
            key = norm(description)
            for city, uf in cities:
                if norm(city) == key:
                    targets.setdefault(code, set()).add(uf)
                    labels[(code, uf)] = city
        unknown = [f'{c}/{u}' for c, u in cities if norm(c) not in {norm(labels[k]) for k in labels}]
        if unknown:
            raise ValueError('Cidade não encontrada na base da Receita: ' + ', '.join(unknown) + '. Confira a grafia.')
        cnaes = {code: description for code, description in rows('Cnaes.zip')}
        since = cutoff(months)
        companies = {}

        def scan_establishments(name):
            found = {}
            for r in rows(name):
                if len(r) < 28 or r[3] != MATRIZ or r[5] != ATIVA or r[10] < since:
                    continue
                ufs = targets.get(r[20])
                if not ufs or r[19] not in ufs:
                    continue
                street = ' '.join(x for x in (r[13], r[14]) if x.strip()).strip()
                address = ', '.join(x for x in (street + (', ' + r[15] if r[15].strip() else ''), r[17].strip(), labels[(r[20], r[19])] + ' - ' + r[19]) if x and x.strip())
                found[r[0]] = {'cnpj': r[0] + r[1] + r[2], 'basico': r[0], 'fantasia': r[4].strip(), 'abertura': f'{r[10][:4]}-{r[10][4:6]}-{r[10][6:8]}',
                               'cnae': r[11], 'atividade': cnaes.get(r[11], ''), 'uf': r[19], 'cidade': labels[(r[20], r[19])], 'endereco': address,
                               'bairro': r[17].strip(), 'cep': r[18], 'phone': mobile_fix(r[21], r[22]), 'phone2': mobile_fix(r[23], r[24]),
                               'email': (r[27] or '').strip().lower()}
                with lock:
                    state['found'] += 1
            return found

        state['step'] = 'Lendo estabelecimentos'
        with ThreadPoolExecutor(workers) as pool:
            for found in pool.map(scan_establishments, groups['Estabelecimentos']):
                companies.update(found)

        def scan_companies(name):
            found = {}
            for r in rows(name):
                if r and r[0] in companies:
                    found[r[0]] = (r[1].strip(), r[2], r[5] if len(r) > 5 else '')
            return found

        state['step'] = 'Lendo razão social'
        with ThreadPoolExecutor(workers) as pool:
            for found in pool.map(scan_companies, groups['Empresas']):
                for basico, (razao, natureza, porte) in found.items():
                    companies[basico].update(razao=razao, natureza=natureza, porte=porte)

        state['step'] = 'Lendo Simples/MEI'
        for r in rows('Simples.zip'):
            if r and r[0] in companies and len(r) > 4:
                companies[r[0]]['mei'] = int(r[4] == 'S')

        result = []
        for item in companies.values():
            item.setdefault('razao', '')
            item.setdefault('natureza', '')
            item.setdefault('porte', '')
            item.setdefault('mei', 0)
            item['nome'] = clean_name(item['fantasia'], item['razao'])
            del item['basico']
            result.append(item)
        if report:
            report('Concluído', total, total, len(result))
        return month, result
