"""Gera historico/envios.csv com tudo o que já foi mandado e recebido, sem senhas nem chaves.

Uso: python exportar_historico.py [--ignorar 5587999999999,...]
O CSV abre direto no Excel ou no Google Planilhas. Rode de novo para atualizar.
"""
import argparse
import csv
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

from app import fill_greeting

ROOT = Path(__file__).parent
BRT = timedelta(hours=-3)  # o banco guarda horários em UTC
KIND = {'inicial': 'Primeira mensagem', 'followup': 'Follow-up', 'resposta': 'Resposta da empresa'}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--ignorar', default='', help='telefones ou e-mails de teste, separados por vírgula')
    args = parser.parse_args()
    skip = {item.strip() for item in args.ignorar.split(',') if item.strip()}
    conn = sqlite3.connect(ROOT / 'data' / 'prospecta.db')
    conn.row_factory = sqlite3.Row
    rows = conn.execute("""
        SELECT m.sent, m.created, m.direction, m.channel, m.kind, m.status, m.error, m.body,
               l.name, l.location, l.segment, l.phone, l.email, l.cnpj, l.outreach, l.stage
        FROM messages m JOIN leads l ON l.id = m.lead_id
        WHERE m.status IN ('enviado', 'recebido', 'erro')
        ORDER BY COALESCE(m.sent, m.created), m.id""").fetchall()
    out = ROOT / 'historico' / 'envios.csv'
    out.parent.mkdir(exist_ok=True)
    written = 0
    with open(out, 'w', newline='', encoding='utf-8-sig') as f:
        w = csv.writer(f, delimiter=';')
        w.writerow(['Data (Brasília)', 'Empresa', 'Cidade', 'Atividade', 'CNPJ', 'Canal', 'Contato', 'Tipo',
                    'Status do envio', 'Mensagem', 'Situação atual da empresa', 'Etapa no funil'])
        for r in rows:
            contact = r['phone'] if r['channel'] == 'whatsapp' else r['email']
            if contact in skip:
                continue
            when = datetime.fromisoformat(r['sent'] or r['created']) + BRT
            body = r['body'] or ''
            if r['direction'] == 'out':
                body = fill_greeting(body, when.hour)
            status = {'enviado': 'Enviado', 'recebido': 'Recebido', 'erro': f"Erro: {r['error']}"}[r['status']]
            w.writerow([when.strftime('%d/%m/%Y %H:%M'), r['name'], r['location'], r['segment'], r['cnpj'] or '',
                        'WhatsApp' if r['channel'] == 'whatsapp' else 'E-mail', contact, KIND.get(r['kind'], r['kind']),
                        status, body, r['outreach'], r['stage']])
            written += 1
    print(f'{written} mensagens em {out}')


if __name__ == '__main__':
    main()
