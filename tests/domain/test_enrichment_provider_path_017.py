
import asyncio
from domain.enrichment import ChainedSpeciesEnrichment, INaturalistAdapter, TrefleAdapter, PerenualAdapter

def run(coro): return asyncio.run(coro)

def test_confirmed_alias_is_canonicalized():
 async def ina(q): return {"results":[{"id":67710,"name":"Sansevieria trifasciata","preferred_common_name":"Snake Plant","matched_term":"Snake Plant"}]}
 async def empty(q): return {"data":[]}
 chain=ChainedSpeciesEnrichment(INaturalistAdapter(ina),TrefleAdapter(empty,""),PerenualAdapter(empty,""))
 candidates=run(chain.discover("Snake Plant"))
 result=run(chain.enrich_selected("Snake Plant",candidates[0]))
 assert result.data["scientific_name"]=="Dracaena trifasciata"
 assert result.data["common_name"]=="Snake Plant"

def test_provider_single_flight():
 calls=0
 async def ina(q):
  nonlocal calls
  calls+=1
  await asyncio.sleep(0.01)
  return {"results":[]}
 chain=ChainedSpeciesEnrichment(INaturalistAdapter(ina),TrefleAdapter(ina,""),PerenualAdapter(ina,""))
 async def exercise(): await asyncio.gather(chain.discover("Snake Plant"),chain.discover("Snake Plant"))
 run(exercise())
 assert calls==1
