# Prospecta Local

CRM e agente de prospecção para uso individual no notebook. Python/FastAPI, SQLite e interface sem build, CDN ou modelo de IA local.

## Iniciar

```sh
cd /home/cadu/prospecta-local
./start.sh
```

Abra http://127.0.0.1:8000. Use apenas um processo do servidor. Precisa de Python 3.10+ e internet para instalar dependências e consultar as APIs.

1. Em **Configurações**, descreva sua empresa, seus três sistemas e o desenvolvimento sob demanda.
2. Cadastre uma ou ambas as chaves. Selecione OpenAI ou Gemini e salve. Campo vazio preserva a chave; a opção Remover apaga a chave correspondente.
3. Use **Testar conexão salva** para conferir autenticação e acesso ao modelo. Esse teste faz uma chamada real de texto, que pode ser cobrada. Não testa busca web.
4. Em **Agente de prospecção**, preencha segmento, região e critérios e inicie uma busca.
5. Acompanhe os resultados em **Oportunidades**: cada empresa traz site, e-mail, WhatsApp e Instagram quando publicados. Complete o que faltar em **Editar contatos**.
6. Configure os canais em **Configurações** e dispare em **Disparos**. As respostas aparecem em **Conversas** em tempo real.

No Windows, sem o `start.sh`:

```sh
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python -m uvicorn app:app --host 127.0.0.1 --port 8000
```

## Disparo, follow-up e conversas

- **E-mail:** SMTP para enviar e IMAP para ler as respostas (Gmail/Outlook exigem senha de app). As respostas são associadas pelo remetente e lidas sem marcar como lidas.
- **WhatsApp:** Evolution API v2 rodando localmente (`docker compose -f docker-compose.evolution.yml up -d`, depois crie a instância e leia o QR code em http://localhost:8080/manager). Use um número dedicado: disparo em massa por API não oficial pode levar a bloqueio.
- **Fila:** um envio por vez, com intervalo mínimo aleatorizado, janela de horário e limite diário configuráveis.
- **Follow-up:** quem não responde recebe a mensagem de follow-up a cada N dias, até o máximo configurado; depois vai para “Sem resposta”. Qualquer resposta interrompe a cadência.
- **Classificação:** respostas viram “Interessado”, “Recusou” ou “Respondeu” (palavras-chave e, se houver chave de IA, o modelo). Recusas cancelam a fila daquela empresa e movem para “Perdido”. Você pode corrigir o status na conversa.
- **Tempo real:** a tela de Conversas recebe eventos do servidor (SSE); e-mails são verificados a cada 30 s e o WhatsApp a cada 30 s.

## O que está implementado

- Duas credenciais independentes, provedor e modelo selecionáveis na interface.
- OpenAI Responses com `web_search`; Gemini `generateContent` com `google_search`.
- Pesquisa em texto com fontes, seguida de uma chamada separada de qualificação, cadastro automático com fontes, deduplicação por domínio ou nome/localidade e histórico persistido.
- Cadastro manual, filtro por etapa/nome, atualização do funil e rascunhos de abordagem.
- Limite diário de execuções (UTC), uma busca por vez, até dez resultados por execução.
- Erros de autenticação, modelo, cota e conexão apresentados sem expor as chaves.

## Custos e limites

O provedor e o modelo são capturados ao iniciar cada execução. Alterações valem para a próxima. Os modelos sugeridos são editáveis e sua disponibilidade e suporte a busca dependem da conta. Não existe fallback automático pago para outro provedor.

O limite diário conta tentativas de prospecção, incluindo erros, não testes de conexão. Não é um teto monetário: tokens e pesquisas são cobrados conforme o provedor. Configure os limites também no painel da API. A aplicação não estima valores em moeda.

A busca exige fontes retornadas pelo provedor. Resultados sem correspondência entre `source_urls` e as fontes da busca são descartados. Fontes são evidências para revisão, não uma garantia de precisão; necessidades comerciais são hipóteses. A pesquisa pode retornar menos empresas que o solicitado ou nenhuma. Duplicados mantêm os dados anteriores.

Esta primeira versão executa um lote por comando do usuário. Não possui agendamento recorrente, envio de mensagens nem navegação visual. O notebook precisa ficar ligado e o processo aberto. Ao reiniciar, execuções pendentes são marcadas como interrompidas e precisam ser iniciadas novamente, evitando repetir chamadas pagas silenciosamente.

## Dados locais

`data/prospecta.db` contém o CRM e as configurações. Chaves são criptografadas com Fernet; `data/secret.key` guarda a chave de criptografia, ambos protegidos por permissões locais. Isso protege contra leitura casual do banco isolado, não contra alguém com acesso à sua conta e aos dois arquivos. Faça backup da pasta `data` inteira; não a publique ou compartilhe. As chaves nunca são devolvidas à interface nem colocadas no armazenamento do navegador.

O servidor escuta apenas em `127.0.0.1`. Requisições de alteração exigem cabeçalho próprio e validação de origem. Não exponha esta versão na rede: não há autenticação multiusuário. Os dados necessários à busca são enviados ao provedor ativo. A interface mostra fontes clicáveis; sugestões de busca do Google são exibidas em iframe isolado, sem scripts.

## Testes

```sh
.venv/bin/pip install pytest
.venv/bin/python -m pytest -q
node --check static/app.js
```

Testes usam respostas simuladas das APIs, sem cobrança. Consultas reais exigem chaves fornecidas pelo usuário pela tela.

Documentação das integrações:
- https://developers.openai.com/api/docs/guides/tools-web-search
- https://ai.google.dev/api/generate-content
- https://ai.google.dev/gemini-api/docs/google-search

Cada execução com fontes faz duas chamadas de IA: pesquisa web e extração estruturada. Sem fontes, termina como “sem resultados”, preservando o consumo informado pelo provedor.
