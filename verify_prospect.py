import asyncio,json
from app import settings,db,Campaign,prospect
s=settings(); campaign=Campaign(segment='academia',location='Juazeiro BA e Petrolina PE',criteria='sistema de agendamento',limit=5)
with db() as c:
 if c.execute("select 1 from runs where status='executando'").fetchone():
  raise SystemExit('Há uma execução em andamento; diagnóstico não iniciado.')
 if c.execute("select count(*) from runs where date(created)=date('now')").fetchone()[0]>=s['daily_limit']:
  raise SystemExit('Limite diário atingido; diagnóstico não iniciado.')
 run_id=c.execute("insert into runs(provider,model,query,status,message) values (?,?,?,'executando','Validando pesquisa com fontes')",(s['provider'],s[s['provider']+'_model'],json.dumps(campaign.model_dump()))).lastrowid
asyncio.run(prospect(run_id,s,campaign))
with db() as c:
 row=c.execute('select status,message,count,sources from runs where id=?',(run_id,)).fetchone()
 print(row['status'],row['message'],'Fontes:',len(json.loads(row['sources'])))
