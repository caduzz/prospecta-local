const $ = s => document.querySelector(s);
const stages = ['Novo','Qualificado','Em contato','Proposta','Ganho','Perdido'];
const outreachStates = ['Não contatado','Para aprovar','Na fila','Aguardando','Respondeu','Interessado','Recusou','Sem resposta','Falha no envio','Sem WhatsApp','Já contatado'];
const signalText = {site_nao_abre:'o site não abre',so_rede_social:'o link leva só para rede social',sem_site:'não tem site cadastrado',sem_whatsapp_no_site:'o site não tem botão de WhatsApp',nao_mobile:'o site não é adaptado para celular',sem_https:'o site não tem https'};
const signalShort = {site_nao_abre:'Site não abre',so_rede_social:'Só rede social',sem_site:'Sem site',sem_whatsapp_no_site:'Sem WhatsApp no site',nao_mobile:'Não é mobile',sem_https:'Sem https'};
const inboxTabs = [['all','Todas',null],['replied','Respondidas',['Respondeu','Interessado']],['waiting','Aguardando',['Aguardando','Na fila']],['interested','Interessados',['Interessado']],['refused','Recusaram',['Recusou']],['silent','Sem resposta',['Sem resposta','Falha no envio']]];
const tone = {'Aguardando':'pending','Na fila':'saving','Respondeu':'saving','Interessado':'saved','Recusou':'error','Sem resposta':'','Falha no envio':'error','Não contatado':'','Sem WhatsApp':'','Para aprovar':'pending','Já contatado':''};
let allLeads = [], conversations = [], summary = null, currentSettings, busy = false, currentLead = null, inboxTab = 'all', refreshTimer, me = null, eventSource = null, started = false;
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const link = s => /^https?:\/\//i.test(s || '') ? esc(s) : '#';
const when = s => s ? new Date(s.replace(' ','T')+'Z').toLocaleString('pt-BR',{day:'2-digit',month:'2-digit',hour:'2-digit',minute:'2-digit'}) : '';
const badge = status => `<span class="badge ${tone[status] ?? ''}">${esc(status)}</span>`;
function notice(message, error = false) { const el = $('#notice'); el.textContent = message; el.className = error ? 'error' : ''; el.hidden = false; }
async function api(path, method='GET', data) {
  const res = await fetch('/api/'+path,{method,headers:{'Content-Type':'application/json','X-Prospecta':'local'},...(data !== undefined ? {body:JSON.stringify(data)} : {})});
  const json = await res.json();
  if(res.status===401&&!path.startsWith('auth/')){showAuth();throw new Error(json.detail);}
  if(!res.ok) throw new Error(typeof json.detail === 'string' ? json.detail : 'Confira os campos preenchidos.');
  return json;
}
function page(name) { document.querySelectorAll('.page').forEach(p=>p.hidden=p.id!==name);document.querySelectorAll('.nav').forEach(b=>b.classList.toggle('active',b.dataset.page===name));$('#page-title').textContent={dashboard:'Oportunidades',inbox:'Conversas',dispatch:'Disparos',agent:'Agente de prospecção',team:'Equipe',settings:'Configurações'}[name];if(name==='team')refreshTeam().catch(e=>notice(e.message,true));if(name==='inbox')refreshConversations().catch(()=>{});if(name==='dispatch')renderPicker(); }
document.querySelectorAll('.nav').forEach(b=>b.onclick=()=>page(b.dataset.page));
function sourceLinks(sources) { return `<div class="sources">${sources.map(s=>`<a href="${link(s.url)}" target="_blank" rel="noreferrer">${esc(s.title || 'Fonte')} ↗</a>`).join('')}</div>`; }
function contactChips(l) {
 const chips=[];
 if(l.email)chips.push(`<a href="mailto:${esc(l.email)}">✉ ${esc(l.email)}</a>`);
 if(l.phone)chips.push(l.tem_whatsapp?`<a href="https://wa.me/${esc(l.phone)}" target="_blank" rel="noreferrer">☏ +${esc(l.phone)}</a>`:`<a href="tel:+${esc(l.phone)}">☎ +${esc(l.phone)} · fixo</a>`);
 if(l.instagram)chips.push(`<a href="https://instagram.com/${esc(l.instagram)}" target="_blank" rel="noreferrer">◎ @${esc(l.instagram)}</a>`);
 if(l.website)chips.push(`<a href="${link(l.website)}" target="_blank" rel="noreferrer">⌂ Site ↗</a>`);
 return chips.length?`<div class="chips">${chips.join('')}</div>`:'<p class="meta">Nenhum contato encontrado ainda. Use Editar contatos para completar.</p>';
}
function diagnosis(l){
 if(l.cnpj)return `<p class="signal">Aberta ${ageText(l.data_abertura)} · ${fmtDate(l.data_abertura)}${l.mei?' · MEI':''}</p>`;
 if(!l.diagnostico)return l.place_id?'<p class="meta">Verificando o site no Google…</p>':'';
 let d={};try{d=JSON.parse(l.diagnostico);}catch{}
 const others=Object.keys(signalShort).filter(k=>d[k]&&k!==l.sinal_principal);
 return `<p class="signal">No Google: ${l.sinal_principal?esc(signalText[l.sinal_principal]):'nenhum problema encontrado no site'}</p>${others.length?`<div class="signal-badges">${others.map(k=>`<span class="badge">${signalShort[k]}</span>`).join('')}</div>`:''}`;
}
function renderLeads() {
 $('#total').textContent=allLeads.length;$('#waiting').textContent=allLeads.filter(l=>['Aguardando','Na fila'].includes(l.outreach)).length;$('#replied').textContent=allLeads.filter(l=>['Respondeu','Interessado'].includes(l.outreach)).length;$('#won').textContent=allLeads.filter(l=>l.stage==='Ganho').length;
 const filter=$('#filter').value.toLocaleLowerCase(); const stage=$('#stage-filter').value; const age=Number($('#age-filter').value||0);
 let list=allLeads.filter(l=>(l.name+' '+l.segment+' '+l.location+' '+l.email+' '+l.instagram).toLocaleLowerCase().includes(filter)&&(!stage||l.stage===stage)&&(!age||(l.data_abertura&&monthsSince(l.data_abertura)<=age)));
 if(age)list=list.sort((a,b)=>b.data_abertura.localeCompare(a.data_abertura));
 $('#leads').innerHTML=list.length?list.map(l=>`<article class="lead"><div class="lead-top"><div><h3>${esc(l.name)} ${badge(l.outreach)}</h3><p class="meta">${esc([l.segment,l.address||l.location,l.contact].filter(Boolean).join(' · '))}</p></div><select data-lead="${l.id}" aria-label="Etapa de ${esc(l.name)}">${stages.map(s=>`<option ${s===l.stage?'selected':''}>${s}</option>`).join('')}</select></div>${contactChips(l)}${diagnosis(l)}${l.motivo_descarte?`<p class="meta">${esc(l.motivo_descarte)}</p>`:''}${l.reason?`<p>${esc(l.reason)}</p>`:''}${sourceLinks(l.sources)}${l.draft?`<details><summary>Mensagem de abordagem</summary><div class="draft">${esc(l.draft)}</div><button class="secondary" data-copy="${l.id}">Copiar mensagem</button> <small class="meta">${esc(l.draft_status||'')}</small></details>`:''}<div class="lead-actions"><button class="secondary" data-edit="${l.id}">Editar contatos</button>${l.diagnostico?`<button class="secondary" data-redraft="${l.id}">Gerar nova mensagem</button>`:''}${l.outreach!=='Não contatado'?`<button class="secondary" data-open="${l.id}">Abrir conversa →</button>`:(l.email||(l.phone&&l.tem_whatsapp))?`<button class="primary" data-manual="${l.id}">➤ Enviar agora</button>`:''}</div></article>`).join(''):`<div class="empty"><div class="symbol">◈</div><h3>${allLeads.length?'Nenhum resultado neste filtro':'Um novo radar para o seu negócio'}</h3><p>${allLeads.length?'Tente outro nome ou etapa.':'Configure sua IA e inicie a primeira busca. As empresas encontradas aparecerão aqui.'}</p>${allLeads.length?'':'<button class="secondary" id="empty-start">Configurar meu agente →</button>'}</div>`;
 $('#empty-start')?.addEventListener('click',()=>page('settings'));
 document.querySelectorAll('[data-lead]').forEach(el=>el.onchange=async()=>{try{await api('leads/'+el.dataset.lead,'PATCH',{stage:el.value});await refreshLeads();}catch(e){notice(e.message,true);await refreshLeads();}});
 document.querySelectorAll('[data-copy]').forEach(el=>el.onclick=async()=>{try{await navigator.clipboard.writeText(allLeads.find(l=>l.id==el.dataset.copy).draft);notice('Mensagem copiada.');}catch{notice('Não foi possível copiar automaticamente. Selecione o texto da mensagem.',true);}});
 document.querySelectorAll('[data-edit]').forEach(el=>el.onclick=()=>editContacts(Number(el.dataset.edit)));
 document.querySelectorAll('[data-redraft]').forEach(el=>el.onclick=async()=>{el.disabled=true;el.textContent='Gerando…';try{notice((await api('leads/'+el.dataset.redraft+'/draft','POST',{})).message);await refreshLeads();}catch(e){notice(e.message,true);el.disabled=false;el.textContent='Gerar nova mensagem';}});
 document.querySelectorAll('[data-open]').forEach(el=>el.onclick=()=>{page('inbox');openThread(Number(el.dataset.open));});
 document.querySelectorAll('[data-manual]').forEach(el=>el.onclick=()=>{page('inbox');openThread(Number(el.dataset.manual),false,true);});
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
async function openThread(id, keepDraft=false, prefill=false){
 const draft=keepDraft?$('#composer textarea')?.value:'';
 const {lead,messages}=await api('leads/'+id+'/messages');currentLead=lead;
 const channels=[lead.email?'email':null,lead.phone&&lead.tem_whatsapp?'whatsapp':null].filter(Boolean);const preferred=channels.includes(lead.channel)?lead.channel:channels[0];
 const followup=lead.outreach==='Aguardando'&&lead.next_followup?`<p class="hint">Próximo follow-up: ${esc(when(lead.next_followup))} · ${lead.attempts} de ${currentSettings.followup_max} enviados</p>`:'';
 $('#thread').innerHTML=`<div class="thread-head"><div><h2>${esc(lead.name)}</h2><p class="meta">${esc([lead.segment,lead.location,lead.contact].filter(Boolean).join(' · '))}</p>${contactChips(lead)}${followup}</div><div class="thread-controls"><label>Status<select id="thread-outreach">${outreachStates.map(s=>`<option ${s===lead.outreach?'selected':''}>${s}</option>`).join('')}</select></label><label>Etapa<select id="thread-stage">${stages.map(s=>`<option ${s===lead.stage?'selected':''}>${s}</option>`).join('')}</select></label><button class="secondary" id="thread-edit">Editar contatos</button></div></div><div class="messages" id="messages">${messages.length?messages.map(m=>`<div class="bubble ${m.direction} ${m.status==='cancelado'?'muted':''}">${m.subject&&m.direction==='in'?`<strong>${esc(m.subject)}</strong>`:''}<p>${esc(m.body)}</p><small>${m.user_name&&m.direction==='out'?`<b>${esc(m.user_name)}</b> · `:''}${m.channel==='email'?'✉':'☏'} ${esc(when(m.sent||m.created))} · ${esc({inicial:'1ª mensagem',followup:'follow-up',manual:'manual',resposta:'resposta'}[m.kind]||m.kind)} · ${esc(m.status)}${m.error?` — ${esc(m.error)}`:''}</small></div>`).join(''):'<div class="empty small"><p>Nenhuma mensagem ainda.</p></div>'}</div>${channels.length?`<form id="composer" class="composer"><select name="channel" aria-label="Canal">${channels.map(c=>`<option value="${c}" ${c===preferred?'selected':''}>${c==='email'?'✉ E-mail':'☏ WhatsApp'}</option>`).join('')}</select><textarea name="body" rows="2" required maxlength="4000" placeholder="Escreva uma resposta… (Ctrl+Enter envia)"></textarea><button class="primary" type="submit">Enviar</button></form>`:'<p class="hint composer">Cadastre e-mail ou WhatsApp para conversar com esta empresa.</p>'}`;
 const box=$('#messages');box.scrollTop=box.scrollHeight;
 if(draft)$('#composer textarea').value=draft;
 if(prefill&&$('#composer')){const t=$('#composer textarea');t.value=lead.draft||'';t.focus();t.setSelectionRange(t.value.length,t.value.length);notice('Revise a mensagem e clique em Enviar: ela sai na hora, sem esperar a fila. Os follow-ups começam a contar a partir deste envio.');}
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
 const list=allLeads.filter(l=>l[field]&&(channel==='email'||l.tem_whatsapp)&&['Não contatado','Falha no envio'].includes(l.outreach));
 const missing=allLeads.filter(l=>(!l[field]||(channel==='whatsapp'&&!l.tem_whatsapp))&&['Não contatado','Sem WhatsApp'].includes(l.outreach)).length;
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
 ${summary.worker?'':'<p class="key-feedback error">O envio automático está desligado neste processo.</p>'}${summary.auto_dispatch?'<p class="key-feedback saved">Disparo automático ligado: leads novos com WhatsApp aparecem em “Aguardando sua aprovação”.</p>':''}
 ${summary.in_window?'':`<p class="key-feedback pending">Fora do horário de envio (${s.send_hour_start}h às ${s.send_hour_end}h). A fila continua no próximo horário.</p>`}
 ${errors.map(e=>`<p class="key-feedback error">${esc(e)}</p>`).join('')}${next}
 ${summary.queue.length?`<ol class="queue">${summary.queue.map(q=>`<li><strong>${esc(q.name)}</strong> <small>${q.channel==='email'?'✉':'☏'} ${esc({inicial:'1ª mensagem',followup:'follow-up'}[q.kind]||q.kind)}</small></li>`).join('')}</ol>`:'<p class="hint">Nada aguardando envio.</p>'}
 ${summary.failed.length?`<h3 class="subhead">Últimas falhas</h3>${summary.failed.map(f=>`<p class="hint"><strong>${esc(f.name)}</strong> · ${esc(f.error)}</p>`).join('')}`:''}`;
 $('#cancel-queue').hidden=!summary.queued;
}
async function refreshSummary(){summary=await api('outreach');renderQueue();updateUnread();const b=$('#approval-badge');b.hidden=!summary.approvals;b.textContent=summary.approvals;}
const saudacaoAgora=()=>{const h=new Date().getHours();return h>=5&&h<12?'bom dia':h<18&&h>=12?'boa tarde':'boa noite';};
function spinText(t){let prev;do{prev=t;t=t.replace(/\{([^{}]*\|[^{}]*)\}/g,(_,o)=>{const p=o.split('|');return p[Math.floor(Math.random()*p.length)].trim();});}while(t!==prev);return t;}
function updateFirstPreview(){const t=spinText($('#settings-form').elements.first_message.value);$('#first-preview').textContent='Exemplo: '+t.replaceAll('{saudacao}',saudacaoAgora()).replaceAll('{empresa}','Distribuidora de Bebidas Big Brother').replaceAll('{cidade}','Petrolina').replaceAll('{segmento}','distribuidora de bebidas').replaceAll('{contato}','');}
$('#settings-form').elements.first_message.addEventListener('input',updateFirstPreview);
async function refreshApprovals(){
 const list=await api('approvals');$('#approvals-panel').hidden=!list.length;
 $('#approvals').innerHTML=list.map(a=>`<article class="approval" data-approval="${a.id}"><div class="approval-head"><div><strong>${esc(a.name)}</strong><small>+${esc(a.phone)} · ${esc(a.location||'')}${a.user_name&&currentSettings.sign_messages!==false?' · sai como '+esc(a.user_name):''}${a.sinal_principal?' · No Google: '+esc(signalText[a.sinal_principal]||''):''}</small></div><div class="filters"><button type="button" class="secondary" data-reject="${a.id}">Descartar</button><button type="button" class="primary" data-approve="${a.id}">Aprovar</button></div></div><textarea rows="2" maxlength="4000" data-body="${a.id}" aria-label="Mensagem para ${esc(a.name)}">${esc(a.body)}</textarea><small class="meta">Como vai sair agora: ${esc(a.user_name&&currentSettings.sign_messages!==false?'*'+a.user_name+':* ':'')}${esc(a.preview)}</small></article>`).join('');
 const save=async id=>{const t=document.querySelector(`[data-body="${id}"]`);if(t.dataset.dirty){await api('approvals/'+id,'PATCH',{body:t.value});delete t.dataset.dirty;}};
 document.querySelectorAll('[data-body]').forEach(t=>t.oninput=()=>t.dataset.dirty='1');
 document.querySelectorAll('[data-approve]').forEach(b=>b.onclick=async()=>{b.disabled=true;try{await save(b.dataset.approve);notice((await api('approvals/approve','POST',{ids:[Number(b.dataset.approve)]})).message);await refreshAll();}catch(e){notice(e.message,true);b.disabled=false;}});
 document.querySelectorAll('[data-reject]').forEach(b=>b.onclick=async()=>{b.disabled=true;try{notice((await api('approvals/reject','POST',{ids:[Number(b.dataset.reject)]})).message);await refreshAll();}catch(e){notice(e.message,true);b.disabled=false;}});
}
$('#approve-all').onclick=async()=>{const n=document.querySelectorAll('[data-approve]').length;if(!confirm(`Aprovar e colocar na fila ${n} mensagens?`))return;try{for(const t of document.querySelectorAll('[data-body][data-dirty]'))await api('approvals/'+t.dataset.body,'PATCH',{body:t.value});notice((await api('approvals/approve','POST',{all:true})).message);await refreshAll();}catch(e){notice(e.message,true);}};
$('#reject-all').onclick=async()=>{if(!confirm('Descartar todas as mensagens aguardando aprovação?'))return;try{notice((await api('approvals/reject','POST',{all:true})).message);await refreshAll();}catch(e){notice(e.message,true);}};
function updateUnread(){const n=conversations.length?conversations.reduce((a,c)=>a+(c.unread||0),0):(summary?.unread||0);const el=$('#unread-badge');el.hidden=!n;el.textContent=n;}
async function refreshAll(){await Promise.all([refreshLeads(),refreshSummary(),refreshConversations(),refreshApprovals()]);if(currentLead&&!$('#inbox').hidden)await openThread(currentLead.id,true);}
function scheduleRefresh(){clearTimeout(refreshTimer);refreshTimer=setTimeout(()=>refreshAll().catch(()=>{}),250);}
function connectEvents(){
 const source=eventSource=new EventSource('/api/events');
 source.onopen=()=>{$('#live-badge').textContent='● Ao vivo';$('#live-badge').className='badge saved';$('#live-status').textContent='Conectado em tempo real';};
 source.onerror=()=>{$('#live-badge').textContent='Reconectando…';$('#live-badge').className='badge pending';};
 source.onmessage=e=>{const ev=JSON.parse(e.data);if(ev.type==='cnpj'){refreshCnpj().catch(()=>{});return;}if(ev.type==='message')notice(`Nova resposta de ${ev.name} · ${ev.outreach}: “${ev.preview}”`);if(ev.type==='sent'&&ev.error)notice(`Falha ao enviar para ${ev.name}: ${ev.error}`,true);scheduleRefresh();};
}

/* Configurações */
const settingFields=['company','offers','daily_limit','openai_model','gemini_model','smtp_host','smtp_port','smtp_user','smtp_from','imap_host','imap_port','evolution_url','evolution_instance','email_subject','followup_text','followup_max','followup_days','send_interval','send_daily_limit','send_hour_start','send_hour_end','chains','first_message'];
const numberFields=['daily_limit','smtp_port','imap_port','followup_max','followup_days','send_interval','send_daily_limit','send_hour_start','send_hour_end'];
function fillSettings(s){currentSettings=s;const f=$('#settings-form');for(const name of settingFields)f.elements[name].value=s[name] ?? '';f.elements.provider.value=s.provider;f.elements.aux_search.checked=!!s.aux_search;f.elements.auto_dispatch.checked=!!s.auto_dispatch;f.elements.draft_mode.value=s.draft_mode||'modelo';f.elements.sign_messages.checked=s.sign_messages!==false;updateFirstPreview();for(const p of ['openai','gemini']){f.elements[p+'_key'].value='';f.elements['remove_'+p].checked=false;keyFeedback(p, s[p+'_configured'] ? '✓ Chave salva neste notebook. O campo fica vazio para proteger sua chave.' : 'Nenhuma chave salva. Cole a chave e clique em Salvar configurações.', s[p+'_configured'] ? 'saved' : '');f.elements[p+'_key'].placeholder=s[p+'_configured']?'Chave já salva · cole outra para substituir':'Cole sua chave de API';}for(const p of ['smtp','evolution','places']){f.elements[p+'_key'].value='';f.elements['remove_'+p].checked=false;f.elements[p+'_key'].placeholder=s[p+'_configured']?'Já salva · preencha para substituir':'Cole aqui';const b=$('#'+p+'-status');b.textContent=s[p+'_configured']?'✓ Configurado':'Não configurado';if(p==='evolution'&&s.evolution_key_from_env){f.elements.evolution_key.placeholder='Usando a chave do arquivo .env (Docker local)';}b.className='badge '+(s[p+'_configured']?'saved':'');}$('#provider-badge').textContent=(s.provider==='gemini'?'Gemini':'OpenAI')+' · '+(s[s.provider+'_configured']?'chave salva':'sem chave');}
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
 for(const p of ['openai','gemini','smtp','evolution','places'])data['remove_'+p]=f.elements['remove_'+p].checked;data.aux_search=f.elements.aux_search.checked;data.auto_dispatch=f.elements.auto_dispatch.checked;data.sign_messages=f.elements.sign_messages.checked;
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
let qrTimer=null;
async function loadQr(){
 try{const r=await api('whatsapp/connect','POST',{});if(r.state==='open'){whatsappConnected();return;}
  $('#qr-image').hidden=!r.qr;if(r.qr)$('#qr-image').src=r.qr;$('#qr-status').textContent=r.qr?'Aguardando a leitura…':r.message;}
 catch(e){$('#qr-image').hidden=true;$('#qr-status').textContent=e.message+' Salve as configurações (nome da instância e API key) antes de conectar.';}
}
function whatsappConnected(){clearInterval(qrTimer);qrTimer=null;$('#qr-dialog').close();notice('WhatsApp conectado e pronto para envio.');saveFeedback('✓ WhatsApp conectado.','saved');}
$('#connect-whatsapp').onclick=()=>{$('#qr-image').hidden=true;$('#qr-status').textContent='Gerando QR code…';$('#qr-dialog').showModal();loadQr();let ticks=0;
 qrTimer=setInterval(async()=>{ticks++;try{const r=await api('whatsapp/state');if(r.state==='open'){whatsappConnected();return;}}catch{}if(ticks%10===0)loadQr();},3000);};
$('#close-qr').onclick=()=>{clearInterval(qrTimer);qrTimer=null;$('#qr-dialog').close();};
$('#qr-dialog').addEventListener('close',()=>{clearInterval(qrTimer);qrTimer=null;});
$('#test-places').onclick=async()=>{const b=$('#test-places');b.disabled=true;b.textContent='Testando…';try{const r=await api('places/test','POST',{});notice(r.message);saveFeedback(r.message,'saved');}catch(e){notice(e.message+' Salve as configurações antes de testar.',true);saveFeedback(e.message,'error');}finally{b.disabled=false;b.textContent='Testar Places';}};
document.querySelectorAll('[data-test-channel]').forEach(b=>b.onclick=async()=>{const label=b.textContent;b.disabled=true;b.textContent='Testando…';try{const r=await api('channels/test','POST',{channel:b.dataset.testChannel});notice(r.message);saveFeedback(r.message,'saved');}catch(e){notice(e.message+' Salve as configurações antes de testar.',true);saveFeedback(e.message,'error');}finally{b.disabled=false;b.textContent=label;}});

/* Agente */
$('#campaign').onsubmit=async e=>{e.preventDefault();$('#run-button').disabled=true;try{const data=Object.fromEntries(new FormData(e.target));data.limit=Number(data.limit);await api('runs','POST',data);notice('Busca iniciada. Você pode acompanhar o progresso abaixo.');await refreshRuns();}catch(e){notice(e.message,true);$('#run-button').disabled=false;}};
async function refreshRuns(){const runs=await api('runs');const wasBusy=busy;busy=runs.some(r=>r.status==='executando');$('#run-button').disabled=busy;$('#run-button').textContent=busy?'Pesquisando…':'✧ Iniciar prospecção';$('#runs').innerHTML=runs.length?runs.map(r=>{let q;try{q=JSON.parse(r.query);}catch{q={segment:r.query,location:''};}const tokens=r.usage.total_tokens??r.usage.totalTokenCount;const lg=r.log||{};const reasons=Object.entries(lg.motivos||{});return `<article class="run"><div class="run-head"><strong>${esc(q.segment)}</strong><span class="badge">${esc(r.status)}</span></div><time>${esc(new Date(r.created.replace(' ','T')+'Z').toLocaleString('pt-BR'))} · ${esc(r.provider==='places'?'Google Places':r.provider==='receita'?'Receita Federal (CNPJ)':r.provider)}${r.user_name?' · '+esc(r.user_name):''}</time><p>${esc(q.location)}${q.limit?' · até '+esc(q.limit)+' empresas':''}${q.meses?' · abertas nos últimos '+esc(q.meses)+(q.meses==1?' mês':' meses'):''}</p><p>${esc(r.message)}</p>${tokens?`<p>${esc(tokens)} tokens informados pelo provedor</p>`:''}${reasons.length?`<p><strong>Descartes:</strong> ${reasons.map(([k,v])=>esc(k)+' ('+v+')').join(' · ')}</p>`:''}${(lg.itens||[]).length?`<details><summary>Ver empresas descartadas ou sem WhatsApp (${lg.itens.length})</summary><ul class="discards">${lg.itens.map(i=>`<li><strong>${esc(i.name)}</strong> — ${esc(i.motivo)}</li>`).join('')}</ul></details>`:''}${sourceLinks(r.sources)}${r.search_html?`<iframe sandbox="allow-popups allow-popups-to-escape-sandbox" title="Sugestões da busca Google" srcdoc="${esc(r.search_html)}"></iframe>`:''}</article>`;}).join(''):'<div class="empty"><div class="symbol">✧</div><h3>Pronto para pesquisar</h3><p>Sua primeira execução aparecerá aqui.</p></div>';if(wasBusy&&!busy)await refreshLeads();}
$('#stage-filter').insertAdjacentHTML('beforeend',stages.map(s=>`<option>${s}</option>`).join(''));$('#filter').oninput=renderLeads;$('#stage-filter').onchange=renderLeads;$('#age-filter').onchange=renderLeads;
$('#new-lead').onclick=()=>$('#lead-dialog').showModal();$('#close-dialog').onclick=()=>$('#lead-dialog').close();
$('#lead-form').onsubmit=async e=>{e.preventDefault();e.submitter.disabled=true;try{await api('leads','POST',Object.fromEntries(new FormData(e.target)));$('#lead-dialog').close();e.target.reset();await refreshLeads();notice('Empresa adicionada ao funil.');}catch(e){notice(e.message,true);}finally{e.submitter.disabled=false;}};
/* Empresas recém-abertas (CNPJ) */
function fmtDate(d){return d?d.slice(8,10)+'/'+d.slice(5,7)+'/'+d.slice(0,4):'';}
function monthsSince(d){return (Date.now()-new Date(d+'T12:00:00'))/864e5/30.44;}
function ageText(d){if(!d)return '';const days=Math.max(0,Math.floor((Date.now()-new Date(d+'T12:00:00'))/864e5));if(days<31)return days<=1?'há 1 dia':`há ${days} dias`;const m=Math.floor(days/30.44);if(m<12)return m===1?'há 1 mês':`há ${m} meses`;const y=Math.floor(m/12),r=m%12;return `há ${y} ano${y>1?'s':''}${r?` e ${r} ${r>1?'meses':'mês'}`:''}`;}
async function refreshCnpj(){
 const info=await api('cnpj');const st=info.status||{};const sel=$('#cnpj-search').elements.cidade;const cur=sel.value;
 sel.innerHTML=`<option value="">Todas as cidades (${info.total})</option>`+info.cidades.map(c=>`<option value="${esc(c.cidade+'/'+c.uf)}">${esc(c.cidade)}/${esc(c.uf)} (${c.total})</option>`).join('');sel.value=cur;
 const imp=$('#cnpj-import');if(!imp.elements.cidades.value&&info.config?.cidades)imp.elements.cidades.value=info.config.cidades;if(info.config?.meses&&!imp.dataset.touched)imp.elements.meses.value=String(info.config.meses);
 const running=st.status==='executando';$('#cnpj-import-button').disabled=running;$('#cnpj-import-button').textContent=running?'Atualizando…':'Baixar / atualizar base';$('#cnpj-button').disabled=!info.total;
 let html='';
 if(running){const pct=st.total?Math.floor(st.lido*100/st.total):0;html=`<p><strong>Atualizando a base da Receita…</strong> ${esc(st.etapa||'')} · ${pct}% · ${esc(st.encontradas||0)} empresas encontradas até agora</p><progress max="100" value="${pct}"></progress>`;}
 if(info.total)html+=`<p class="hint">Base de ${esc(st.mes_base||'')}: <strong>${info.total}</strong> empresas abertas nos últimos ${esc(info.config?.meses||'')} meses em ${info.cidades.map(c=>esc(c.cidade+'/'+c.uf)).join(', ')}.</p>`;
 else if(!running)html+=`<p class="hint">${me?.role==='admin'?'Baixe a base uma vez em “Atualizar base da Receita”, logo abaixo.':'Peça ao administrador para baixar a base da Receita.'}</p>`;
 if(st.status==='erro'||st.status==='interrompido')html+=`<p class="error-text">${esc(st.erro||'')}</p>`;
 $('#cnpj-status').innerHTML=html;
}
$('#cnpj-import').elements.meses.onchange=()=>{$('#cnpj-import').dataset.touched='1';};
$('#cnpj-search').onsubmit=async e=>{e.preventDefault();const f=e.target;const b=$('#cnpj-button');b.disabled=true;try{const r=await api('cnpj/buscar','POST',{cidade:f.elements.cidade.value,meses:Number(f.elements.meses.value),atividade:f.elements.atividade.value,limite:Number(f.elements.limite.value),excluir_mei:f.elements.excluir_mei.checked,excluir_saude:f.elements.excluir_saude.checked,pular_contador:f.elements.pular_contador.checked});notice(r.message);await Promise.all([refreshRuns(),refreshLeads()]);}catch(e){notice(e.message,true);}finally{b.disabled=false;}};
$('#cnpj-import').onsubmit=async e=>{e.preventDefault();const f=e.target;try{notice((await api('cnpj/importar','POST',{cidades:f.elements.cidades.value,meses:Number(f.elements.meses.value)})).message);await refreshCnpj();}catch(e){notice(e.message,true);}};
/* Tema */
const darkQuery=matchMedia('(prefers-color-scheme: dark)');
function applyTheme(theme){document.documentElement.dataset.theme=theme;document.documentElement.classList.toggle('dark',theme==='dark'||(theme==='auto'&&darkQuery.matches));$('#theme-toggle').textContent={auto:'◐ Tema: automático',light:'☀ Tema: claro',dark:'☾ Tema: escuro'}[theme];}
$('#theme-toggle').onclick=()=>{const next={auto:'light',light:'dark',dark:'auto'}[document.documentElement.dataset.theme||'auto'];try{localStorage.setItem('prospecta-theme',next);}catch{}applyTheme(next);};
darkQuery.addEventListener('change',()=>applyTheme(document.documentElement.dataset.theme||'auto'));
applyTheme(document.documentElement.dataset.theme||'auto');
/* Login e equipe */
let authMode='login';
function showAuth(status={}){
 document.body.classList.add('locked');$('#auth').hidden=false;eventSource?.close();eventSource=null;
 authMode=status.needs_setup?'setup':'login';const f=$('#auth-form');
 $('#auth-title').textContent=authMode==='setup'?'Criar administrador':'Entrar';
 $('#auth-hint').textContent=authMode==='setup'?(status.setup_allowed?'Primeiro acesso: crie a conta de administrador. Depois você adiciona a equipe.':'O primeiro administrador precisa ser criado no computador do servidor.'):'Use o e-mail e a senha que o administrador cadastrou para você.';
 $('#auth-name-field').hidden=authMode!=='setup';f.elements.name.required=authMode==='setup';f.elements.password.autocomplete=authMode==='setup'?'new-password':'current-password';f.elements.password.minLength=authMode==='setup'?8:1;
 $('#auth-button').textContent=authMode==='setup'?'Criar e entrar':'Entrar';$('#auth-error').hidden=true;
}
$('#auth-form').onsubmit=async e=>{
 e.preventDefault();const f=e.target;const data=Object.fromEntries(new FormData(f));const b=$('#auth-button');b.disabled=true;
 try{await api(authMode==='setup'?'auth/setup':'auth/login','POST',authMode==='setup'?data:{email:data.email,password:data.password});f.reset();await boot();}
 catch(err){$('#auth-error').textContent=err.message;$('#auth-error').hidden=false;}finally{b.disabled=false;}
};
$('#logout').onclick=async()=>{await api('auth/logout','POST',{}).catch(()=>{});location.reload();};
$('#open-account').onclick=()=>{const f=$('#account-form');f.reset();f.elements.name.value=me.name;$('#account-dialog').showModal();};
$('#close-account').onclick=()=>$('#account-dialog').close();
$('#account-form').onsubmit=async e=>{e.preventDefault();const data=Object.fromEntries(new FormData(e.target));if(!data.new_password)delete data.new_password;try{notice((await api('me','PATCH',data)).message);$('#account-dialog').close();me.name=data.name||me.name;$('#me-name').textContent=me.name;}catch(err){notice(err.message,true);}};
async function refreshTeam(){
 const users=await api('team');
 $('#team-list').innerHTML=users.map(u=>`<article class="member ${u.active?'':'inactive'}"><div><strong>${esc(u.name)}</strong><span>${esc(u.email)}${u.active?'':' · desativado'}</span></div><div class="member-actions"><select data-role="${u.id}" aria-label="Permissão de ${esc(u.name)}"><option value="member" ${u.role==='member'?'selected':''}>Membro</option><option value="admin" ${u.role==='admin'?'selected':''}>Administrador</option></select><button class="secondary" data-rename="${u.id}" data-name="${esc(u.name)}">Editar nome</button><button class="secondary" data-reset="${u.id}">Nova senha</button><button class="secondary" data-active="${u.id}" data-value="${u.active?0:1}">${u.active?'Desativar':'Reativar'}</button></div></article>`).join('');
 const patch=async(id,data)=>{try{notice((await api('team/'+id,'PATCH',data)).message);}catch(e){notice(e.message,true);}await refreshTeam();};
 document.querySelectorAll('[data-role]').forEach(el=>el.onchange=()=>patch(el.dataset.role,{role:el.value}));
 document.querySelectorAll('[data-active]').forEach(el=>el.onclick=()=>patch(el.dataset.active,{active:el.dataset.value==='1'}));
 document.querySelectorAll('[data-rename]').forEach(el=>el.onclick=async()=>{const name=prompt('Novo nome (é o que aparece em negrito nas mensagens):',el.dataset.name);if(name===null)return;if(name.trim().length<2){notice('O nome precisa ter pelo menos 2 letras.',true);return;}await patch(el.dataset.rename,{name:name.trim()});if(Number(el.dataset.rename)===me.id){me.name=name.trim();$('#me-name').textContent=me.name;}});
 document.querySelectorAll('[data-reset]').forEach(el=>el.onclick=()=>{const pw=prompt('Nova senha para este membro (mínimo 8 caracteres):');if(pw)patch(el.dataset.reset,{password:pw});});
}
$('#team-form').onsubmit=async e=>{e.preventDefault();try{notice((await api('team','POST',Object.fromEntries(new FormData(e.target)))).message);e.target.reset();await refreshTeam();}catch(err){notice(err.message,true);}};
async function boot(){
 const status=await api('auth/status');
 if(!status.user){showAuth(status);return;}
 me=status.user;document.body.classList.remove('locked');$('#auth').hidden=true;
 $('#me-name').textContent=me.name;$('#me-role').textContent=me.role==='admin'?'Administrador':'Membro';
 document.querySelectorAll('[data-admin]').forEach(el=>el.hidden=me.role!=='admin');
 try{fillSettings(await api('settings'));await Promise.all([refreshLeads(),refreshRuns(),refreshSummary(),refreshConversations(),refreshApprovals(),refreshCnpj()]);if(!eventSource)connectEvents();}catch(e){notice('Não foi possível carregar o sistema: '+e.message,true);}
 if(!started){started=true;setInterval(()=>{if(!document.hidden&&me){refreshRuns().catch(()=>{});refreshSummary().catch(()=>{});if(!$('#agent').hidden)refreshCnpj().catch(()=>{});}},5000);}
}
boot().catch(e=>notice('Não foi possível carregar o sistema: '+e.message,true));
