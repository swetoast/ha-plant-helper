import asyncio,copy
from datetime import datetime,timedelta,timezone
import pytest
from domain.enrichment import *
from domain.storage import PlantHelperStorage
NOW=datetime(2026,1,1,tzinfo=timezone.utc)
class B:
 def __init__(self,data=None):self.data=copy.deepcopy(data)
 async def async_load(self):return copy.deepcopy(self.data)
 async def async_save(self,d):self.data=copy.deepcopy(d)
def run(c):return asyncio.run(c)
def store(data=None):b=B(data);s=PlantHelperStorage(b);run(s.async_load());return b,s
class P:
 def __init__(self,name,items=None,error=None,delay=0):self.name=name;self.items=items or [];self.error=error;self.delay=delay;self.calls=0;self.credential='secret-token'
 async def search(self,q):self.calls+=1;await asyncio.sleep(self.delay); 
 async def _unused(self):pass

def provider(name,items=None,error=None,delay=0):
 p=P(name,items,error,delay)
 async def search(q):
  p.calls+=1;await asyncio.sleep(delay)
  if error:raise error
  return copy.deepcopy(items or [])
 p.search=search;return p
def test_adapters_normalize_all_three_provider_shapes():
 per=PerenualAdapter(lambda q:asyncio.sleep(0,result={'data':[{'scientific_name':['Dracaena trifasciata'],'common_name':'Snake plant','default_image':{'regular_url':'p.jpg'}}]}))
 tre=TrefleAdapter(lambda q:asyncio.sleep(0,result={'data':[{'scientific_name':'Dracaena trifasciata','family':'Asparagaceae'}]}))
 ina=INaturalistAdapter(lambda q:asyncio.sleep(0,result={'results':[{'name':'Dracaena trifasciata','default_photo':{'medium_url':'i.jpg'}}]}))
 assert run(per.search('x'))[0]['scientific_name']=='Dracaena trifasciata';assert run(tre.search('x'))[0]['family']=='Asparagaceae';assert run(ina.search('x'))[0]['image_url']=='i.jpg'
def test_exact_strong_and_field_level_merge():
 b,s=store();providers=[provider('perenual',[{'scientific_name':'Dracaena trifasciata','common_name':'Snake plant','watering_category':'low'}]),provider('trefle',[{'scientific_name':'Dracaena trifasciata','family':'Asparagaceae','genus':'Dracaena'}]),provider('inaturalist',[{'scientific_name':'Dracaena trifasciata','image_url':'i.jpg'}])]
 e=SpeciesEnrichment(s,providers);run(e.load());r=run(e.enrich('Snake plant',NOW));assert r.status=='matched' and r.data['family']=='Asparagaceae' and r.data['watering_category']=='low' and r.data['image_url']=='i.jpg'
def test_species_and_provider_single_flight():
 async def scenario():
  b=B();s=PlantHelperStorage(b);await s.async_load();p=provider('perenual',[{'scientific_name':'Monstera deliciosa'}],delay=.02);e=SpeciesEnrichment(s,[p]);await e.load();a,b2=await asyncio.gather(e.enrich('Monstera deliciosa',NOW),e.enrich('Monstera deliciosa',NOW));assert p.calls==1 and a==b2
 run(scenario())
def test_long_lived_cache_persists_restart():
 b,s=store();p=provider('trefle',[{'scientific_name':'Monstera deliciosa'}]);e=SpeciesEnrichment(s,[p]);run(e.load());run(e.enrich('Monstera deliciosa',NOW));s2=PlantHelperStorage(B(b.data));run(s2.async_load());p2=provider('trefle');e2=SpeciesEnrichment(s2,[p2]);run(e2.load());r=run(e2.enrich('Monstera deliciosa',NOW+timedelta(days=2)));assert r.cached and p2.calls==0
def test_negative_classification_ambiguous_not_found_and_transient():
 b,s=store();amb=SpeciesEnrichment(s,[provider('trefle',[{'scientific_name':'Monstera adansonii'}])]);run(amb.load());assert run(amb.enrich('Monstera',NOW)).status=='ambiguous'
 b,s=store();nf=SpeciesEnrichment(s,[provider('trefle',[])]);run(nf.load());assert run(nf.enrich('No such plant',NOW)).status=='not_found'
 b,s=store();bad=SpeciesEnrichment(s,[provider('trefle',error=ProviderError('network'))]);run(bad.load());assert run(bad.enrich('Anything',NOW)).status=='unavailable' and 'anything' not in bad.cache
def test_provider_backoff_auth_suspension_and_failure_isolation():
 b,s=store();auth=provider('perenual',error=ProviderError('auth',401));rate=provider('trefle',error=ProviderError('rate',429));good=provider('inaturalist',[{'scientific_name':'Monstera deliciosa'}]);e=SpeciesEnrichment(s,[auth,rate,good]);run(e.load());r=run(e.enrich('Monstera deliciosa',NOW));assert r.status=='matched' and auth.name in e.auth_suspended and e.backoff_until['trefle']>NOW
 assert run(e.enrich('Another plant',NOW+timedelta(minutes=1))).status in {'not_found','unavailable'} and auth.calls==1 and rate.calls==1
