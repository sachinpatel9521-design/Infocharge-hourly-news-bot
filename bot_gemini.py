import os,json,re,time
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
import requests
from google import genai
from google.genai import types
from PIL import Image,ImageDraw,ImageFont

IST=ZoneInfo('Asia/Kolkata')
TOKEN=os.environ['TELEGRAM_BOT_TOKEN']; CHAT=os.environ['TELEGRAM_CHAT_ID']; KEY=os.environ['GEMINI_API_KEY']
KIND=os.getenv('INFOCHARGE_UPDATE_TYPE','hourly'); MEM=Path('infocharge_memory.json')
MODELS=['gemini-2.5-flash-lite','gemini-2.5-flash']
HOL={'2026-01-15','2026-01-26','2026-03-03','2026-03-26','2026-03-31','2026-04-03','2026-04-14','2026-05-01','2026-05-28','2026-06-26','2026-09-14','2026-10-02','2026-10-20','2026-11-10','2026-11-24','2026-12-25'}
MUH={'2026-11-08'}

def now(): return datetime.now(IST)
def session(t=None):
 t=t or now(); d=t.strftime('%Y-%m-%d')
 if d in MUH:return 'market_day'
 if t.weekday()>4 or d in HOL:return 'closed'
 m=t.hour*60+t.minute
 return 'pre_market' if m<555 else ('market_hours' if m<=930 else 'post_market')

def memory():
 try:return json.loads(MEM.read_text())
 except:return {'covered_stories':[],'covered_companies':[],'covered_themes':[],'recent_formats':[],'last_posts':[]}

def tg(method,data):
 r=requests.post(f'https://api.telegram.org/bot{TOKEN}/{method}',json=data,timeout=40); x=r.json()
 if not r.ok or not x.get('ok'): raise RuntimeError(f'Telegram {method}: {x}')
 return x

def research():
 t=now(); s=session(t); m=memory()
 if s=='market_hours': goal='Find ONE fresh, material Indian-market development worth posting now. Never create a routine hourly recap.'
 elif s=='pre_market': goal='Find the strongest fresh Indian developments relevant to today\'s open and choose ONE useful story.'
 elif s=='post_market': goal='Find what genuinely mattered in Indian markets today and choose ONE strong story.'
 else: goal='Only post if there is a genuinely material Indian corporate, regulatory or sector development; otherwise NO_POST.'
 prompt=f'''You are INFOCHARGE's senior Indian market research editor. Current India time: {t:%d %b %Y %I:%M %p IST}. Session: {s}. {goal}
Use LIVE GOOGLE SEARCH. Prioritize NSE/BSE companies, company filings, order wins, contracts, capex, acquisitions, fundraising, results, guidance, IPOs, SEBI/RBI, policy, sectors, FII/DII and India-relevant macro. Global news only when materially relevant to India. Prefer primary/strong sources and cross-check important numbers. No buy/sell calls, no invented facts, no generic filler, no repeated stories.
Previous memory: {json.dumps({k:m[k][-30:] for k in ['covered_stories','covered_companies','covered_themes','recent_formats']},ensure_ascii=False)}
Return ONLY JSON: {{"decision":"POST"|"NO_POST","headline":"","company":"","sector":"","importance":1-10,"what_happened":"","key_numbers":[],"why_it_matters":"","bigger_theme":"","what_to_watch":[],"risk_or_caveat":"","sources":[{{"title":"","url":""}}],"visual_brief":"","format_style":""}}. If nothing valuable, return {{"decision":"NO_POST"}}.'''
 c=genai.Client(api_key=KEY); last=None
 for model in MODELS:
  for attempt in range(2):
   try:
    r=c.models.generate_content(model=model,contents=prompt,config=types.GenerateContentConfig(temperature=.25,max_output_tokens=1800),tools=[types.Tool(google_search=types.GoogleSearch())])
    raw=re.sub(r'^```(?:json)?\s*|\s*```$','',(r.text or '').strip()); return json.loads(raw)
   except Exception as e:
    last=e; print('research',model,e); time.sleep(3*(attempt+1))
 raise RuntimeError(f'Research failed: {last}')

