import asyncio,copy
from datetime import datetime,timedelta,timezone
import pytest
from domain.enrichment import *
from domain.storage import PlantHelperStorage
from domain.enrichment import ChainedSpeciesEnrichment
from domain.enrichment import select_exact_common_name_candidate
import asyncio
from domain.enrichment import ChainedSpeciesEnrichment, INaturalistAdapter, TrefleAdapter, PerenualAdapter
from domain.species import normalize_species_key,classify_match,merge_provider_fields
import asyncio,io,os
from pathlib import Path
from PIL import Image
from domain.image_proxy import *

# ---- from test_enrichment.py ----
NOW=datetime(2026,1,1,tzinfo=timezone.utc)
class B:
 def __init__(self,data=None):self.data=copy.deepcopy(data)
 async def async_load(self):return copy.deepcopy(self.data)
 async def async_save(self,d):self.data=copy.deepcopy(d)
def enrichment_run(c):return asyncio.run(c)
def store(data=None):b=B(data);s=PlantHelperStorage(b);enrichment_run(s.async_load());return b,s
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
 assert enrichment_run(per.search('x'))[0]['scientific_name']=='Dracaena trifasciata';assert enrichment_run(tre.search('x'))[0]['family']=='Asparagaceae';assert enrichment_run(ina.search('x'))[0]['image_url']=='i.jpg'
def test_exact_strong_and_field_level_merge():
 b,s=store();providers=[provider('perenual',[{'scientific_name':'Dracaena trifasciata','common_name':'Snake plant','watering_category':'low'}]),provider('trefle',[{'scientific_name':'Dracaena trifasciata','family':'Asparagaceae','genus':'Dracaena'}]),provider('inaturalist',[{'scientific_name':'Dracaena trifasciata','image_url':'i.jpg'}])]
 e=SpeciesEnrichment(s,providers);enrichment_run(e.load());r=enrichment_run(e.enrich('Snake plant',NOW));assert r.status=='matched' and r.data['family']=='Asparagaceae' and r.data['watering_category']=='low' and r.data['image_url']=='i.jpg'
def test_species_and_provider_single_flight():
 async def scenario():
  b=B();s=PlantHelperStorage(b);await s.async_load();p=provider('perenual',[{'scientific_name':'Monstera deliciosa'}],delay=.02);e=SpeciesEnrichment(s,[p]);await e.load();a,b2=await asyncio.gather(e.enrich('Monstera deliciosa',NOW),e.enrich('Monstera deliciosa',NOW));assert p.calls==1 and a==b2
 enrichment_run(scenario())
def test_long_lived_cache_persists_restart():
 b,s=store();p=provider('trefle',[{'scientific_name':'Monstera deliciosa'}]);e=SpeciesEnrichment(s,[p]);enrichment_run(e.load());enrichment_run(e.enrich('Monstera deliciosa',NOW));s2=PlantHelperStorage(B(b.data));enrichment_run(s2.async_load());p2=provider('trefle');e2=SpeciesEnrichment(s2,[p2]);enrichment_run(e2.load());r=enrichment_run(e2.enrich('Monstera deliciosa',NOW+timedelta(days=2)));assert r.cached and p2.calls==0
def test_negative_classification_ambiguous_not_found_and_transient():
 b,s=store();amb=SpeciesEnrichment(s,[provider('trefle',[{'scientific_name':'Monstera adansonii'}])]);enrichment_run(amb.load());assert enrichment_run(amb.enrich('Monstera',NOW)).status=='ambiguous'
 b,s=store();nf=SpeciesEnrichment(s,[provider('trefle',[])]);enrichment_run(nf.load());assert enrichment_run(nf.enrich('No such plant',NOW)).status=='not_found'
 b,s=store();bad=SpeciesEnrichment(s,[provider('trefle',error=ProviderError('network'))]);enrichment_run(bad.load());assert enrichment_run(bad.enrich('Anything',NOW)).status=='unavailable' and 'anything' not in bad.cache
def test_provider_backoff_auth_suspension_and_failure_isolation():
 b,s=store();auth=provider('perenual',error=ProviderError('auth',401));rate=provider('trefle',error=ProviderError('rate',429));good=provider('inaturalist',[{'scientific_name':'Monstera deliciosa'}]);e=SpeciesEnrichment(s,[auth,rate,good]);enrichment_run(e.load());r=enrichment_run(e.enrich('Monstera deliciosa',NOW));assert r.status=='matched' and auth.name in e.auth_suspended and e.backoff_until['trefle']>NOW
 assert enrichment_run(e.enrich('Another plant',NOW+timedelta(minutes=1))).status in {'not_found','unavailable'} and auth.calls==1 and rate.calls==1
