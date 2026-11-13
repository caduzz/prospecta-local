const $ = s => document.querySelector(s);
const stages = ['Novo','Qualificado','Em contato','Proposta','Ganho','Perdido'];
const outreachStates = ['Não contatado','Na fila','Aguardando','Respondeu','Interessado','Recusou','Sem resposta','Falha no envio'];
const inboxTabs = [['all','Todas',null],['replied','Respondidas',['Respondeu','Interessado']],['waiting','Aguardando',['Aguardando','Na fila']],['interested','Interessados',['Interessado']],['refused','Recusaram',['Recusou']],['silent','Sem resposta',['Sem resposta','Falha no envio']]];
const tone = {'Aguardando':'pending','Na fila':'saving','Respondeu':'saving','Interessado':'saved','Recusou':'error','Sem resposta':'','Falha no envio':'error','Não contatado':''};
let allLeads = [], conversations = [], summary = null, currentSettings, busy = false, currentLead = null, inboxTab = 'all', refreshTimer;
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const link = s => /^https?:\/\//i.test(s || '') ? esc(s) : '#';
const when = s => s ? new Date(s.replace(' ','T')+'Z').toLocaleString('pt-BR',{day:'2-digit',month:'2-digit',hour:'2-digit',minute:'2-digit'}) : '';
const badge = status => `<span class="badge ${tone[status] ?? ''}">${esc(status)}</span>`;
function notice(message, error = false) { const el = $('#notice'); el.textContent = message; el.className = error ? 'error' : ''; el.hidden = false; }
async function api(path, method='GET', data) {
  const res = await fetch('/api/'+path,{method,headers:{'Content-Type':'application/json','X-Prospecta':'local'},...(data !== undefined ? {body:JSON.stringify(data)} : {})});
  const json = await res.json();
  if(!res.ok) throw new Error(typeof json.detail === 'string' ? json.detail : 'Confira os campos preenchidos.');
  return json;
}
function page(name) { document.querySelectorAll('.page').forEach(p=>p.hidden=p.id!==name);document.querySelectorAll('.nav').forEach(b=>b.classList.toggle('active',b.dataset.page===name));$('#page-title').textContent={dashboard:'Oportunidades',inbox:'Conversas',dispatch:'Disparos',agent:'Agente de prospecção',settings:'Configurações'}[name];if(name==='inbox')refreshConversations().catch(()=>{});if(name==='dispatch')renderPicker(); }
document.querySelectorAll('.nav').forEach(b=>b.onclick=()=>page(b.dataset.page));
function sourceLinks(sources) { return `<div class="sources">${sources.map(s=>`<a href="${link(s.url)}" target="_blank" rel="noreferrer">${esc(s.title || 'Fonte')} ↗</a>`).join('')}</div>`; }
function contactChips(l) {
 const chips=[];
 if(l.email)chips.push(`<a href="mailto:${esc(l.email)}">✉ ${esc(l.email)}</a>`);
 if(l.phone)chips.push(`<a href="https://wa.me/${esc(l.phone)}" target="_blank" rel="noreferrer">☏ +${esc(l.phone)}</a>`);
 if(l.instagram)chips.push(`<a href="https://instagram.com/${esc(l.instagram)}" target="_blank" rel="noreferrer">◎ @${esc(l.instagram)}</a>`);
 if(l.website)chips.push(`<a href="${link(l.website)}" target="_blank" rel="noreferrer">⌂ Site ↗</a>`);
 return chips.length?`<div class="chips">${chips.join('')}</div>`:'<p class="meta">Nenhum contato encontrado ainda. Use Editar contatos para completar.</p>';
}
function renderLeads() {
 $('#total').textContent=allLeads.length;$('#waiting').textContent=allLeads.filter(l=>['Aguardando','Na fila'].includes(l.outreach)).length;$('#replied').textContent=allLeads.filter(l=>['Respondeu','Interessado'].includes(l.outreach)).length;$('#won').textContent=allLeads.filter(l=>l.stage==='Ganho').length;
 const filter=$('#filter').value.toLocaleLowerCase(); const stage=$('#stage-filter').value;
 const list=allLeads.filter(l=>(l.name+' '+l.segment+' '+l.location+' '+l.email+' '+l.instagram).toLocaleLowerCase().includes(filter)&&(!stage||l.stage===stage));
 $('#leads').innerHTML=list.length?list.map(l=>`<article class="lead"><div class="lead-top"><div><h3>${esc(l.name)} ${badge(l.outreach)}</h3><p class="meta">${esc([l.segment,l.location,l.contact].filter(Boolean).join(' · '))}</p></div><select data-lead="${l.id}" aria-label="Etapa de ${esc(l.name)}">${stages.map(s=>`<option ${s===l.stage?'selected':''}>${s}</option>`).join('')}</select></div>${contactChips(l)}${l.reason?`<p>${esc(l.reason)}</p>`:''}${sourceLinks(l.sources)}${l.draft?`<details><summary>Mensagem de abordagem</summary><div class="draft">${esc(l.draft)}</div><button class="secondary" data-copy="${l.id}">Copiar mensagem</button></details>`:''}<div class="lead-actions"><button class="secondary" data-edit="${l.id}">Editar contatos</button>${l.outreach!=='Não contatado'?`<button class="secondary" data-open="${l.id}">Abrir conversa →</button>`:''}</div></article>`).join(''):`<div class="empty"><div class="symbol">◈</div><h3>${allLeads.length?'Nenhum resultado neste filtro':'Um novo radar para o seu negócio'}</h3><p>${allLeads.length?'Tente outro nome ou etapa.':'Configure sua IA e inicie a primeira busca. As empresas encontradas aparecerão aqui.'}</p>${allLeads.length?'':'<button class="secondary" id="empty-start">Configurar meu agente →</button>'}</div>`;
 $('#empty-start')?.addEventListener('click',()=>page('settings'));
 document.querySelectorAll('[data-lead]').forEach(el=>el.onchange=async()=>{try{await api('leads/'+el.dataset.lead,'PATCH',{stage:el.value});await refreshLeads();}catch(e){notice(e.message,true);await refreshLeads();}});
 document.querySelectorAll('[data-copy]').forEach(el=>el.onclick=async()=>{try{await navigator.clipboard.writeText(allLeads.find(l=>l.id==el.dataset.copy).draft);notice('Mensagem copiada.');}catch{notice('Não foi possível copiar automaticamente. Selecione o texto da mensagem.',true);}});
 document.querySelectorAll('[data-edit]').forEach(el=>el.onclick=()=>editContacts(Number(el.dataset.edit)));
 document.querySelectorAll('[data-open]').forEach(el=>el.onclick=()=>{page('inbox');openThread(Number(el.dataset.open));});
 if(!$('#dispatch').hidden)renderPicker();
}
async function refreshLeads(){allLeads=await api('leads');renderLeads();}
function editContacts(id){
 const l=allLeads.find(x=>x.id===id) || (currentLead?.id===id?currentLead:null);if(!l)return;
 const f=$('#contact-form');f.dataset.id=id;$('#contact-title').textContent='Contatos · '+l.name;
 for(const name of ['email','phone','instagram','contact','draft'])f.elements[name].value=l[name]||'';
 $('#contact-dialog').showModal();
}
$('#close-contact').onclick=()=>$('#contact-dialog').close();
$('#contact-form').onsubmit=async e=>{e.preventDefault();const f=e.target;const button=e.submitter;button.disabled=true;try{await api('leads/'+f.dataset.id,'PATCH',Object.fromEntries(new FormData(f)));$('#contact-dialog').close();notice('Contatos atualizados.');await refreshAll();}catch(err){notice(err.message,true);}finally{button.disabled=false;}};

