import httpx
from app import settings, cipher
s=settings()
key=cipher().decrypt(s['gemini_key'].encode()).decode()
try:
 r=httpx.get('https://generativelanguage.googleapis.com/v1beta/models',headers={'x-goog-api-key':key},timeout=30)
 print('HTTP',r.status_code)
 if r.is_success:
  print('\n'.join(m['name'] for m in r.json().get('models',[]) if 'generateContent' in m.get('supportedGenerationMethods',[])))
 else:
  print(r.text.replace(key,'[REDACTED]')[:1500])
except httpx.HTTPError:
 print('Falha de rede ao consultar modelos')
 raise SystemExit(1)