def test_redaction():
 text=redact('https://x.test?api_key=abc token=xyz Authorization=secret bearer live.token',('live.token',));assert 'abc' not in text and 'xyz' not in text and 'secret' not in text and 'live.token' not in text

def test_chained_common_name_discovery_preserves_ambiguous_candidates():
 ina=INaturalistAdapter(lambda query:asyncio.sleep(0,result={'results':[
  {'id':67710,'rank':'species','is_active':True,'name':'Sansevieria trifasciata','preferred_common_name':'Snake Plant','matched_term':'Snake Plant','iconic_taxon_name':'Plantae'},
  {'id':168422,'rank':'species','is_active':True,'name':'Sansevieria cylindrica','preferred_common_name':'African Spear','matched_term':'Cylindrical Snake Plant','iconic_taxon_name':'Plantae'}]}))
 chain=ChainedSpeciesEnrichment(ina,TrefleAdapter(lambda q:asyncio.sleep(0,result={'data':[]})),PerenualAdapter(lambda q:asyncio.sleep(0,result={'data':[]})))
 candidates=enrichment_run(chain.discover('Snake Plant'))
 assert [candidate['scientific_name'] for candidate in candidates]==['Sansevieria trifasciata','Sansevieria cylindrica']
 assert candidates[0]['synonyms']==['Snake Plant']

def test_chained_selected_identity_trefle_then_perenual_fallbacks():
 calls=[]
 async def trefle(query):
  calls.append(('trefle',query));return {'data':[{'scientific_name':'Dracaena trifasciata','synonyms':['Sansevieria trifasciata'],'family':'Asparagaceae','genus':'Dracaena'}]}
 async def perenual(query):
  calls.append(('perenual',query))
  if query=='Snake Plant':return {'data':[{'scientific_name':['Sansevieria trifasciata'],'common_name':'Snake Plant','watering':'Minimum','sunlight':['part shade']} ]}
  return {'data':[]}
 selected={'provider_id':67710,'scientific_name':'Sansevieria trifasciata','common_name':'Snake Plant','synonyms':['Snake Plant'],'image_url':'inat.jpg'}
 chain=ChainedSpeciesEnrichment(INaturalistAdapter(lambda q:asyncio.sleep(0,result={})),TrefleAdapter(trefle),PerenualAdapter(perenual))
 result=enrichment_run(chain.enrich_selected('Snake Plant',selected))
 assert result.status=='matched'
 assert result.data['scientific_name']=='Dracaena trifasciata'
 assert result.data['common_name']=='Snake Plant'
 assert result.data['family']=='Asparagaceae' and result.data['genus']=='Dracaena'
 assert result.data['watering_category']=='Minimum'
 assert calls==[('trefle','Sansevieria trifasciata'),('perenual','Dracaena trifasciata'),('perenual','Sansevieria trifasciata'),('perenual','Snake Plant')]

def test_chained_perenual_family_only_match_is_rejected():
 selected={'scientific_name':'Sansevieria trifasciata','common_name':'Snake Plant','synonyms':['Snake Plant']}
 trefle=TrefleAdapter(lambda q:asyncio.sleep(0,result={'data':[{'scientific_name':'Dracaena trifasciata','synonyms':['Sansevieria trifasciata'],'family':'Asparagaceae'}]}))
 perenual=PerenualAdapter(lambda q:asyncio.sleep(0,result={'data':[{'scientific_name':['Agave americana'],'common_name':'Century Plant','family':'Asparagaceae','watering':'Minimum'}]}))
 result=enrichment_run(ChainedSpeciesEnrichment(INaturalistAdapter(lambda q:asyncio.sleep(0,result={})),trefle,perenual).enrich_selected('Snake Plant',selected))
 assert 'watering_category' not in result.data
 assert result.providers==('inaturalist','trefle')


def test_exact_common_name_selection_requires_one_candidate():
 candidates=[
  {'scientific_name':'Sansevieria trifasciata','common_name':'Snake Plant','matched_term':'Snake Plant'},
  {'scientific_name':'Sansevieria cylindrica','common_name':'African Spear','matched_term':'Cylindrical Snake Plant'},
 ]
 assert select_exact_common_name_candidate('Snake Plant',candidates)['scientific_name']=='Sansevieria trifasciata'
 assert select_exact_common_name_candidate('Plant',candidates) is None
 assert select_exact_common_name_candidate('Snake Plant',[candidates[0],dict(candidates[0])]) is None


