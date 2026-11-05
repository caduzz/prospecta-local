import asyncio
from app import settings,generate
async def main():
 try:
  text,sources,usage,_=await generate(settings(),'Pesquise o site oficial do Python e responda em uma frase curta com a fonte.',True)
  print('Busca OK; fontes:',len(sources))
 except ValueError as e:
  print(str(e))
  raise SystemExit(1)
asyncio.run(main())