/* Conversas */
function tabMatches(c, tab){const states=inboxTabs.find(t=>t[0]===tab)[2];return !states || states.includes(c.outreach);}
function renderTabs(){
 $('#inbox-tabs').innerHTML=inboxTabs.map(([key,label])=>{const n=conversations.filter(c=>tabMatches(c,key)).length;return `<button role="tab" aria-selected="${key===inboxTab}" class="tab ${key===inboxTab?'active':''}" data-tab="${key}">${label} <span>${n}</span></button>`;}).join('');
 document.querySelectorAll('[data-tab]').forEach(b=>b.onclick=()=>{inboxTab=b.dataset.tab;renderTabs();renderThreads();});
}
function renderThreads(){
 const q=$('#inbox-search').value.toLocaleLowerCase();
 const list=conversations.filter(c=>tabMatches(c,inboxTab)&&c.name.toLocaleLowerCase().includes(q));
 $('#threads').innerHTML=list.length?list.map(c=>`<button class="thread-item ${currentLead?.id===c.id?'active':''} ${c.unread?'unread':''}" data-thread="${c.id}"><span class="thread-top"><strong>${esc(c.name)}</strong><time>${esc(when(c.last_at))}</time></span><span class="thread-preview">${c.last_direction==='out'?'Você: ':''}${esc(c.last_body.slice(0,90))}</span><span class="thread-top">${badge(c.outreach)}<small>${c.last_channel==='email'?'✉ E-mail':'☏ WhatsApp'}${c.unread?` · <b>${c.unread} nova${c.unread>1?'s':''}</b>`:''}</small></span></button>`).join(''):`<div class="empty small"><p>${conversations.length?'Nenhuma conversa neste filtro.':'Nenhuma conversa ainda. Comece em Disparos.'}</p></div>`;
 document.querySelectorAll('[data-thread]').forEach(b=>b.onclick=()=>openThread(Number(b.dataset.thread)));
}
async function refreshConversations(){conversations=await api('conversations');renderTabs();renderThreads();}
async function openThread(id, keepDraft=false){
 const draft=keepDraft?$('#composer textarea')?.value:'';
 const {lead,messages}=await api('leads/'+id+'/messages');currentLead=lead;
 const channels=[lead.email?'email':null,lead.phone?'whatsapp':null].filter(Boolean);const preferred=channels.includes(lead.channel)?lead.channel:channels[0];
 const followup=lead.outreach==='Aguardando'&&lead.next_followup?`<p class="hint">Próximo follow-up: ${esc(when(lead.next_followup))} · ${lead.attempts} de ${currentSettings.followup_max} enviados</p>`:'';
 $('#thread').innerHTML=`<div class="thread-head"><div><h2>${esc(lead.name)}</h2><p class="meta">${esc([lead.segment,lead.location,lead.contact].filter(Boolean).join(' · '))}</p>${contactChips(lead)}${followup}</div><div class="thread-controls"><label>Status<select id="thread-outreach">${outreachStates.map(s=>`<option ${s===lead.outreach?'selected':''}>${s}</option>`).join('')}</select></label><label>Etapa<select id="thread-stage">${stages.map(s=>`<option ${s===lead.stage?'selected':''}>${s}</option>`).join('')}</select></label><button class="secondary" id="thread-edit">Editar contatos</button></div></div><div class="messages" id="messages">${messages.length?messages.map(m=>`<div class="bubble ${m.direction} ${m.status==='cancelado'?'muted':''}">${m.subject&&m.direction==='in'?`<strong>${esc(m.subject)}</strong>`:''}<p>${esc(m.body)}</p><small>${m.channel==='email'?'✉':'☏'} ${esc(when(m.sent||m.created))} · ${esc({inicial:'1ª mensagem',followup:'follow-up',manual:'manual',resposta:'resposta'}[m.kind]||m.kind)} · ${esc(m.status)}${m.error?` — ${esc(m.error)}`:''}</small></div>`).join(''):'<div class="empty small"><p>Nenhuma mensagem ainda.</p></div>'}</div>${channels.length?`<form id="composer" class="composer"><select name="channel" aria-label="Canal">${channels.map(c=>`<option value="${c}" ${c===preferred?'selected':''}>${c==='email'?'✉ E-mail':'☏ WhatsApp'}</option>`).join('')}</select><textarea name="body" rows="2" required maxlength="4000" placeholder="Escreva uma resposta… (Ctrl+Enter envia)"></textarea><button class="primary" type="submit">Enviar</button></form>`:'<p class="hint composer">Cadastre e-mail ou WhatsApp para conversar com esta empresa.</p>'}`;
 const box=$('#messages');box.scrollTop=box.scrollHeight;
 if(draft)$('#composer textarea').value=draft;
 $('#thread-outreach').onchange=async e=>{try{await api('leads/'+id,'PATCH',{outreach:e.target.value});await refreshAll();}catch(err){notice(err.message,true);}};
 $('#thread-stage').onchange=async e=>{try{await api('leads/'+id,'PATCH',{stage:e.target.value});await refreshLeads();}catch(err){notice(err.message,true);}};
 $('#thread-edit').onclick=()=>editContacts(id);
 const composer=$('#composer');
 if(composer){composer.body.onkeydown=e=>{if(e.key==='Enter'&&(e.ctrlKey||e.metaKey))composer.requestSubmit();};composer.onsubmit=async e=>{e.preventDefault();const b=composer.querySelector('button');b.disabled=true;b.textContent='Enviando…';try{await api('leads/'+id+'/messages','POST',Object.fromEntries(new FormData(composer)));await refreshAll();}catch(err){notice(err.message,true);b.disabled=false;b.textContent='Enviar';}};}
 const item=conversations.find(c=>c.id===id);if(item){item.unread=0;}renderThreads();updateUnread();
}
$('#inbox-search').oninput=renderThreads;