def test_redaction():
 text=redact('https://x.test?api_key=abc token=xyz Authorization=secret bearer live.token',('live.token',));assert 'abc' not in text and 'xyz' not in text and 'secret' not in text and 'live.token' not in text

def test_chained_common_name_discovery_preserves_ambiguous_candidates():
 from domain.enrichment import ChainedSpeciesEnrichment
 ina=INaturalistAdapter(lambda query:asyncio.sleep(0,result={'results':[
  {'id':67710,'rank':'species','is_active':True,'name':'Sansevieria trifasciata','preferred_common_name':'Snake Plant','matched_term':'Snake Plant','iconic_taxon_name':'Plantae'},
  {'id':168422,'rank':'species','is_active':True,'name':'Sansevieria cylindrica','preferred_common_name':'African Spear','matched_term':'Cylindrical Snake Plant','iconic_taxon_name':'Plantae'}]}))
 chain=ChainedSpeciesEnrichment(ina,TrefleAdapter(lambda q:asyncio.sleep(0,result={'data':[]})),PerenualAdapter(lambda q:asyncio.sleep(0,result={'data':[]})))
 candidates=run(chain.discover('Snake Plant'))
 assert [candidate['scientific_name'] for candidate in candidates]==['Sansevieria trifasciata','Sansevieria cylindrica']
 assert candidates[0]['synonyms']==['Snake Plant']

def test_chained_selected_identity_trefle_then_perenual_fallbacks():
 from domain.enrichment import ChainedSpeciesEnrichment
 calls=[]
 async def trefle(query):
  calls.append(('trefle',query));return {'data':[{'scientific_name':'Dracaena trifasciata','synonyms':['Sansevieria trifasciata'],'family':'Asparagaceae','genus':'Dracaena'}]}
 async def perenual(query):
  calls.append(('perenual',query))
  if query=='Snake Plant':return {'data':[{'scientific_name':['Sansevieria trifasciata'],'common_name':'Snake Plant','watering':'Minimum','sunlight':['part shade']} ]}
  return {'data':[]}
 selected={'provider_id':67710,'scientific_name':'Sansevieria trifasciata','common_name':'Snake Plant','synonyms':['Snake Plant'],'image_url':'inat.jpg'}
 chain=ChainedSpeciesEnrichment(INaturalistAdapter(lambda q:asyncio.sleep(0,result={})),TrefleAdapter(trefle),PerenualAdapter(perenual))
 result=run(chain.enrich_selected('Snake Plant',selected))
 assert result.status=='matched'
 assert result.data['scientific_name']=='Dracaena trifasciata'
 assert result.data['common_name']=='Snake Plant'
 assert result.data['family']=='Asparagaceae' and result.data['genus']=='Dracaena'
 assert result.data['watering_category']=='Minimum'
 assert calls==[('trefle','Sansevieria trifasciata'),('perenual','Dracaena trifasciata'),('perenual','Sansevieria trifasciata'),('perenual','Snake Plant')]

def test_chained_perenual_family_only_match_is_rejected():
 from domain.enrichment import ChainedSpeciesEnrichment
 selected={'scientific_name':'Sansevieria trifasciata','common_name':'Snake Plant','synonyms':['Snake Plant']}
 trefle=TrefleAdapter(lambda q:asyncio.sleep(0,result={'data':[{'scientific_name':'Dracaena trifasciata','synonyms':['Sansevieria trifasciata'],'family':'Asparagaceae'}]}))
 perenual=PerenualAdapter(lambda q:asyncio.sleep(0,result={'data':[{'scientific_name':['Agave americana'],'common_name':'Century Plant','family':'Asparagaceae','watering':'Minimum'}]}))
 result=run(ChainedSpeciesEnrichment(INaturalistAdapter(lambda q:asyncio.sleep(0,result={})),trefle,perenual).enrich_selected('Snake Plant',selected))
 assert 'watering_category' not in result.data
 assert result.providers==('inaturalist','trefle')


def test_exact_common_name_selection_requires_one_candidate():
 from domain.enrichment import select_exact_common_name_candidate
 candidates=[
  {'scientific_name':'Sansevieria trifasciata','common_name':'Snake Plant','matched_term':'Snake Plant'},
  {'scientific_name':'Sansevieria cylindrica','common_name':'African Spear','matched_term':'Cylindrical Snake Plant'},
 ]
 assert select_exact_common_name_candidate('Snake Plant',candidates)['scientific_name']=='Sansevieria trifasciata'
 assert select_exact_common_name_candidate('Plant',candidates) is None
 assert select_exact_common_name_candidate('Snake Plant',[candidates[0],dict(candidates[0])]) is None
