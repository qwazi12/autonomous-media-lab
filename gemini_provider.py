"""Gemini JSON adapter. No calls without explicit runtime authorization.

Reads a key from an environment variable; never stores keys in artifacts or errors.
Request quota bounds requests, not dollars. Spending approval is external to code.
"""
import base64,json,os,re,urllib.request,urllib.error
from pathlib import Path

class GeminiError(ValueError):pass
class NoRedirect(urllib.request.HTTPRedirectHandler):
 def redirect_request(self,*args,**kwargs):raise GeminiError('Provider redirects are disabled')

class GeminiModel:
 provider='gemini'
 def __init__(self,model,key_env='GEMINI_API_KEY',*,authorized=False,max_calls=0,quota=None):
  if not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9._-]{0,99}',model or ''):raise GeminiError('Invalid Gemini model name')
  if not re.fullmatch(r'[A-Z_][A-Z0-9_]{0,99}',key_env):raise GeminiError('Use an environment variable name, never a key value')
  if authorized is not True or type(max_calls) is not int or not 1<=max_calls<=1000:raise GeminiError('Gemini is disabled without explicit spending/data authorization and a request limit')
  self.model=model;self.key_env=key_env;self.max_calls=max_calls;self.calls=0;self.usage=[];self.quota=quota if quota is not None else {'used':0}
 def generate(self,prompt,images=None):
  if not isinstance(prompt,str) or len(prompt)>60000:raise GeminiError('Prompt exceeds bounded context')
  if self.quota['used']>=self.max_calls:raise GeminiError('Approved request limit reached; no request sent')
  key=os.environ.get(self.key_env)
  if not key:raise GeminiError('Configured Gemini key environment variable is missing')
  parts=[{'text':prompt}]
  if len(images or [])>5:raise GeminiError('At most five sampled images per request')
  total=0
  for path in images or []:
   p=Path(path);raw=p.read_bytes();total+=len(raw)
   if total>15*1024*1024:raise GeminiError('Image payload exceeds 15 MiB limit')
   if raw.startswith(b'\xff\xd8\xff'):mime='image/jpeg'
   elif raw.startswith(b'\x89PNG\r\n\x1a\n'):mime='image/png'
   else:raise GeminiError('Only PNG/JPEG image bytes are supported')
   parts.append({'inlineData':{'mimeType':mime,'data':base64.b64encode(raw).decode()}})
  payload={'contents':[{'role':'user','parts':parts}],'generationConfig':{'temperature':0.2,'responseMimeType':'application/json','maxOutputTokens':8192}}
  req=urllib.request.Request('https://generativelanguage.googleapis.com/v1beta/models/'+self.model+':generateContent',json.dumps(payload).encode(),{'Content-Type':'application/json','x-goog-api-key':key},method='POST')
  # Count before transport: timeout may have consumed a paid request. Never retry.
  self.calls+=1;self.quota['used']+=1
  try:
   opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect())
   with opener.open(req,timeout=600) as response:
    raw=response.read(20*1024*1024+1)
   if len(raw)>20*1024*1024:raise GeminiError('Provider response too large')
   result=json.loads(raw)
  except Exception:
   raise GeminiError('Gemini request failed or outcome uncertain; no automatic retry. Provider response and credentials omitted.') from None
  candidates=result.get('candidates',[])
  if not candidates or candidates[0].get('finishReason')!='STOP':raise GeminiError('Gemini did not return a complete response; review safety, output limit or model availability')
  try:
   text=''.join(p.get('text','') for p in candidates[0]['content']['parts'] if not p.get('thought'))
   output=json.loads(text)
  except (ValueError,KeyError,TypeError):raise GeminiError('Gemini returned invalid JSON content') from None
  if not isinstance(output,dict):raise GeminiError('Gemini response must be a JSON object')
  usage=result.get('usageMetadata',{})
  self.usage.append({k:v for k,v in usage.items() if k in ('promptTokenCount','candidatesTokenCount','totalTokenCount','thoughtsTokenCount') and type(v) is int})
  return output
