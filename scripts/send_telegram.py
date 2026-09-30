import json, os, urllib.request
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
D=datetime.now(ZoneInfo('Asia/Seoul')).strftime('%Y-%m-%d')
p=Path('data')/f'{D}.json'
if not p.exists(): raise SystemExit(f'missing briefing: {p}')
d=json.loads(p.read_text())
parts=[f'제약바이오 브리핑 {D}']
for key,label in [('domestic','국내'),('global','글로벌'),('patent','특허')]:
    parts.append(f'\n[{label}]')
    parts += [f"• {x['title']}\n{x['source']}" for x in d.get(key,[])]
text='\n'.join(parts)
token=os.environ['TELEGRAM_BOT_TOKEN']; chat=os.environ['TELEGRAM_CHAT_ID']
req=urllib.request.Request(f'https://api.telegram.org/bot{token}/sendMessage',data=json.dumps({'chat_id':chat,'text':text,'disable_web_page_preview':True}).encode(),headers={'Content-Type':'application/json'})
with urllib.request.urlopen(req) as r:
    out=json.load(r)
    if not out.get('ok'): raise SystemExit(out)
print('telegram ok')
