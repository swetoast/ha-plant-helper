from __future__ import annotations
import asyncio,re
from dataclasses import dataclass
from datetime import datetime,timedelta,timezone
from typing import Any,Awaitable,Callable,Mapping
from .species import classify_match,merge_provider_fields,normalize_species_key
from .storage import PlantHelperStorage

CACHE_TTL=timedelta(days=30);NEGATIVE_TTL=timedelta(days=7);TRANSIENT_BACKOFF=timedelta(minutes=5);RATE_BACKOFF=timedelta(minutes=20)
class ProviderError(RuntimeError):
 def __init__(self,kind:str,status:int|None=None,message:str=''):super().__init__(kind);self.kind=kind;self.status=status;self.message=message
@dataclass(frozen=True,slots=True)
class ProviderCandidate:
 provider:str;data:dict[str,Any];match:str
@dataclass(frozen=True,slots=True)
class EnrichmentResult:
 species_key:str;status:str;data:dict[str,Any];providers:tuple[str,...];cached:bool

def redact(value:Any,secrets:tuple[str,...]=())->str:
 text=str(value)
 for secret in secrets:
  if secret:text=text.replace(secret,'[redacted]')
 text=re.sub(r'(?i)(key|token|authorization|api_key)=([^&\s]+)',r'\1=[redacted]',text)
 text=re.sub(r'(?i)(bearer)\s+[A-Za-z0-9._~+/-]+',r'\1 [redacted]',text)
 return text

def _first(value:Any)->Any:return value[0] if isinstance(value,list) and value else value
class PerenualAdapter:
 name='perenual'
 def __init__(self,request:Callable[[str],Awaitable[Mapping[str,Any]]],credential:str=''):self.request=request;self.credential=credential
 async def search(self,query:str)->list[dict[str,Any]]:
  raw=await self.request(query);items=raw.get('data',raw.get('results',[]))
  return [{'scientific_name':_first(x.get('scientific_name')),'common_name':x.get('common_name'),'family':x.get('family'),'genus':x.get('genus'),'synonyms':x.get('synonyms',[]),'watering_category':x.get('watering'),'sunlight_requirements':x.get('sunlight'),'image_url':(x.get('default_image') or {}).get('regular_url')} for x in items]
class TrefleAdapter:
 name='trefle'
 def __init__(self,request:Callable[[str],Awaitable[Mapping[str,Any]]],credential:str=''):self.request=request;self.credential=credential
 async def search(self,query:str)->list[dict[str,Any]]:
  raw=await self.request(query);items=raw.get('data',[])
  return [{'scientific_name':x.get('scientific_name'),'common_name':x.get('common_name'),'family':x.get('family'),'genus':x.get('genus'),'synonyms':x.get('synonyms',[]),'image_url':x.get('image_url')} for x in items]
class INaturalistAdapter:
 name='inaturalist'
 def __init__(self,request:Callable[[str],Awaitable[Mapping[str,Any]]],credential:str=''):self.request=request;self.credential=credential
 async def search(self,query:str)->list[dict[str,Any]]:
  raw=await self.request(query);items=raw.get('results',[])
  return [{'scientific_name':x.get('name'),'common_name':x.get('preferred_common_name'),'family':x.get('family'),'genus':x.get('genus'),'synonyms':x.get('names',[]),'image_url':(x.get('default_photo') or {}).get('medium_url')} for x in items]

class SpeciesEnrichment:
 def __init__(self,storage:PlantHelperStorage,providers:list[Any]):
  self.storage=storage;self.providers={p.name:p for p in providers};self.cache={};self.species_flights={};self.provider_flights={};self.backoff_until={};self.auth_suspended=set()
 async def load(self)->None:
  snapshot=await self.storage.async_snapshot();self.cache={k:dict(v) for k,v in snapshot.data['species_cache'].items()}
 def _cache_result(self,key:str,now:datetime)->EnrichmentResult|None:
  item=self.cache.get(key)
  if not item:return None
  try:expires=datetime.fromisoformat(item['expires_at'])
  except (KeyError,ValueError,TypeError):return None
  if expires.tzinfo is None:expires=expires.replace(tzinfo=timezone.utc)
  if now>=expires:return None
  return EnrichmentResult(key,item['status'],dict(item.get('data',{})),tuple(item.get('providers',[])),True)
 async def enrich(self,species:str,now:datetime|None=None)->EnrichmentResult:
  now=now or datetime.now(timezone.utc);key=normalize_species_key(species);cached=self._cache_result(key,now)
  if cached:return cached
  if key in self.species_flights:return await self.species_flights[key]
  task=asyncio.create_task(self._enrich(key,species,now));self.species_flights[key]=task
  try:return await task
  finally:self.species_flights.pop(key,None)
 async def _provider(self,provider:Any,query:str,now:datetime)->list[dict[str,Any]]:
  name=provider.name;flight_key=(name,normalize_species_key(query))
  if name in self.auth_suspended or now<self.backoff_until.get(name,datetime.min.replace(tzinfo=timezone.utc)):return None
  if flight_key in self.provider_flights:return await self.provider_flights[flight_key]
  async def call():
   try:return await provider.search(query)
   except ProviderError as err:
    if err.kind=='auth' or err.status in {401,403}:self.auth_suspended.add(name)
    elif err.kind=='rate' or err.status==429:self.backoff_until[name]=now+RATE_BACKOFF
    else:self.backoff_until[name]=now+TRANSIENT_BACKOFF
    return None
   except Exception as err:
    self.backoff_until[name]=now+TRANSIENT_BACKOFF;_ = redact(err,getattr(provider,'credential','') and (provider.credential,) or ());return None
  task=asyncio.create_task(call());self.provider_flights[flight_key]=task
  try:return await task
  finally:self.provider_flights.pop(flight_key,None)
 async def _enrich(self,key:str,query:str,now:datetime)->EnrichmentResult:
  provider_results={};ambiguous=False;successful=0;canonical=set();scored=[]
  results=await asyncio.gather(*(self._provider(p,query,now) for p in self.providers.values()))
  query_tokens=normalize_species_key(query).split()
  for provider,candidates in zip(self.providers.values(),results):
   if candidates is None:continue
   successful+=1;provider_scored=[]
   for candidate in candidates:
    match=classify_match(query,candidate)
    if match=='strong' and len(query_tokens)<2:match='ambiguous'
    provider_scored.append((candidate,match))
    if match in {'confirmed','strong'}:
     scientific=normalize_species_key(str(candidate.get('scientific_name','')))
     if scientific:canonical.add(scientific)
    elif match=='ambiguous':ambiguous=True
   scored.append((provider,provider_scored))
  for provider,candidates in scored:
   best=None
   for candidate,match in candidates:
    scientific=normalize_species_key(str(candidate.get('scientific_name','')))
    if match in {'confirmed','strong'} or scientific in canonical:
     best=ProviderCandidate(provider.name,candidate,match if match in {'confirmed','strong'} else 'confirmed');break
   if best:provider_results[provider.name]=best.data
  if provider_results:status='matched';data=merge_provider_fields(provider_results);ttl=CACHE_TTL
  elif ambiguous:status='ambiguous';data={};ttl=NEGATIVE_TTL
  elif successful:status='not_found';data={};ttl=NEGATIVE_TTL
  else:return EnrichmentResult(key,'unavailable',{},tuple(),False)
  stored={'status':status,'data':data,'providers':sorted(provider_results),'expires_at':(now+ttl).isoformat()};self.cache[key]=stored;await self.storage.async_set_species_cache(key,stored)
  return EnrichmentResult(key,status,data,tuple(sorted(provider_results)),False)