/* Disparos */
function renderPicker(){
 const f=$('#dispatch-form');const channel=f.elements.channel.value;const field=channel==='email'?'email':'phone';
 $('#subject-field').hidden=channel!=='email';
 const selected=new Set([...document.querySelectorAll('[data-pick]:checked')].map(x=>Number(x.dataset.pick)));
 const list=allLeads.filter(l=>l[field]&&['Não contatado','Falha no envio'].includes(l.outreach));
 const missing=allLeads.filter(l=>!l[field]&&l.outreach==='Não contatado').length;
 $('#pick-list').innerHTML=list.length?list.map(l=>`<label class="pick"><input type="checkbox" data-pick="${l.id}" ${selected.has(l.id)?'checked':''}><span><strong>${esc(l.name)}</strong><small>${esc(channel==='email'?l.email:'+'+l.phone)}${l.draft?'':' · sem mensagem da IA'}${l.outreach==='Falha no envio'?' · falhou antes':''}</small></span></label>`).join('')+(missing?`<p class="hint">${missing} ${missing===1?'empresa':'empresas'} sem ${channel==='email'?'e-mail':'WhatsApp'} não aparecem aqui.</p>`:''):`<div class="empty small"><p>Nenhuma empresa pronta para ${channel==='email'?'e-mail':'WhatsApp'}. Rode o agente de prospecção ou complete os contatos em Oportunidades.</p></div>`;
 document.querySelectorAll('[data-pick]').forEach(x=>x.onchange=updatePickCount);updatePickCount();
}
function updatePickCount(){const all=[...document.querySelectorAll('[data-pick]')];const n=all.filter(x=>x.checked).length;$('#pick-count').textContent=n+' selecionada'+(n===1?'':'s');$('#pick-all').checked=all.length>0&&n===all.length;}
$('#pick-all').onchange=e=>{document.querySelectorAll('[data-pick]').forEach(x=>x.checked=e.target.checked);updatePickCount();};
$('#dispatch-form').addEventListener('change',e=>{if(e.target.name==='channel')renderPicker();});
$('#dispatch-form').onsubmit=async e=>{
 e.preventDefault();const f=e.target;const ids=[...document.querySelectorAll('[data-pick]:checked')].map(x=>Number(x.dataset.pick));
 if(!ids.length){notice('Selecione ao menos uma empresa.',true);return;}
 const template=f.elements.template.value.trim();const withoutText=ids.filter(id=>!template&&!allLeads.find(l=>l.id===id)?.draft).length;
 if(!confirm(`Colocar ${ids.length} mensagens na fila de ${f.elements.channel.value==='email'?'e-mail':'WhatsApp'}?${withoutText?`\n${withoutText} empresas sem mensagem da IA serão ignoradas.`:''}\nO envio começa respeitando o intervalo e o horário configurados.`))return;
 const b=$('#dispatch-button');b.disabled=true;
 try{const r=await api('dispatch','POST',{lead_ids:ids,channel:f.elements.channel.value,template,subject:f.elements.subject.value});notice(r.message);await refreshAll();}catch(err){notice(err.message,true);}finally{b.disabled=false;}
};
$('#cancel-queue').onclick=async()=>{if(!confirm('Cancelar todas as mensagens que ainda não foram enviadas?'))return;try{notice((await api('queue/cancel','POST',{})).message);await refreshAll();}catch(e){notice(e.message,true);}};
function renderQueue(){
 if(!summary)return;const s=currentSettings;const errors=Object.values(summary.errors||{});
 const next=summary.next_send&&summary.queued?`<p class="hint">Próximo envio a partir de ${esc(when(summary.next_send))}.</p>`:'';
 $('#queue-status').innerHTML=`<div class="mini-stats"><div><strong>${summary.queued}</strong><span>na fila</span></div><div><strong>${summary.sent_today}/${s.send_daily_limit}</strong><span>enviadas hoje</span></div><div><strong>${summary.counts['Aguardando']}</strong><span>aguardando</span></div><div><strong>${summary.counts['Respondeu']+summary.counts['Interessado']}</strong><span>responderam</span></div></div>
 ${summary.worker?'':'<p class="key-feedback error">O envio automático está desligado neste processo.</p>'}
 ${summary.in_window?'':`<p class="key-feedback pending">Fora do horário de envio (${s.send_hour_start}h às ${s.send_hour_end}h). A fila continua no próximo horário.</p>`}
 ${errors.map(e=>`<p class="key-feedback error">${esc(e)}</p>`).join('')}${next}
 ${summary.queue.length?`<ol class="queue">${summary.queue.map(q=>`<li><strong>${esc(q.name)}</strong> <small>${q.channel==='email'?'✉':'☏'} ${esc({inicial:'1ª mensagem',followup:'follow-up'}[q.kind]||q.kind)}</small></li>`).join('')}</ol>`:'<p class="hint">Nada aguardando envio.</p>'}
 ${summary.failed.length?`<h3 class="subhead">Últimas falhas</h3>${summary.failed.map(f=>`<p class="hint"><strong>${esc(f.name)}</strong> · ${esc(f.error)}</p>`).join('')}`:''}`;
 $('#cancel-queue').hidden=!summary.queued;
}
async function refreshSummary(){summary=await api('outreach');renderQueue();updateUnread();}
function updateUnread(){const n=conversations.length?conversations.reduce((a,c)=>a+(c.unread||0),0):(summary?.unread||0);const el=$('#unread-badge');el.hidden=!n;el.textContent=n;}
async function refreshAll(){await Promise.all([refreshLeads(),refreshSummary(),refreshConversations()]);if(currentLead&&!$('#inbox').hidden)await openThread(currentLead.id,true);}
function scheduleRefresh(){clearTimeout(refreshTimer);refreshTimer=setTimeout(()=>refreshAll().catch(()=>{}),250);}
function connectEvents(){
 const source=new EventSource('/api/events');
 source.onopen=()=>{$('#live-badge').textContent='● Ao vivo';$('#live-badge').className='badge saved';$('#live-status').textContent='Conectado em tempo real';};
 source.onerror=()=>{$('#live-badge').textContent='Reconectando…';$('#live-badge').className='badge pending';};
 source.onmessage=e=>{const ev=JSON.parse(e.data);if(ev.type==='message')notice(`Nova resposta de ${ev.name} · ${ev.outreach}: “${ev.preview}”`);if(ev.type==='sent'&&ev.error)notice(`Falha ao enviar para ${ev.name}: ${ev.error}`,true);scheduleRefresh();};
}

