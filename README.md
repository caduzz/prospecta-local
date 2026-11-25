# Prospecta

CRM e agente de prospecção para uma equipe pequena. Python/FastAPI, SQLite e interface sem build, CDN ou modelo de IA local.

## Iniciar

```sh
cd /home/cadu/prospecta-local
./start.sh
```

No Windows, sem o `start.sh`:

```sh
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python -m uvicorn app:app --host 127.0.0.1 --port 8000
```

Abra http://127.0.0.1:8000. Use apenas um processo do servidor. Precisa de Python 3.10+.

1. **Primeiro acesso:** crie a conta de administrador (só funciona no próprio computador do servidor).
2. Em **Configurações**, descreva sua empresa e o que você vende, cadastre a chave do **Google Places** e, se quiser mensagens escritas pela IA, uma chave Gemini ou OpenAI.
3. Em **Equipe**, adicione os membros.
4. Em **Agente de prospecção**, informe segmento e cidade e escolha 20, 40 ou 60 empresas.
5. Em **Oportunidades**, veja o diagnóstico de cada empresa (“No Google: …”) e a mensagem sugerida.
6. Configure os canais em **Configurações** e dispare em **Disparos**. As respostas aparecem em **Conversas** em tempo real.

## Fonte dos leads: Google Places

A busca usa o **Text Search da Places API (New)** com a consulta “{segmento} em {cidade}”, até 3 páginas de 20 resultados, pedindo só estes campos: `id`, `displayName`, `formattedAddress`, `nationalPhoneNumber`, `internationalPhoneNumber`, `websiteUri`, `primaryType`, `types`, `businessStatus`, `googleMapsUri`.

**Como criar a chave**

1. Acesse https://console.cloud.google.com, crie (ou escolha) um projeto e ative o faturamento dele.
2. Em **APIs e serviços › Biblioteca**, ative a **Places API (New)**.
3. Em **APIs e serviços › Credenciais**, clique em **Criar credenciais › Chave de API**.
4. Edite a chave e, em **Restrições de API**, permita só a **Places API (New)**. Se o servidor tiver IP fixo, restrinja também por IP.
5. Cole a chave em **Configurações › Google Places** e use **Testar Places**.