def test_exact_candidate_selection_accepts_scientific_name_query():
 candidates=[{'scientific_name':'Sansevieria trifasciata','common_name':'Snake Plant','matched_term':'Sansevieria trifasciata'}]
 assert select_exact_common_name_candidate('Sansevieria trifasciata',candidates)==candidates[0]

def test_scientific_name_query_resolves_despite_infraspecific_ambiguity():
 # iNaturalist/Trefle return the species alongside an infraspecific taxon that
 # carries the same matched term; the precise binomial the add flow stored must
 # still resolve to its own taxon so enrichment runs instead of going ambiguous.
 candidates=[
  {'scientific_name':'Dracaena trifasciata','common_name':'Snake Plant','matched_term':'Dracaena trifasciata'},
  {'scientific_name':'Dracaena trifasciata subsp. trifasciata','common_name':None,'matched_term':'Dracaena trifasciata'},
 ]
 assert select_exact_common_name_candidate('Dracaena trifasciata',candidates)['scientific_name']=='Dracaena trifasciata'

def test_inaturalist_derives_genus_from_binomial_when_taxonomy_absent():
 # iNaturalist autocomplete carries no family/genus fields, so a keyless install
 # still gets the genus from the species binomial (family needs Trefle).
 async def req(q):return {'results':[{'name':'Dracaena trifasciata','rank':'species','preferred_common_name':'Snake Plant','default_photo':{'medium_url':'m.jpg'},'id':1}]}
 candidates=enrichment_run(INaturalistAdapter(req).search('snake plant'))
 assert candidates[0]['genus']=='Dracaena' and candidates[0]['family'] is None and candidates[0]['scientific_name']=='Dracaena trifasciata'


# ---- from test_enrichment_provider_path_017.py ----
def enrichment_provider_path_017_run(coro): return asyncio.run(coro)

def test_synonym_canonicalizes_to_accepted_name_via_trefle():
 # iNaturalist's active name here is the older synonym; Trefle supplies the
 # accepted name and lists the synonym, so the chain canonicalizes generally -
 # no per-species special case.
 async def ina(q): return {"results":[{"id":67710,"name":"Sansevieria trifasciata","preferred_common_name":"Snake Plant","matched_term":"Snake Plant"}]}
 async def trefle(q): return {"data":[{"id":375325,"scientific_name":"Dracaena trifasciata","synonyms":["Sansevieria trifasciata"],"family":"Asparagaceae","genus":"Dracaena"}]}
 async def empty(q): return {"data":[]}
 chain=ChainedSpeciesEnrichment(INaturalistAdapter(ina),TrefleAdapter(trefle),PerenualAdapter(empty,""))
 candidates=enrichment_provider_path_017_run(chain.discover("Snake Plant"))
 result=enrichment_provider_path_017_run(chain.enrich_selected("Snake Plant",candidates[0]))
 assert result.data["scientific_name"]=="Dracaena trifasciata"
 assert result.data["family"]=="Asparagaceae" and result.data["common_name"]=="Snake Plant"

def test_without_a_resolving_provider_inaturalist_name_is_kept_not_faked():
 # No provider can supply an accepted name, so the chain keeps what iNaturalist
 # returned instead of inventing one - consistent behaviour for every species.
 async def ina(q): return {"results":[{"id":67710,"name":"Sansevieria trifasciata","preferred_common_name":"Snake Plant","matched_term":"Snake Plant"}]}
 async def empty(q): return {"data":[]}
 chain=ChainedSpeciesEnrichment(INaturalistAdapter(ina),TrefleAdapter(empty,""),PerenualAdapter(empty,""))
 candidates=enrichment_provider_path_017_run(chain.discover("Snake Plant"))
 result=enrichment_provider_path_017_run(chain.enrich_selected("Snake Plant",candidates[0]))
 assert result.data["scientific_name"]=="Sansevieria trifasciata"
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
 enrichment_provider_path_017_run(exercise())
 assert calls==1


# ---- from test_species.py ----
def test_normalize_species_key():
    assert normalize_species_key("  Dracaena_trifasciata!! ")=="dracaena trifasciata"

def test_match_classes():
    exact={"scientific_name":"Dracaena trifasciata","common_name":"Snake plant","synonyms":["Sansevieria trifasciata"],"family":"Asparagaceae"}
    assert classify_match("snake plant",exact)=="confirmed"
    assert classify_match("Dracaena trifasciata",exact)=="confirmed"
    assert classify_match("Dracaena green",exact,known_family="Asparagaceae")=="strong"
    assert classify_match("plant",exact)=="ambiguous"
    assert classify_match("rose",exact)=="rejected"