/* Configurações */
const settingFields=['company','offers','daily_limit','openai_model','gemini_model','smtp_host','smtp_port','smtp_user','smtp_from','imap_host','imap_port','evolution_url','evolution_instance','email_subject','followup_text','followup_max','followup_days','send_interval','send_daily_limit','send_hour_start','send_hour_end'];
const numberFields=['daily_limit','smtp_port','imap_port','followup_max','followup_days','send_interval','send_daily_limit','send_hour_start','send_hour_end'];
function fillSettings(s){currentSettings=s;const f=$('#settings-form');for(const name of settingFields)f.elements[name].value=s[name] ?? '';f.elements.provider.value=s.provider;for(const p of ['openai','gemini']){f.elements[p+'_key'].value='';f.elements['remove_'+p].checked=false;keyFeedback(p, s[p+'_configured'] ? '✓ Chave salva neste notebook. O campo fica vazio para proteger sua chave.' : 'Nenhuma chave salva. Cole a chave e clique em Salvar configurações.', s[p+'_configured'] ? 'saved' : '');f.elements[p+'_key'].placeholder=s[p+'_configured']?'Chave já salva · cole outra para substituir':'Cole sua chave de API';}for(const p of ['smtp','evolution']){f.elements[p+'_key'].value='';f.elements['remove_'+p].checked=false;f.elements[p+'_key'].placeholder=s[p+'_configured']?'Já salva · preencha para substituir':'Cole aqui';const b=$('#'+p+'-status');b.textContent=s[p+'_configured']?'✓ Configurado':'Não configurado';b.className='badge '+(s[p+'_configured']?'saved':'');}$('#provider-badge').textContent=(s.provider==='gemini'?'Gemini':'OpenAI')+' · '+(s[s.provider+'_configured']?'chave salva':'sem chave');}
function keyFeedback(provider, message, state='') {
 const el=$('#'+provider+'-feedback');el.textContent=message;el.className='key-feedback '+state;
 const badge=$('#'+provider+'-status');badge.textContent={saved:'✓ Chave salva',pending:'Não salvo',saving:'Salvando…',error:'Não foi salvo'}[state] || 'Sem chave';badge.className='badge '+state;
}
function saveFeedback(message,state='') { const el=$('#save-feedback');el.textContent=message;el.className='key-feedback '+state; }
$('#settings-form').addEventListener('input',e=>{
 saveFeedback('Há alterações não salvas. Clique em Salvar configurações.','pending');
 for(const p of ['openai','gemini']) {
  const f=e.currentTarget;
  if(e.target.name===p+'_key'||e.target.name==='remove_'+p) {
   if(f.elements['remove_'+p].checked)keyFeedback(p,'A chave será removida ao salvar.','pending');
   else if(f.elements[p+'_key'].value.trim())keyFeedback(p,'Chave preenchida, mas ainda não salva.','pending');
   else keyFeedback(p,currentSettings[p+'_configured']?'✓ Sua chave salva será mantida.':'Nenhuma chave salva.',currentSettings[p+'_configured']?'saved':'');
  }
 }
});
$('#settings-form').onsubmit=async e=>{
 e.preventDefault();const f=e.target;const button=e.submitter || f.querySelector('[type="submit"]');
 const data=Object.fromEntries(new FormData(f));numberFields.forEach(n=>data[n]=Number(data[n]));data.revision=currentSettings.revision || 0;
 for(const p of ['openai','gemini','smtp','evolution'])data['remove_'+p]=f.elements['remove_'+p].checked;
 const changed=['openai','gemini'].filter(p=>data[p+'_key'].trim() || data['remove_'+p]);
 const controls=[...f.elements];controls.forEach(el=>el.disabled=true);button.textContent='Salvando…';saveFeedback('Salvando configurações neste notebook…','saving');
 changed.forEach(p=>keyFeedback(p,'Salvando alteração da chave…','saving'));
 try{
  fillSettings(await api('settings','PUT',data));
  changed.forEach(p=>keyFeedback(p,data['remove_'+p]?'Chave removida com sucesso.':'✓ Chave salva com sucesso. Use Testar IA para validar o acesso.',data['remove_'+p]?'':'saved'));
  saveFeedback('✓ Configurações salvas com sucesso. Provedor ativo: '+(data.provider==='gemini'?'Gemini':'OpenAI')+'.','saved');
  notice('Configurações salvas.');refreshSummary().catch(()=>{});
 }catch(error){
  saveFeedback('Não foi possível salvar: '+error.message,'error');
  changed.forEach(p=>keyFeedback(p,'Não foi possível salvar a alteração. Sua chave anterior foi mantida; tente novamente.','error'));
  notice(error.message,true);
 }finally{controls.forEach(el=>el.disabled=false);button.textContent='Salvar configurações';}
};
$('#test-key').onclick=async()=>{const b=$('#test-key');b.disabled=true;b.textContent='Testando…';try{const r=await api('test','POST',{});notice(r.message);saveFeedback(r.message,'saved');}catch(e){notice(e.message,true);saveFeedback(e.message,'error');}finally{b.disabled=false;b.textContent='Testar IA';}};
document.querySelectorAll('[data-test-channel]').forEach(b=>b.onclick=async()=>{const label=b.textContent;b.disabled=true;b.textContent='Testando…';try{const r=await api('channels/test','POST',{channel:b.dataset.testChannel});notice(r.message);saveFeedback(r.message,'saved');}catch(e){notice(e.message+' Salve as configurações antes de testar.',true);saveFeedback(e.message,'error');}finally{b.disabled=false;b.textContent=label;}});

