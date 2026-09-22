import asyncio,io,os
from datetime import datetime,timedelta,timezone
from pathlib import Path
import pytest
from PIL import Image
from domain.image_proxy import *
NOW=datetime(2026,1,1,tzinfo=timezone.utc)
def run(c):return asyncio.run(c)
def image(size=(1200,800),fmt='JPEG'):
 out=io.BytesIO();Image.new('RGB',size,(20,100,40)).save(out,fmt);return out.getvalue()
def response(body=None,url='https://images.example/plant.jpg',ctype='image/jpeg',status=200,headers=None):return DownloadResponse(status,headers or {'Content-Type':ctype},image() if body is None else body,url)
def public(host):return ('93.184.216.34',)
def test_https_only_dns_private_and_redirect_ssrf(tmp_path):
 fetch=lambda u:asyncio.sleep(0,result=response());p=SpeciesImageProxy(tmp_path,fetch,public)
 with pytest.raises(ImageProxyError):run(p.refresh('a','http://images.example/a.jpg',NOW))
 with pytest.raises(ImageProxyError):run(SpeciesImageProxy(tmp_path,fetch,lambda h:('127.0.0.1',)).refresh('a','https://images.example/a.jpg',NOW))
 async def redirect(u):return DownloadResponse(302,{'Location':'https://localhost/private'},b'',u)
 with pytest.raises(ImageProxyError):run(SpeciesImageProxy(tmp_path,redirect,lambda h:('127.0.0.1',) if h=='localhost' else public(h)).refresh('a','https://images.example/a.jpg',NOW))
def test_content_type_size_dimensions_and_decompression_limits(tmp_path):
 with pytest.raises(ImageProxyError,match='content_type'):transform_thumbnail(image(),'text/html')
 with pytest.raises(ImageProxyError,match='size'):transform_thumbnail(b'x'*(MAX_DOWNLOAD+1),'image/jpeg')
 with pytest.raises(ImageProxyError,match='dimensions'):transform_thumbnail(image((9000,1),'PNG'),'image/png')
 bomb=Image.MAX_IMAGE_PIXELS;Image.MAX_IMAGE_PIXELS=100
 try:
  with pytest.raises(ImageProxyError,match='image'):transform_thumbnail(image((20,20),'PNG'),'image/png')
 finally:Image.MAX_IMAGE_PIXELS=bomb
def test_static_thumbnail_content_addressed_cache_and_dedup(tmp_path):
 data=image();p=SpeciesImageProxy(tmp_path,lambda u:asyncio.sleep(0,result=response(data)),public);a=run(p.refresh('snake','https://images.example/a.jpg',NOW));b=run(p.refresh('other','https://images.example/b.jpg',NOW))
 assert a.digest==b.digest and a.width<=512 and a.height<=512 and len(list(tmp_path.glob('*.webp')))==1
 with Image.open(a.path) as im:assert im.format=='WEBP' and im.size==(512,341)
def test_auth_etag_and_cache_headers(tmp_path):
 p=SpeciesImageProxy(tmp_path,lambda u:asyncio.sleep(0,result=response()),public);item=run(p.refresh('a','https://images.example/a.jpg',NOW))
 assert p.serve(item.digest,False).status==401
 first=p.serve(item.digest,True);assert first.status==200 and first.headers['ETag']==f'"{item.digest}"' and 'immutable' in first.headers['Cache-Control']
 assert p.serve(item.digest,True,first.headers['ETag']).status==304 and p.serve('0'*64,True).status==404
def test_gc_preserves_referenced_and_removes_old_orphan(tmp_path):
 p=SpeciesImageProxy(tmp_path,lambda u:asyncio.sleep(0,result=response()),public);active=run(p.refresh('a','https://images.example/a.jpg',NOW));orphan='f'*64;op=tmp_path/f'{orphan}.webp';op.write_bytes(active.path.read_bytes());old=(NOW-timedelta(days=40)).timestamp();os.utime(op,(old,old))
 assert p.garbage_collect(NOW)==(orphan,) and active.path.exists()
def test_refresh_failure_preserves_stale_image(tmp_path):
 state={'fail':False}
 async def fetch(u):
  if state['fail']:raise TimeoutError
  return response()
 p=SpeciesImageProxy(tmp_path,fetch,public);old=run(p.refresh('a','https://images.example/a.jpg',NOW));state['fail']=True;kept=run(p.refresh('a','https://images.example/new.jpg',NOW+timedelta(days=1)));assert kept.digest==old.digest and old.path.exists()
def test_reported_size_and_redirect_limit(tmp_path):
 async def huge(u):return response(headers={'Content-Type':'image/jpeg','Content-Length':str(MAX_DOWNLOAD+1)})
 with pytest.raises(ImageProxyError,match='size'):run(SpeciesImageProxy(tmp_path,huge,public).refresh('a','https://images.example/a.jpg',NOW))
 async def loop(u):return DownloadResponse(302,{'Location':'/again'},b'',u)
 with pytest.raises(ImageProxyError,match='redirect_limit'):run(SpeciesImageProxy(tmp_path,loop,public).refresh('a','https://images.example/a.jpg',NOW,max_redirects=1))