def write_post(x):
 p=f'''Write a premium INFOCHARGE Telegram post from this verified research. Sound like a sharp human Indian market editor, not AI/PR. Natural varied structure; do not force the same template. Explain WHAT happened, WHY IT MATTERS, bigger theme when justified, and WHAT TO WATCH. Use important numbers. No source URLs in the body, no buy/sell call, no exaggerated words, no article-copying. 1200-1800 chars. 3-6 natural emojis. End with: ⚠️ Educational information only. Not investment advice.\nRESEARCH:\n{json.dumps(x,ensure_ascii=False)}'''
 c=genai.Client(api_key=KEY)
 for model in MODELS:
  try:
   r=c.models.generate_content(model=model,contents=p,config=types.GenerateContentConfig(temperature=.65,max_output_tokens=1100))
   if r.text:return r.text.strip()
  except Exception as e: print('writer',model,e);time.sleep(2)
 raise RuntimeError('Writing failed')

def visual(x):
 img=Image.new('RGB',(1080,1080),(235,247,255)); d=ImageDraw.Draw(img)
 def F(n,b=False):
  p='/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf' if b else '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'; return ImageFont.truetype(p,n)
 d.rounded_rectangle((40,40,1040,1040),35,fill='white'); d.rectangle((40,40,1040,180),fill=(205,235,250))
 d.text((80,75),'INFOCHARGE',font=F(48,1),fill=(15,45,70))
 title=x.get('headline','Market Intelligence'); lines=[]
 for w in title.split():
  z=(lines[-1]+' '+w).strip() if lines else w
  if len(z)>24: lines.append(w)
  else:
   if lines:lines[-1]=z
   else:lines.append(z)
 y=230
 for line in lines[:3]:d.text((80,y),line,font=F(62,1),fill=(15,35,55));y+=75
 d.text((85,y+20),x.get('company','')[:42],font=F(40,1),fill=(20,95,125));y+=100
 for n in x.get('key_numbers',[])[:3]:
  d.text((90,y),'• '+str(n)[:52],font=F(30),fill=(35,50,65));y+=55
 d.rounded_rectangle((90,790,990,970),25,fill=(225,244,252));d.text((120,825),'WHY IT MATTERS',font=F(40,1),fill=(15,70,100))
 text=x.get('why_it_matters',''); d.text((120,885),text[:90],font=F(27),fill=(35,50,65))
 out=Path('infocharge_visual.jpg');img.save(out,quality=92);return out

def save_mem(x):
 m=memory()
 for k,v,lim in [('covered_stories',x.get('headline'),60),('covered_companies',x.get('company'),60),('covered_themes',x.get('bigger_theme'),50),('recent_formats',x.get('format_style'),15)]:
  if v and v not in m[k]:m[k].append(v)
  m[k]=m[k][-lim:]
 m['last_posts'].append({'date':now().isoformat(),'headline':x.get('headline',''),'company':x.get('company',''),'importance':x.get('importance',0)})
 m['last_posts']=m['last_posts'][-50:];MEM.write_text(json.dumps(m,ensure_ascii=False,indent=2))

def send(text,img):
 tg('getMe',{});tg('getChat',{'chat_id':CHAT})
 with img.open('rb') as f:
  r=requests.post(f'https://api.telegram.org/bot{TOKEN}/sendPhoto',data={'chat_id':CHAT,'caption':text[:1024]},files={'photo':f},timeout=60)
 if r.ok and r.json().get('ok'): print('visual post sent');return
 print('visual failed; sending text');tg('sendMessage',{'chat_id':CHAT,'text':text,'disable_web_page_preview':True})

def main():
 x=research();print(json.dumps(x,ensure_ascii=False))
 if x.get('decision')!='POST' or int(x.get('importance',0))<6: print('NO_POST');return
 post=write_post(x); img=visual(x);send(post,img);save_mem(x)
main()