/* Agente */
$('#campaign').onsubmit=async e=>{e.preventDefault();$('#run-button').disabled=true;try{const data=Object.fromEntries(new FormData(e.target));data.limit=Number(data.limit);await api('runs','POST',data);notice('Busca iniciada. Você pode acompanhar o progresso abaixo.');await refreshRuns();}catch(e){notice(e.message,true);$('#run-button').disabled=false;}};
async function refreshRuns(){const runs=await api('runs');const wasBusy=busy;busy=runs.some(r=>r.status==='executando');$('#run-button').disabled=busy;$('#run-button').textContent=busy?'Pesquisando…':'✧ Iniciar prospecção';$('#runs').innerHTML=runs.length?runs.map(r=>{let q;try{q=JSON.parse(r.query);}catch{q={segment:r.query,location:''};}const tokens=r.usage.total_tokens??r.usage.totalTokenCount;return `<article class="run"><div class="run-head"><strong>${esc(q.segment)}</strong><span class="badge">${esc(r.status)}</span></div><time>${esc(new Date(r.created.replace(' ','T')+'Z').toLocaleString('pt-BR'))} · ${esc(r.provider)}</time><p>${esc(q.location)} · ${esc(r.model)}</p><p>${esc(r.message)}</p>${tokens?`<p>${esc(tokens)} tokens informados pelo provedor</p>`:''}${sourceLinks(r.sources)}${r.search_html?`<iframe sandbox="allow-popups allow-popups-to-escape-sandbox" title="Sugestões da busca Google" srcdoc="${esc(r.search_html)}"></iframe>`:''}</article>`;}).join(''):'<div class="empty"><div class="symbol">✧</div><h3>Pronto para pesquisar</h3><p>Sua primeira execução aparecerá aqui.</p></div>';if(wasBusy&&!busy)await refreshLeads();}
$('#stage-filter').insertAdjacentHTML('beforeend',stages.map(s=>`<option>${s}</option>`).join(''));$('#filter').oninput=renderLeads;$('#stage-filter').onchange=renderLeads;
$('#new-lead').onclick=()=>$('#lead-dialog').showModal();$('#close-dialog').onclick=()=>$('#lead-dialog').close();
$('#lead-form').onsubmit=async e=>{e.preventDefault();e.submitter.disabled=true;try{await api('leads','POST',Object.fromEntries(new FormData(e.target)));$('#lead-dialog').close();e.target.reset();await refreshLeads();notice('Empresa adicionada ao funil.');}catch(e){notice(e.message,true);}finally{e.submitter.disabled=false;}};
async function init(){try{fillSettings(await api('settings'));await Promise.all([refreshLeads(),refreshRuns(),refreshSummary(),refreshConversations()]);connectEvents();}catch(e){notice('Não foi possível carregar o sistema: '+e.message,true);}}
init();setInterval(()=>{if(!document.hidden){refreshRuns().catch(()=>{});refreshSummary().catch(()=>{});}},5000);
