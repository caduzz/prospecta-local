const $ = s => document.querySelector(s);
const stages = ['Novo','Qualificado','Em contato','Proposta','Ganho','Perdido'];
let allLeads = [], currentSettings, busy = false;
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const link = s => /^https?:\/\//i.test(s || '') ? esc(s) : '#';
function notice(message, error = false) { const el = $('#notice'); el.textContent = message; el.className = error ? 'error' : ''; el.hidden = false; }
async function api(path, method='GET', data) {
  const res = await fetch('/api/'+path,{method,headers:{'Content-Type':'application/json','X-Prospecta':'local'},...(data !== undefined ? {body:JSON.stringify(data)} : {})});
  const json = await res.json();
  if(!res.ok) throw new Error(typeof json.detail === 'string' ? json.detail : 'Confira os campos preenchidos.');
  return json;
}
function page(name) { document.querySelectorAll('.page').forEach(p=>p.hidden=p.id!==name);document.querySelectorAll('.nav').forEach(b=>b.classList.toggle('active',b.dataset.page===name));$('#page-title').textContent={dashboard:'Oportunidades',agent:'Agente de prospecção',settings:'Configurações'}[name]; }
document.querySelectorAll('.nav').forEach(b=>b.onclick=()=>page(b.dataset.page));
function sourceLinks(sources) { return `<div class="sources">${sources.map(s=>`<a href="${link(s.url)}" target="_blank" rel="noreferrer">${esc(s.title || 'Fonte')} ↗</a>`).join('')}</div>`; }
function renderLeads() {
 $('#total').textContent=allLeads.length;$('#negotiating').textContent=allLeads.filter(l=>['Em contato','Proposta'].includes(l.stage)).length;$('#won').textContent=allLeads.filter(l=>l.stage==='Ganho').length;
 const filter=$('#filter').value.toLocaleLowerCase(); const stage=$('#stage-filter').value;
 const list=allLeads.filter(l=>(l.name+' '+l.segment+' '+l.location).toLocaleLowerCase().includes(filter)&&(!stage||l.stage===stage));
 $('#leads').innerHTML=list.length?list.map(l=>`<article class="lead"><div class="lead-top"><div><h3>${esc(l.name)}</h3><p class="meta">${esc([l.segment,l.location].filter(Boolean).join(' · '))}</p>${l.website?`<a href="${link(l.website)}" target="_blank" rel="noreferrer">Visitar site ↗</a>`:''}</div><select data-lead="${l.id}" aria-label="Etapa de ${esc(l.name)}">${stages.map(s=>`<option ${s===l.stage?'selected':''}>${s}</option>`).join('')}</select></div>${l.reason?`<p>${esc(l.reason)}</p>`:''}${l.contact?`<p><strong>Contato:</strong> ${esc(l.contact)}</p>`:''}${sourceLinks(l.sources)}${l.draft?`<details><summary>Rascunho de abordagem</summary><div class="draft">${esc(l.draft)}</div><button class="secondary" data-copy="${l.id}">Copiar rascunho</button></details>`:''}</article>`).join(''):`<div class="empty"><div class="symbol">◈</div><h3>${allLeads.length?'Nenhum resultado neste filtro':'Um novo radar para o seu negócio'}</h3><p>${allLeads.length?'Tente outro nome ou etapa.':'Configure sua IA e inicie a primeira busca. As empresas encontradas aparecerão aqui.'}</p>${allLeads.length?'':'<button class="secondary" id="empty-start">Configurar meu agente →</button>'}</div>`;
 $('#empty-start')?.addEventListener('click',()=>page('settings'));
 document.querySelectorAll('[data-lead]').forEach(el=>el.onchange=async()=>{try{await api('leads/'+el.dataset.lead,'PATCH',{stage:el.value});await refreshLeads();}catch(e){notice(e.message,true);await refreshLeads();}});
 document.querySelectorAll('[data-copy]').forEach(el=>el.onclick=async()=>{try{await navigator.clipboard.writeText(allLeads.find(l=>l.id==el.dataset.copy).draft);notice('Rascunho copiado.');}catch{notice('Não foi possível copiar automaticamente. Selecione o texto do rascunho.',true);}});
}
async function refreshLeads(){allLeads=await api('leads');renderLeads();}
function fillSettings(s){currentSettings=s;const f=$('#settings-form');for(const name of ['company','offers','daily_limit','openai_model','gemini_model'])f.elements[name].value=s[name];f.elements.provider.value=s.provider;for(const p of ['openai','gemini']){f.elements[p+'_key'].value='';f.elements['remove_'+p].checked=false;keyFeedback(p, s[p+'_configured'] ? '✓ Chave salva neste notebook. O campo fica vazio para proteger sua chave.' : 'Nenhuma chave salva. Cole a chave e clique em Salvar configurações.', s[p+'_configured'] ? 'saved' : '');f.elements[p+'_key'].placeholder=s[p+'_configured']?'Chave já salva · cole outra para substituir':'Cole sua chave de API';}$('#provider-badge').textContent=(s.provider==='gemini'?'Gemini':'OpenAI')+' · '+(s[s.provider+'_configured']?'chave salva':'sem chave');}
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
 const data=Object.fromEntries(new FormData(f));data.daily_limit=Number(data.daily_limit);data.revision=currentSettings.revision || 0;
 data.remove_openai=f.elements.remove_openai.checked;data.remove_gemini=f.elements.remove_gemini.checked;
 const changed=['openai','gemini'].filter(p=>data[p+'_key'].trim() || data['remove_'+p]);
 const controls=[...f.elements];controls.forEach(el=>el.disabled=true);button.textContent='Salvando…';saveFeedback('Salvando configurações neste notebook…','saving');
 changed.forEach(p=>keyFeedback(p,'Salvando alteração da chave…','saving'));
 try{
  fillSettings(await api('settings','PUT',data));
  changed.forEach(p=>keyFeedback(p,data['remove_'+p]?'Chave removida com sucesso.':'✓ Chave salva com sucesso. Use Testar conexão salva para validar o acesso.',data['remove_'+p]?'':'saved'));
  saveFeedback('✓ Configurações salvas com sucesso. Provedor ativo: '+(data.provider==='gemini'?'Gemini':'OpenAI')+'.','saved');
  notice('Configurações salvas. As próximas buscas usarão o provedor selecionado.');
 }catch(error){
  saveFeedback('Não foi possível salvar: '+error.message,'error');
  changed.forEach(p=>keyFeedback(p,'Não foi possível salvar a alteração. Sua chave anterior foi mantida; tente novamente.','error'));
  notice(error.message,true);
 }finally{controls.forEach(el=>el.disabled=false);button.textContent='Salvar configurações';}
};
$('#test-key').onclick=async()=>{const b=$('#test-key');b.disabled=true;b.textContent='Testando…';try{const r=await api('test','POST',{});notice(r.message);saveFeedback(r.message,'saved');}catch(e){notice(e.message,true);saveFeedback(e.message,'error');}finally{b.disabled=false;b.textContent='Testar conexão salva';}};
$('#campaign').onsubmit=async e=>{e.preventDefault();$('#run-button').disabled=true;try{const data=Object.fromEntries(new FormData(e.target));data.limit=Number(data.limit);await api('runs','POST',data);notice('Busca iniciada. Você pode acompanhar o progresso abaixo.');await refreshRuns();}catch(e){notice(e.message,true);$('#run-button').disabled=false;}};
async function refreshRuns(){const runs=await api('runs');const wasBusy=busy;busy=runs.some(r=>r.status==='executando');$('#run-button').disabled=busy;$('#run-button').textContent=busy?'Pesquisando…':'✧ Iniciar prospecção';$('#runs').innerHTML=runs.length?runs.map(r=>{let q;try{q=JSON.parse(r.query);}catch{q={segment:r.query,location:''};}const tokens=r.usage.total_tokens??r.usage.totalTokenCount;return `<article class="run"><div class="run-head"><strong>${esc(q.segment)}</strong><span class="badge">${esc(r.status)}</span></div><time>${esc(new Date(r.created.replace(' ','T')+'Z').toLocaleString('pt-BR'))} · ${esc(r.provider)}</time><p>${esc(q.location)} · ${esc(r.model)}</p><p>${esc(r.message)}</p>${tokens?`<p>${esc(tokens)} tokens informados pelo provedor</p>`:''}${sourceLinks(r.sources)}${r.search_html?`<iframe sandbox="allow-popups allow-popups-to-escape-sandbox" title="Sugestões da busca Google" srcdoc="${esc(r.search_html)}"></iframe>`:''}</article>`;}).join(''):'<div class="empty"><div class="symbol">✧</div><h3>Pronto para pesquisar</h3><p>Sua primeira execução aparecerá aqui.</p></div>';if(wasBusy&&!busy)await refreshLeads();}
$('#stage-filter').insertAdjacentHTML('beforeend',stages.map(s=>`<option>${s}</option>`).join(''));$('#filter').oninput=renderLeads;$('#stage-filter').onchange=renderLeads;
$('#new-lead').onclick=()=>$('#lead-dialog').showModal();$('#close-dialog').onclick=()=>$('#lead-dialog').close();
$('#lead-form').onsubmit=async e=>{e.preventDefault();e.submitter.disabled=true;try{await api('leads','POST',Object.fromEntries(new FormData(e.target)));$('#lead-dialog').close();e.target.reset();await refreshLeads();notice('Empresa adicionada ao funil.');}catch(e){$('#lead-dialog').close();notice(e.message,true);}finally{e.submitter.disabled=false;}};
async function init(){try{fillSettings(await api('settings'));await Promise.all([refreshLeads(),refreshRuns()]);}catch(e){notice('Não foi possível carregar o sistema: '+e.message,true);}}init();setInterval(()=>{if(!document.hidden)refreshRuns().catch(()=>{});},5000);
