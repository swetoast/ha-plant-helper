from __future__ import annotations
import hashlib,io,ipaddress,socket
from dataclasses import dataclass
from datetime import datetime,timedelta,timezone
from pathlib import Path
from typing import Any,Awaitable,Callable,Iterable,Mapping
from urllib.parse import urljoin,urlsplit
from PIL import Image,ImageOps,UnidentifiedImageError

ALLOWED_FORMATS={'JPEG','PNG','WEBP'}
MAX_DOWNLOAD=5*1024*1024
MAX_PIXELS=20_000_000
MAX_DIMENSION=8192
THUMBNAIL_SIZE=(512,512)
CACHE_MAX_AGE=31536000
class ImageProxyError(RuntimeError):pass
@dataclass(frozen=True,slots=True)
class DownloadResponse:
 status:int;headers:Mapping[str,str];body:bytes;url:str
@dataclass(frozen=True,slots=True)
class CachedImage:
 digest:str;path:Path;content_type:str;width:int;height:int;created_at:datetime
@dataclass(frozen=True,slots=True)
class ImageResponse:
 status:int;headers:Mapping[str,str];body:bytes

def _public(address:str)->bool:
 try:ip=ipaddress.ip_address(address)
 except ValueError:return False
 return not (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved or ip.is_unspecified)
def validate_url(url:str,resolve:Callable[[str],Iterable[str]])->str:
 parsed=urlsplit(url)
 if parsed.scheme!='https' or not parsed.hostname or parsed.username or parsed.password:raise ImageProxyError('url')
 try:port=parsed.port
 except ValueError:raise ImageProxyError('url') from None
 if port not in (None,443):raise ImageProxyError('port')
 addresses=tuple(resolve(parsed.hostname))
 if not addresses or not all(_public(v) for v in addresses):raise ImageProxyError('ssrf')
 return url

def system_resolve(host:str)->tuple[str,...]:
 return tuple(sorted({item[4][0] for item in socket.getaddrinfo(host,443,type=socket.SOCK_STREAM)}))

def transform_thumbnail(body:bytes,content_type:str|None=None)->tuple[bytes,int,int]:
 # The HTTP Content-Type is advisory only. Image hosts (S3, iNaturalist open-data,
 # provider thumbnail CDNs) routinely serve real photos as application/octet-stream
 # or with no type at all, so gating on the header silently drops valid images. The
 # authoritative check is the decoded format below: the bytes are actually parsed,
 # which is both safer and compatible with mislabeled sources.
 if not body or len(body)>MAX_DOWNLOAD:raise ImageProxyError('size')
 try:
  with Image.open(io.BytesIO(body)) as image:
   if (image.format or '').upper() not in ALLOWED_FORMATS:raise ImageProxyError('image_format')
   width,height=image.size
   if width<1 or height<1 or width>MAX_DIMENSION or height>MAX_DIMENSION or width*height>MAX_PIXELS:raise ImageProxyError('dimensions')
   image.load()
   image=ImageOps.exif_transpose(image).convert('RGB')
   image.thumbnail(THUMBNAIL_SIZE,Image.Resampling.LANCZOS)
   output=io.BytesIO();image.save(output,'WEBP',quality=82,method=6)
   data=output.getvalue()
   if len(data)>MAX_DOWNLOAD:raise ImageProxyError('output_size')
   return data,image.width,image.height
 except ImageProxyError:raise
 except (UnidentifiedImageError,OSError,Image.DecompressionBombError) as err:raise ImageProxyError('image') from err

async def _run_inline(func:Callable[...,Any],*args:Any)->Any:return func(*args)