def test_field_owners_and_provenance():
    merged=merge_provider_fields({"trefle":{"scientific_name":"Dracaena trifasciata","image_url":"t"},"perenual":{"common_name":"Snake plant","watering_category":"minimum","image_url":"p"},"inaturalist":{"image_url":"i"}})
    assert merged["scientific_name"]=="Dracaena trifasciata"
    assert merged["common_name"]=="Snake plant"
    assert merged["image_url"]=="i"
    assert merged["provenance"]["image_url"]=="inaturalist"


def test_trefle_care_parser_extracts_growth_and_specifications_and_drops_nulls():
    care=parse_trefle_care({
        'growth':{'light':7,'atmospheric_humidity':5,'soil_humidity':4,'ph_minimum':6.0,'ph_maximum':7.5,'minimum_temperature':{'deg_c':10,'deg_f':50},'maximum_temperature':{'deg_c':30,'deg_f':86},'growth_months':None},
        'specifications':{'growth_habit':'Herb','growth_rate':'Slow','toxicity':'low','average_height':{'cm':90},'maximum_height':{'cm':None}},
        'duration':['perennial'],'edible':False,
    })
    assert care['light_requirement']==7 and care['humidity_requirement']==5 and care['soil_moisture_requirement']==4
    assert care['ph_minimum']==6.0 and care['ph_maximum']==7.5
    assert care['minimum_temperature_c']==10 and care['maximum_temperature_c']==30
    assert care['growth_habit']=='Herb' and care['growth_rate']=='Slow' and care['toxicity']=='low' and care['average_height_cm']==90
    assert care['duration']==['perennial'] and care['edible'] is False
    assert 'growth_months' not in care

def test_enrich_selected_chains_to_trefle_detail_for_care_fields():
    async def trefle_search(q):
        return {'data':[{'id':375325,'scientific_name':'Dracaena trifasciata','synonyms':['Sansevieria trifasciata'],'family':'Asparagaceae','genus':'Dracaena','image_url':'t.jpg'}]}
    detail_calls=[]
    async def trefle_detail(species_id):
        detail_calls.append(species_id)
        return {'data':{'growth':{'light':7,'soil_humidity':4},'specifications':{'toxicity':'low'}}}
    async def perenual(q):return {'data':[]}
    chain=ChainedSpeciesEnrichment(INaturalistAdapter(lambda q:asyncio.sleep(0,result={})),TrefleAdapter(trefle_search,trefle_detail),PerenualAdapter(perenual))
    selected={'scientific_name':'Dracaena trifasciata','common_name':'Snake Plant','synonyms':['Sansevieria trifasciata']}
    result=enrichment_run(chain.enrich_selected('Snake Plant',selected))
    assert detail_calls==[375325]
    assert result.data['light_requirement']==7 and result.data['soil_moisture_requirement']==4 and result.data['toxicity']=='low'
    assert result.data['scientific_name']=='Dracaena trifasciata' and result.data['family']=='Asparagaceae'

def test_provider_failure_does_not_discard_inaturalist_match():
    async def trefle_search(q):raise ProviderError('rate',429)
    async def perenual(q):raise ProviderError('provider',500)
    chain=ChainedSpeciesEnrichment(INaturalistAdapter(lambda q:asyncio.sleep(0,result={})),TrefleAdapter(trefle_search),PerenualAdapter(perenual))
    selected={'scientific_name':'Dracaena trifasciata','common_name':'Snake Plant'}
    result=enrichment_run(chain.enrich_selected('Snake Plant',selected))
    assert result.status=='matched'
    assert result.data['scientific_name']=='Dracaena trifasciata' and result.data['common_name']=='Snake Plant'

def test_rate_limit_gate_self_regulates_on_remaining_and_429():
    from domain.rate_limit import RateLimitGate
    gate=RateLimitGate()
    assert gate.allow(1000.0)
    gate.observe(200,'5','2000',1000.0); assert gate.allow(1000.0)
    gate.observe(200,'0','1060',1000.0)
    assert not gate.allow(1000.0) and not gate.allow(1059.0) and gate.allow(1060.0)
    recovered=RateLimitGate(); recovered.observe(429,'0','5000',1000.0); assert not recovered.allow(1000.0)
    recovered.observe(200,'10','6000',1000.0); assert recovered.allow(1000.0)
    cooldown=RateLimitGate(cooldown_seconds=30.0); cooldown.observe(429,None,None,1000.0)
    assert not cooldown.allow(1029.0) and cooldown.allow(1030.0)


# ---- from test_image_proxy.py ----
NOW=datetime(2026,1,1,tzinfo=timezone.utc)
def image_proxy_run(c):return asyncio.run(c)
def image(size=(1200,800),fmt='JPEG'):
 out=io.BytesIO();Image.new('RGB',size,(20,100,40)).save(out,fmt);return out.getvalue()
