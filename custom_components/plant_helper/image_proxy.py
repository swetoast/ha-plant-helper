from __future__ import annotations
from typing import Any
from plant_helper_domain.image_proxy import SpeciesImageProxy

IMAGE_PATH='/api/plant_helper/image/{hash}'
class PlantHelperImageView:
 url='/api/plant_helper/image/{digest}'
 name='api:plant_helper:image'
 requires_auth=True
 def __init__(self,proxy:SpeciesImageProxy):self.proxy=proxy
 async def get(self,request:Any,digest:str):
  authenticated=bool(getattr(request,'user',None) and getattr(request.user,'is_authenticated',True))
  response=self.proxy.serve(digest,authenticated,request.headers.get('If-None-Match'))
  try:
   from aiohttp.web import Response
   return Response(status=response.status,headers=dict(response.headers),body=response.body)
  except ImportError:return response
