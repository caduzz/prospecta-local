import httpx
from app import settings,cipher
s=settings();key=cipher().decrypt(s['gemini_key'].encode()).decode()
url='https://generativelanguage.googleapis.com/v1beta/models/'+s['gemini_model']+':generateContent'
try:
 r=httpx.post(url,headers={'x-goog-api-key':key},json={'contents':[{'parts':[{'text':'Responda OK'}]}],'generationConfig':{'maxOutputTokens':20}},timeout=45)
 print('HTTP',r.status_code)
 print(r.text.replace(key,'[REDACTED]')[:2000])
except httpx.HTTPError:
 print('Falha de rede')