def response(body=None,url='https://images.example/plant.jpg',ctype='image/jpeg',status=200,headers=None):return DownloadResponse(status,headers or {'Content-Type':ctype},image() if body is None else body,url)
def public(host):return ('93.184.216.34',)
def test_https_only_dns_private_and_redirect_ssrf(tmp_path):
 fetch=lambda u:asyncio.sleep(0,result=response());p=SpeciesImageProxy(tmp_path,fetch,public)
 with pytest.raises(ImageProxyError):image_proxy_run(p.refresh('a','http://images.example/a.jpg',NOW))
 with pytest.raises(ImageProxyError):image_proxy_run(SpeciesImageProxy(tmp_path,fetch,lambda h:('127.0.0.1',)).refresh('a','https://images.example/a.jpg',NOW))
 async def redirect(u):return DownloadResponse(302,{'Location':'https://localhost/private'},b'',u)
 with pytest.raises(ImageProxyError):image_proxy_run(SpeciesImageProxy(tmp_path,redirect,lambda h:('127.0.0.1',) if h=='localhost' else public(h)).refresh('a','https://images.example/a.jpg',NOW))
def test_format_size_dimensions_and_decompression_limits(tmp_path):
 # A real image is accepted regardless of a wrong or missing HTTP Content-Type...
 ok,w,h=transform_thumbnail(image(),'text/html');assert ok[:4]==b'RIFF' and w<=512 and h<=512
 assert transform_thumbnail(image(),None)
 # ...but bytes that do not decode as an allowed image format are rejected.
 with pytest.raises(ImageProxyError,match='image'):transform_thumbnail(b'not-a-real-image'*8,'image/jpeg')
 with pytest.raises(ImageProxyError,match='size'):transform_thumbnail(b'x'*(MAX_DOWNLOAD+1),'image/jpeg')
 with pytest.raises(ImageProxyError,match='dimensions'):transform_thumbnail(image((9000,1),'PNG'),'image/png')
 bomb=Image.MAX_IMAGE_PIXELS;Image.MAX_IMAGE_PIXELS=100
 try:
  with pytest.raises(ImageProxyError,match='image'):transform_thumbnail(image((20,20),'PNG'),'image/png')
 finally:Image.MAX_IMAGE_PIXELS=bomb
def test_refresh_accepts_generic_or_missing_content_type(tmp_path):
 # S3 / iNaturalist open-data frequently serve a real image as octet-stream.
 p=SpeciesImageProxy(tmp_path,lambda u:asyncio.sleep(0,result=response(ctype='application/octet-stream')),public)
 item=image_proxy_run(p.refresh('snake','https://images.example/a.jpg',NOW))
 assert item.content_type=='image/webp' and item.path.exists()
def test_static_thumbnail_content_addressed_cache_and_dedup(tmp_path):
 data=image();p=SpeciesImageProxy(tmp_path,lambda u:asyncio.sleep(0,result=response(data)),public);a=image_proxy_run(p.refresh('snake','https://images.example/a.jpg',NOW));b=image_proxy_run(p.refresh('other','https://images.example/b.jpg',NOW))
 assert a.digest==b.digest and a.width<=512 and a.height<=512 and len(list(tmp_path.glob('*.webp')))==1
 with Image.open(a.path) as im:assert im.format=='WEBP' and im.size==(512,341)
def test_auth_etag_and_cache_headers(tmp_path):
 p=SpeciesImageProxy(tmp_path,lambda u:asyncio.sleep(0,result=response()),public);item=image_proxy_run(p.refresh('a','https://images.example/a.jpg',NOW))
 assert p.serve(item.digest,False).status==401
 first=p.serve(item.digest,True);assert first.status==200 and first.headers['ETag']==f'"{item.digest}"' and 'immutable' in first.headers['Cache-Control']
 assert p.serve(item.digest,True,first.headers['ETag']).status==304 and p.serve('0'*64,True).status==404
def test_gc_preserves_referenced_and_removes_old_orphan(tmp_path):
 p=SpeciesImageProxy(tmp_path,lambda u:asyncio.sleep(0,result=response()),public);active=image_proxy_run(p.refresh('a','https://images.example/a.jpg',NOW));orphan='f'*64;op=tmp_path/f'{orphan}.webp';op.write_bytes(active.path.read_bytes());old=(NOW-timedelta(days=40)).timestamp();os.utime(op,(old,old))
 assert p.garbage_collect(NOW)==(orphan,) and active.path.exists()