class SpeciesImageProxy:
 def __init__(self,cache_dir:Path,fetch:Callable[[str],Awaitable[DownloadResponse]],resolve:Callable[[str],Iterable[str]]=system_resolve,run_blocking:Callable[...,Awaitable[Any]]|None=None):
  # run_blocking executes DNS resolution, image decoding and file I/O off the
  # caller's event loop; inline by default so the pure module has no HA import.
  self.cache_dir=Path(cache_dir);self.cache_dir.mkdir(parents=True,exist_ok=True);self.fetch=fetch;self.resolve=resolve;self.run_blocking=run_blocking or _run_inline;self.index={};self.references={}
 def _store(self,body:bytes,ctype:str)->tuple[str,Path,int,int]:
  data,width,height=transform_thumbnail(body,ctype)
  digest=hashlib.sha256(data).hexdigest();path=self.cache_dir/f'{digest}.webp'
  if not path.exists():
   temp=path.with_suffix('.tmp');temp.write_bytes(data);temp.replace(path)
  return digest,path,width,height
 async def refresh(self,species_key:str,url:str,now:datetime|None=None,max_redirects:int=3)->CachedImage:
  now=now or datetime.now(timezone.utc);old_digest=self.references.get(species_key);current=await self.run_blocking(validate_url,url,self.resolve)
  try:
   for _ in range(max_redirects+1):
    response=await self.fetch(current)
    if response.status in {301,302,303,307,308}:
     location=response.headers.get('Location') or response.headers.get('location')
     if not location:raise ImageProxyError('redirect')
     current=await self.run_blocking(validate_url,urljoin(current,location),self.resolve);continue
    if response.status!=200:raise ImageProxyError(f'http_{response.status}')
    reported=response.headers.get('Content-Length') or response.headers.get('content-length')
    if reported is not None:
     try:length=int(reported)
     except ValueError:raise ImageProxyError('content_length') from None
     if length<0 or length>MAX_DOWNLOAD:raise ImageProxyError('size')
    ctype=response.headers.get('Content-Type') or response.headers.get('content-type','')
    digest,path,width,height=await self.run_blocking(self._store,response.body,ctype)
    item=CachedImage(digest,path,'image/webp',width,height,now);self.index[digest]=item;self.references[species_key]=digest;return item
   raise ImageProxyError('redirect_limit')
  except Exception:
   if old_digest and old_digest in self.index and await self.run_blocking(self.index[old_digest].path.exists):return self.index[old_digest]
   raise
 async def async_serve(self,digest:str,authenticated:bool,if_none_match:str|None=None)->ImageResponse:
  return await self.run_blocking(self.serve,digest,authenticated,if_none_match)
 def serve(self,digest:str,authenticated:bool,if_none_match:str|None=None)->ImageResponse:
  if not authenticated:return ImageResponse(401,{'Cache-Control':'no-store'},b'')
  item=self.index.get(digest);path=self.cache_dir/f'{digest}.webp'
  if item is None and path.exists():item=CachedImage(digest,path,'image/webp',0,0,datetime.fromtimestamp(path.stat().st_mtime,timezone.utc));self.index[digest]=item
  if item is None or not path.exists():return ImageResponse(404,{'Cache-Control':'no-store'},b'')
  etag=f'"{digest}"';headers={'Content-Type':'image/webp','ETag':etag,'Cache-Control':f'private, max-age={CACHE_MAX_AGE}, immutable','X-Content-Type-Options':'nosniff'}
  if if_none_match==etag:return ImageResponse(304,headers,b'')
  return ImageResponse(200,headers,path.read_bytes())
 def garbage_collect(self,now:datetime|None=None,max_age:timedelta=timedelta(days=30))->tuple[str,...]:
  now=now or datetime.now(timezone.utc);active=set(self.references.values());removed=[]
  for path in self.cache_dir.glob('*.webp'):
   digest=path.stem;item=self.index.get(digest);created=item.created_at if item else datetime.fromtimestamp(path.stat().st_mtime,timezone.utc)
   if digest not in active and now-created>max_age:path.unlink(missing_ok=True);self.index.pop(digest,None);removed.append(digest)
  return tuple(sorted(removed))
