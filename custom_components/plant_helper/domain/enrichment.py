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
  raw=await self.request(query)
  status=int(raw.get('http_status',raw.get('status',200)))
  payload=raw.get('body',raw)
  if status>=400:
   message=str(payload)
   kind='plan' if status==429 and 'upgrade plan' in message.casefold() else 'rate' if status==429 else 'auth' if status in {401,403} else 'provider'
   raise ProviderError(kind,status,redact(message,(self.credential,) if self.credential else ()))
  if not isinstance(payload,Mapping):return []
  items=payload.get('data',payload.get('results'))
  if isinstance(items,Mapping):items=[items]
  elif not isinstance(items,list):items=[payload] if payload.get('scientific_name') else []
  return [{'scientific_name':_first(x.get('scientific_name')),'common_name':x.get('common_name'),'family':x.get('family'),'genus':x.get('genus'),'synonyms':x.get('synonyms',[]),'watering_category':x.get('watering'),'sunlight_requirements':x.get('sunlight'),'image_url':(x.get('default_image') or {}).get('regular_url')} for x in items]
class TrefleAdapter:
 name='trefle'
 def __init__(self,request:Callable[[str],Awaitable[Mapping[str,Any]]],credential:str=''):self.request=request;self.credential=credential
 async def search(self,query:str)->list[dict[str,Any]]:
  raw=await self.request(query)
  status=int(raw.get('http_status',raw.get('status',200)))
  if status>=400:raise ProviderError('rate' if status==429 else 'auth' if status in {401,403} else 'provider',status)
  payload=raw.get('body',raw)
  items=payload.get('data',[]) if isinstance(payload,Mapping) else []
  if isinstance(items,Mapping):items=[items]
  elif not isinstance(items,list):items=[]
  return [{'scientific_name':x.get('scientific_name'),'common_name':x.get('common_name'),'family':x.get('family'),'genus':x.get('genus'),'synonyms':x.get('synonyms',[]),'image_url':x.get('image_url')} for x in items]
class INaturalistAdapter:
 name='inaturalist'
 def __init__(self,request:Callable[[str],Awaitable[Mapping[str,Any]]],credential:str=''):self.request=request;self.credential=credential
 async def search(self,query:str)->list[dict[str,Any]]:
  raw=await self.request(query)
  status=int(raw.get('http_status',raw.get('status',200)))
  payload=raw.get('body',raw)
  if status>=400:raise ProviderError('rate' if status==429 else 'auth' if status in {401,403} else 'provider',status,redact(payload,(self.credential,) if self.credential else ()))
  items=payload.get('results',[]) if isinstance(payload,Mapping) else []
  if not isinstance(items,list):return []
  candidates=[]
  for item in items:
   if not isinstance(item,Mapping) or item.get('is_active') is False or item.get('extinct') is True or item.get('provisional') is True:continue
   if item.get('rank') not in {None,'species'} or item.get('iconic_taxon_name') not in {None,'Plantae'}:continue
   synonyms=list(item.get('names',[])) if isinstance(item.get('names',[]),list) else []
   matched=item.get('matched_term')
   if matched and normalize_species_key(str(matched)) not in {normalize_species_key(str(value)) for value in synonyms}:synonyms.append(matched)
   candidates.append({'scientific_name':item.get('name'),'common_name':item.get('preferred_common_name'),'family':item.get('family'),'genus':item.get('genus'),'synonyms':synonyms,'image_url':(item.get('default_photo') or {}).get('medium_url'),'provider_id':item.get('id'),'matched_term':matched})
  return candidates

@dataclass(frozen=True,slots=True)
class ResolvedIdentity:
 scientific_name:str
 common_name:str|None
 aliases:tuple[str,...]
 family:str|None=None
 genus:str|None=None
 provider_id:int|None=None

class ChainedSpeciesEnrichment:
 def __init__(self,inaturalist:INaturalistAdapter,trefle:TrefleAdapter,perenual:PerenualAdapter):
  self.inaturalist=inaturalist;self.trefle=trefle;self.perenual=perenual
 async def discover(self,common_name:str)->list[dict[str,Any]]:
  return await self.inaturalist.search(common_name)
 async def enrich_selected(self,common_name:str,selected:Mapping[str,Any])->EnrichmentResult:
  scientific=str(selected.get('scientific_name','')).strip()
  if not scientific:raise ValueError('selected candidate requires scientific_name')
  identity=ResolvedIdentity(scientific,str(selected.get('common_name') or common_name),tuple(dict.fromkeys([scientific,*[str(v) for v in selected.get('synonyms',[]) if v]])),provider_id=selected.get('provider_id'))
  trefle_candidates=await self.trefle.search(identity.scientific_name)
  trefle_match=next((candidate for candidate in trefle_candidates if _identity_match(identity.aliases,candidate)),None)
  if trefle_match:
   aliases=tuple(dict.fromkeys([*identity.aliases,str(trefle_match.get('scientific_name') or ''),*[str(v) for v in trefle_match.get('synonyms',[]) if v]]))
   identity=ResolvedIdentity(str(trefle_match.get('scientific_name') or identity.scientific_name),identity.common_name,tuple(v for v in aliases if v),trefle_match.get('family'),trefle_match.get('genus'),identity.provider_id)
  perenual_match=None
  queries=tuple(dict.fromkeys([identity.scientific_name,*identity.aliases,common_name]))
  for query in queries:
   candidates=await self.perenual.search(query)
   perenual_match=next((candidate for candidate in candidates if _identity_match((*identity.aliases,identity.scientific_name,common_name),candidate)),None)
   if perenual_match:break
  results={'inaturalist':dict(selected)}
  if trefle_match:results['trefle']=trefle_match
  if perenual_match:results['perenual']=perenual_match
  data=merge_provider_fields(results)
  data['scientific_name']=identity.scientific_name
  data['common_name']=identity.common_name
  if identity.family:data['family']=identity.family
  if identity.genus:data['genus']=identity.genus
  return EnrichmentResult(normalize_species_key(common_name),'matched',data,tuple(results),False)

def _identity_match(aliases:tuple[str,...],candidate:Mapping[str,Any])->bool:
 names={normalize_species_key(value) for value in aliases if value}
 candidate_names={normalize_species_key(str(candidate.get('scientific_name',''))),normalize_species_key(str(candidate.get('common_name','')))}
 candidate_names.update(normalize_species_key(str(value)) for value in candidate.get('synonyms',[]) if value)
 return bool(names & candidate_names)

def select_exact_common_name_candidate(query:str,candidates:list[dict[str,Any]])->dict[str,Any]|None:
 normalized=normalize_species_key(query)
 exact=[candidate for candidate in candidates if normalized in {normalize_species_key(str(candidate.get('scientific_name',''))),normalize_species_key(str(candidate.get('common_name',''))),normalize_species_key(str(candidate.get('matched_term','')))}]
 return exact[0] if len(exact)==1 else None

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