def test_refresh_failure_preserves_stale_image(tmp_path):
 state={'fail':False}
 async def fetch(u):
  if state['fail']:raise TimeoutError
  return response()
 p=SpeciesImageProxy(tmp_path,fetch,public);old=image_proxy_run(p.refresh('a','https://images.example/a.jpg',NOW));state['fail']=True;kept=image_proxy_run(p.refresh('a','https://images.example/new.jpg',NOW+timedelta(days=1)));assert kept.digest==old.digest and old.path.exists()
def test_reported_size_and_redirect_limit(tmp_path):
 async def huge(u):return response(headers={'Content-Type':'image/jpeg','Content-Length':str(MAX_DOWNLOAD+1)})
 with pytest.raises(ImageProxyError,match='size'):image_proxy_run(SpeciesImageProxy(tmp_path,huge,public).refresh('a','https://images.example/a.jpg',NOW))
 async def loop(u):return DownloadResponse(302,{'Location':'/again'},b'',u)
 with pytest.raises(ImageProxyError,match='redirect_limit'):image_proxy_run(SpeciesImageProxy(tmp_path,loop,public).refresh('a','https://images.example/a.jpg',NOW,max_redirects=1))


def test_blocking_work_runs_through_the_injected_executor(tmp_path):
    # In Home Assistant, run_blocking is hass.async_add_executor_job, so DNS
    # validation, image decoding, file writes and serving never block the loop.
    ran=[]
    async def run_blocking(func,*args):
        ran.append(getattr(func,'__name__',repr(func)))
        return await asyncio.to_thread(func,*args)
    p=SpeciesImageProxy(tmp_path,lambda u:asyncio.sleep(0,result=response()),public,run_blocking)
    item=image_proxy_run(p.refresh('snake','https://images.example/a.jpg',NOW))
    served=image_proxy_run(p.async_serve(item.digest,True))
    assert 'validate_url' in ran and '_store' in ran and 'serve' in ran
    assert served.status==200 and served.body[:4]==b'RIFF'


# ---- per-provider matching (real provider responses) -----------------------
import json as _json
from pathlib import Path as _Path
from domain.config import PlantConfig
from domain.config import ValidationError as _VE

_FIX = _Path(__file__).resolve().parents[1] / "fixtures"


def _fixture(name):
    return _json.loads((_FIX / name).read_text())


def _served(raw):
    async def request(_arg):
        return {"http_status": raw.get("http_status", 200), "body": raw.get("body", raw)}
    return request


def test_trefle_search_candidates_from_live_response_rank_the_accepted_species_first():
    raw = _fixture("trefle/dracaena_trifasciata_search.json")
    found = enrichment_run(TrefleAdapter(_served(raw)).search("Dracaena trifasciata"))
    assert [c["id"] for c in found] == [375325, 453823]
    # iNaturalist still calls it Sansevieria trifasciata; Trefle lists that as a
    # synonym of the accepted species only.
    ranked = rank_candidates(found, ["Sansevieria trifasciata", "Snake Plant"])
    assert ranked[0]["id"] == 375325 and is_exact_candidate(ranked[0], ["Sansevieria trifasciata"])
    assert not is_exact_candidate(ranked[1], ["Sansevieria trifasciata"])
    assert "little or no growth data" in describe_candidate("trefle", ranked[0])
    assert describe_candidate("trefle", ranked[1]).startswith("Dracaena trifasciata subsp. trifasciata (ssp")


def test_trefle_record_by_id_from_live_detail_is_taxonomy_only_for_this_species():
    raw = _fixture("trefle/dracaena_trifasciata_details.json")
    record = enrichment_run(TrefleAdapter(_served(raw), _served(raw)).record(375325))
    assert record["scientific_name"] == "Dracaena trifasciata" and record["family"] == "Asparagaceae"
    assert record["synonyms"] == ["Sansevieria trifasciata"]
    assert not any(key in record for key in ("light_requirement", "toxicity", "ph_minimum"))


def test_trefle_record_carries_growth_data_when_trefle_has_it():
    raw = _fixture("trefle/monstera_deliciosa_details.json")
    record = enrichment_run(TrefleAdapter(_served(raw), _served(raw)).record(1))
    assert record["scientific_name"] == "Monstera deliciosa" and record["family"] == "Araceae"
    assert record["growth_habit"] == "Vine, Forb/herb" and record["edible"] is False


def test_perenual_record_by_id_reads_watering_and_sunlight_from_details():
    raw = _fixture("perenual/free_details_success.json")
    record = enrichment_run(PerenualAdapter(_served(raw), "k", detail_request=_served(raw)).record(1))
    assert record["watering_category"] == "Frequent"
    assert record["sunlight_requirements"] == ["full sun"]
    assert record["scientific_name"] == "Abies alba"


