import json, os, urllib.request
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo

def api(token, method, payload=None):
    data=None if payload is None else json.dumps(payload).encode()
    req=urllib.request.Request(f'https://api.telegram.org/bot{token}/{method}',data=data,headers={'Content-Type':'application/json'} if data else {})
    with urllib.request.urlopen(req,timeout=20) as r: out=json.load(r)
    if not out.get('ok'): raise SystemExit(out)
    return out['result']

def discover_chat(token):
    for u in reversed(api(token,'getUpdates')):
        m=u.get('message') or u.get('channel_post')
        if m and m.get('chat',{}).get('id'): return str(m['chat']['id'])
    raise SystemExit('No Telegram chat found. Open @daily_pharm_bot and send /start once.')

D=datetime.now(ZoneInfo('Asia/Seoul')).strftime('%Y-%m-%d')
p=Path('data')/f'{D}.json'
if not p.exists(): raise SystemExit(f'missing briefing: {p}')
d=json.loads(p.read_text())
token=os.environ['TELEGRAM_BOT_TOKEN']
chat=os.environ.get('TELEGRAM_CHAT_ID') or discover_chat(token)
parts=[f'제약바이오 브리핑 {D}']
for key,label in [('domestic','국내'),('global','글로벌'),('patent','특허')]:
    parts.append(f'\n[{label}]')
    parts += [f"• {x['title']}\n{x['source']}" for x in d.get(key,[])]
api(token,'sendMessage',{'chat_id':chat,'text':'\n'.join(parts),'disable_web_page_preview':True})
print('telegram ok')