**Custo aproximado** (confira os valores atuais em https://developers.google.com/maps/billing-and-pricing/pricing): telefone e site fazem a busca cair no nível *Text Search Enterprise*, cobrado por chamada, cerca de **US$ 35 por 1.000 chamadas**, com uma franquia mensal gratuita. Cada página de 20 resultados é uma chamada:

| Busca | Chamadas | Custo aproximado |
|---|---|---|
| 20 empresas | 1 | US$ 0,035 |
| 40 empresas | 2 | US$ 0,07 |
| 60 empresas | 3 | US$ 0,105 |

A mensagem de cada lead usa 1 ou 2 chamadas de texto à IA (centavos de fração por lead); sem chave de IA, um modelo fixo é usado sem custo. O botão **Testar Places** faz uma chamada mínima (só o campo `id`).

**Descartes automáticos** (o motivo fica na atividade do agente):

- `businessStatus` diferente de `OPERATIONAL`;
- sem telefone;
- rede/franquia: nome com uma marca da lista em Configurações, ou o mesmo site em empresas de cidades diferentes;
- já cadastrada (mesmo `place_id`).

**Telefone fixo** (no Brasil, celular tem 11 dígitos com 9 após o DDD) não é descartado: a empresa entra como **“Sem WhatsApp”**, aparece em Oportunidades e fica fora do disparo por WhatsApp.

A busca web da IA é só um complemento opcional (desligado por padrão) para achar Instagram e e-mail de quem não tem site.

## Fonte dos leads: empresas recém-abertas (CNPJ da Receita Federal)

Na tela **Agente**, o painel **Empresas recém-abertas** busca empresas pelo tempo de abertura usando os dados abertos de CNPJ da Receita Federal. É grátis e não precisa de chave.

1. **Baixar a base (administrador):** em "Atualizar base da Receita", informe as cidades com UF (ex.: `Petrolina/PE, Juazeiro/BA`) e quantos meses guardar (12, 24 ou 36).
   - Os arquivos da Receita têm cerca de 7 GB. O Prospecta lê direto do servidor e guarda só as empresas **ativas**, **matrizes**, dessas cidades e desse período.
   - A primeira vez leva por volta de 1 hora. A Receita publica uma base nova por mês, e o Prospecta confere a cada 6 horas e atualiza sozinho.
   - Se a Receita mudar o endereço da pasta pública, defina `PROSPECTA_RFB_TOKEN` com o código que aparece depois de `/index.php/s/` no link da pasta Dados > Cadastros > CNPJ.
2. **Buscar:** escolha a cidade, "abertas nos últimos" 1 a 36 meses, a atividade (opcional, procura na descrição do CNAE e no nome) e a quantidade. As mais novas vêm primeiro.
   - **Excluir MEI** (ligado por padrão).
   - **Pular contato de escritório contábil** (ligado por padrão): muitas empresas novas são registradas com o telefone ou o e-mail do contador. Um telefone ou e-mail que se repete em 3 ou mais empresas da base, ou um e-mail com "contab", "contador" e afins, não é usado. Se a empresa tiver outro contato, entra com ele; se não tiver, é descartada com o motivo.
   - Celular entra pronto para WhatsApp. Fixo entra como "Sem WhatsApp". Só e-mail entra para envio por e-mail.
3. **Nos leads:** o card mostra "Aberta há X meses", a data, o CNPJ e a razão social. Em Oportunidades, o filtro "Abertas há até 3/6/12 meses" mostra só essas, ordenadas da mais nova.

A mensagem usa o mesmo modelo de abordagem, a mesma aprovação em Disparos e a mesma proteção contra mensagem repetida. Essas buscas não contam no limite diário do Google Places.

## Diagnóstico e mensagem

Para cada lead novo, o servidor faz checagens determinísticas, sem IA, em segundo plano (5 sites por vez, 8 s de limite cada):

| Sinal | Regra |
|---|---|
| `site_nao_abre` | o site não responde ou responde com erro (status ≥ 400) |
| `so_rede_social` | o link aponta para Instagram, Facebook, Linktree ou wa.me |
| `sem_site` | sem site no Google |
| `sem_whatsapp_no_site` | o HTML não tem `wa.me` nem `api.whatsapp.com` |
| `nao_mobile` | o HTML não tem `<meta name="viewport">` |
| `sem_https` | o site só responde em http |

O `sinal_principal` segue essa ordem de prioridade. O diagnóstico só acessa endereços públicos (bloqueia IPs internos).

A IA recebe apenas nome, segmento, cidade, contato, sinal principal e a descrição dos seus serviços, e escreve no máximo 2 linhas terminando em pergunta. Se a mensagem passar de 280 caracteres ou tiver elogio, nota do Google ou pedido de reunião, ela é gerada de novo uma vez; se falhar de novo, entra um modelo fixo. O botão **Gerar nova mensagem** no card refaz o texto.

## Equipe

- O **administrador** configura chaves, canais e a equipe; **membros** prospectam, disparam e conversam.
- Todos usam o mesmo WhatsApp e o mesmo e-mail. No WhatsApp, cada mensagem sai com o nome de quem enviou em negrito no início (`*João:*`); no e-mail, como assinatura no fim. Os follow-ups saem com o nome de quem fez o primeiro disparo.
- Senhas são guardadas com `scrypt`; a sessão é um cookie `HttpOnly`. Depois de 5 senhas erradas, o login fica bloqueado por 5 minutos para aquele IP. Desativar um membro ou trocar a senha dele encerra as sessões abertas.

## Disparo, follow-up e conversas

- **E-mail:** SMTP para enviar e IMAP para ler as respostas (Gmail/Outlook exigem senha de app). As respostas são associadas pelo remetente e lidas sem marcar como lidas.
- **WhatsApp:** Evolution API v2 (`docker compose -f docker-compose.evolution.yml up -d`, depois crie a instância e leia o QR code em http://localhost:8080/manager). Use um número dedicado: disparo em massa por API não oficial pode levar a bloqueio.
- **Fila:** um envio por vez, com intervalo mínimo aleatorizado, janela de horário e limite diário configuráveis.
- **Follow-up:** quem não responde recebe a mensagem de follow-up a cada N dias, até o máximo configurado; depois vai para “Sem resposta”. Qualquer resposta interrompe a cadência.
- **Classificação:** respostas viram “Interessado”, “Recusou” ou “Respondeu” (palavras-chave e, se houver chave de IA, o modelo). Recusas cancelam a fila daquela empresa e movem para “Perdido”.
- **Tempo real:** a tela de Conversas recebe eventos do servidor (SSE); e-mail e WhatsApp são verificados a cada 30 s.

## Publicar na internet (deploy)

O código já tem login, mas o deploy ainda não foi feito. Ao publicar:

- coloque o Prospecta atrás de um proxy com **HTTPS** (Caddy ou Nginx) e rode o uvicorn com `--proxy-headers`, ouvindo só em `127.0.0.1`;
- informe o domínio em `PROSPECTA_HOSTS` (ex.: `PROSPECTA_HOSTS=crm.suaempresa.com.br`);
- crie o administrador antes de abrir o acesso, no próprio servidor: `python app.py criar-admin` (pela internet a tela de criação fica bloqueada);
- faça backup da pasta `data`.

## Dados

`data/prospecta.db` contém o CRM, os usuários e as configurações. Chaves e senhas de canais são criptografadas com Fernet; `data/secret.key` guarda a chave de criptografia. Faça backup da pasta `data` inteira; não a publique ou compartilhe. As chaves nunca são devolvidas à interface.

## Testes

```sh
.venv/bin/pip install pytest
.venv/bin/python -m pytest -q
node --check static/app.js
```

Os testes usam respostas simuladas das APIs, sem cobrança.

Documentação das integrações:
- https://developers.google.com/maps/documentation/places/web-service/text-search
- https://ai.google.dev/api/generate-content
- https://developers.openai.com/api/docs/guides/text

## Histórico do que já foi mandado

O banco (`data/`) não vai para o Git: ele guarda as senhas e as chaves. Para compartilhar o que já foi enviado, gere a planilha:

```
python exportar_historico.py --ignorar 5587999999999
```

Ela sai em `historico/envios.csv` (abre no Excel ou no Google Planilhas), com data, empresa, contato, tipo, status e o texto de cada mensagem. `--ignorar` tira números ou e-mails de teste.