def test_perenual_paid_only_record_is_a_plan_error_not_a_silent_miss():
    raw = _fixture("perenual/paid_details_restricted.json")
    with pytest.raises(ProviderError) as err:
        enrichment_run(PerenualAdapter(_served(raw), "k", detail_request=_served(raw)).record(4000))
    assert err.value.kind == "plan"


def test_perenual_paywall_placeholders_are_dropped():
    locked = "Upgrade Plans To Premium/Supreme - https://perenual.com/subscription-api-pricing. I'm sorry"
    items = {"data": [{"id": 4127, "common_name": "Snake plant", "scientific_name": ["Dracaena trifasciata"],
                       "watering": locked, "sunlight": [locked], "cycle": locked}]}
    found = enrichment_run(PerenualAdapter(lambda q: asyncio.sleep(0, result=items)).search("x"))
    assert found[0]["id"] == 4127 and found[0]["watering_category"] is None
    assert found[0]["sunlight_requirements"] is None
    assert "paid Perenual plan" in describe_candidate("perenual", found[0], perenual_free=True)
    assert "paid" not in describe_candidate("perenual", {**found[0], "id": 12}, perenual_free=True)


class _Adapter:
    def __init__(self, record=None, error=None):
        self.value, self.error, self.calls = record or {}, error, 0

    async def record(self, _id):
        self.calls += 1
        if self.error:
            raise self.error
        return dict(self.value)


SOURCES = {
    "inaturalist": {"id": 67710, "name": "Sansevieria trifasciata", "common_name": "Snake Plant", "image_url": "i.jpg"},
    "trefle": {"id": 375325, "name": "Dracaena trifasciata"},
    "perenual": {"id": 1, "name": "Dracaena trifasciata"},
}


def test_source_enrichment_merges_the_chosen_records_by_id():
    trefle = _Adapter({"scientific_name": "Dracaena trifasciata", "family": "Asparagaceae", "genus": "Dracaena"})
    perenual = _Adapter({"scientific_name": "Dracaena trifasciata", "watering_category": "Minimum",
                         "sunlight_requirements": ["part shade"]})
    result = enrichment_run(SourceEnrichment(trefle=trefle, perenual=perenual).enrich(SOURCES))
    assert result.data["scientific_name"] == "Dracaena trifasciata"  # Trefle's accepted name
    assert result.data["family"] == "Asparagaceae"
    assert result.data["watering_category"] == "Minimum"
    assert result.data["image_url"] == "i.jpg" and result.data["common_name"] == "Snake Plant"
    assert set(result.providers) == {"inaturalist", "trefle", "perenual"}


def test_skipped_and_failing_providers_never_disturb_the_others():
    trefle = _Adapter(error=ProviderError("network"))
    result = enrichment_run(SourceEnrichment(trefle=trefle, perenual=None).enrich(
        {**SOURCES, "perenual": "skip"}))
    assert result.status == "matched" and result.providers == ("inaturalist",)
    assert result.data["scientific_name"] == "Sansevieria trifasciata"


def test_records_are_cached_and_a_stale_record_beats_an_outage():
    b, s = store()
    trefle = _Adapter({"scientific_name": "Dracaena trifasciata", "family": "Asparagaceae"})
    first = SourceEnrichment(trefle=trefle, storage=s)
    enrichment_run(first.load())
    enrichment_run(first.enrich(SOURCES, now=datetime(2026, 9, 25, tzinfo=timezone.utc)))
    enrichment_run(first.enrich(SOURCES, now=datetime(2026, 9, 26, tzinfo=timezone.utc)))
    assert trefle.calls == 1  # the second start is served from the cache
    # A restart after the cache expired, with Trefle down: the stale record is used.
    down = _Adapter(error=ProviderError("network"))
    later = SourceEnrichment(trefle=down, storage=s)
    enrichment_run(later.load())
    result = enrichment_run(later.enrich(SOURCES, now=datetime(2027, 6, 1, tzinfo=timezone.utc)))
    assert down.calls == 1 and result.data["family"] == "Asparagaceae"


def test_a_paid_only_perenual_record_is_not_retried_every_start():
    perenual = _Adapter(error=ProviderError("plan", 429))
    source = SourceEnrichment(perenual=perenual)
    now = datetime(2026, 9, 25, tzinfo=timezone.utc)
    for day in range(5):
        enrichment_run(source.enrich(SOURCES, now=now + timedelta(days=day)))
    assert perenual.calls == 1


def test_species_sources_are_validated_on_the_plant():
    base = {"display_name": "Snake Plant", "soil_moisture": "sensor.m", "placement": "indoor"}
    config = PlantConfig.normalize({**base, "species_sources": {
        "inaturalist": {"id": 67710, "name": "Sansevieria trifasciata", "nested": {"x": 1}},
        "trefle": "skip"}}, plant_uuid="a" * 32)
    assert config.species_sources == {"inaturalist": {"id": 67710, "name": "Sansevieria trifasciata"},
                                      "trefle": "skip"}
    for bad in ({"gbif": "skip"}, {"trefle": {"name": "no id"}}, ["trefle"]):
        with pytest.raises(_VE):
            PlantConfig.normalize({**base, "species_sources": bad}, plant_uuid="a" * 32)


def _perenual_search(name):
    raw = _fixture(f"perenual/{name}")
    return enrichment_run(PerenualAdapter(lambda q: asyncio.sleep(0, result=raw), "k").search("q"))


def test_live_perenual_search_finds_the_snake_plant_behind_the_free_plan_paywall():
    found = _perenual_search("sansevieria_trifasciata_search.json")
    ranked = rank_candidates(found, ["Dracaena trifasciata", "Sansevieria trifasciata"])
    assert ranked[0]["id"] == 7171 and is_exact_candidate(ranked[0], ["Sansevieria trifasciata"])
    # Cultivars share the species epithet but are not the species itself.
    assert not any(is_exact_candidate(c, ["Sansevieria trifasciata"]) for c in ranked[1:])
    # Perenual swaps in an upgrade_access placeholder image for records the key
    # cannot open; that is detected per record, and no image is ever kept.
    assert ranked[0]["restricted"] is True and "image_url" not in ranked[0]
    assert "needs a paid Perenual plan" in describe_candidate("perenual", ranked[0], perenual_free=False)
    assert is_restricted(ranked[0], perenual_free=False)


def test_common_names_never_count_as_an_exact_match():
    found = _perenual_search("snake_plant_search.json")
    patens = next(c for c in found if c["id"] == 7168)
    assert patens["common_name"] == "snake plant"  # a different species entirely
    assert not is_exact_candidate(patens, ["Snake Plant", "snake plant", "Dracaena trifasciata"])
    # The one record inside the free range carries a real photo, not the placeholder.
    calathea = next(c for c in found if c["id"] == 1469)
    assert calathea["restricted"] is False and not is_restricted(calathea, perenual_free=True)
    assert looks_scientific("Sansevieria trifasciata") and not looks_scientific("Snake Plant")
    assert not looks_scientific("mother-in-law's tongue")


def test_the_current_name_is_simply_absent_from_perenual():
    assert _perenual_search("dracaena_trifasciata_search.json") == []


def test_live_free_tier_details_keep_only_the_useful_core_record():
    raw = _fixture("perenual/calathea_lancifolia_details_free.json")
    record = enrichment_run(PerenualAdapter(_served(raw), "k", detail_request=_served(raw)).record(1469))
    assert record["scientific_name"] == "Calathea lancifolia" and record["family"] == "Marantaceae"
    assert record["watering_category"] == "Average"
    assert record["sunlight_requirements"] == ["part shade", "part sun/part shade"]
    assert record["care_level"] == "Medium" and record["growth_rate"] == "Low"
    assert record["indoor"] is True and record["drought_tolerant"] is False
    assert record["poisonous_to_pets"] is False and record["poisonous_to_humans"] is False
    # Null benchmark: no interval. Supreme-only fields, images, and the
    # key-bearing hardiness/care-guide URLs are never kept.
    assert "watering_interval" not in record and "image_url" not in record
    flat = _json.dumps(record)
    assert "key=" not in flat and "Upgrade" not in flat and "x" + "Watering" not in flat


def test_watering_interval_is_readable_and_paywall_safe():
    from domain.enrichment import _watering_interval
    assert _watering_interval({"value": "5-7", "unit": "days"}) == "every 5-7 days"
    assert _watering_interval({"value": '"7"', "unit": "days"}) == "every 7 days"
    assert _watering_interval({"value": None, "unit": "days"}) is None
    assert _watering_interval({"value": "Upgrade Plan To Supreme For Access", "unit": "days"}) is None


def test_live_paywalled_details_response_is_a_plan_error():
    raw = _fixture("perenual/paywalled_details_7171.json")
    with pytest.raises(ProviderError) as err:
        enrichment_run(PerenualAdapter(_served(raw), "k", detail_request=_served(raw)).record(7171))
    assert err.value.kind == "plan" and err.value.status == 429
