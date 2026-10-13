"""Translate global discovery headlines for the Korean desk (unverified candidates)."""
import json
import re
import sys
import time
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

def translate(title):
    params=urlencode({"client":"gtx","sl":"en","tl":"ko","dt":"t","q":title})
    req=Request("https://translate.googleapis.com/translate_a/single?"+params,headers={"User-Agent":"Mozilla/5.0"})
    with urlopen(req,timeout=8) as response:
        data=json.load(response)
    result="".join(chunk[0] for chunk in data[0] if chunk and chunk[0])
    if not re.search("[가-힣]",result):
        raise ValueError("Translation returned no Korean")
    return result

def main(path):
    file=Path(path)
    data=json.loads(file.read_text(encoding="utf-8"))
    failures=0
    for item in data.get("items",[]):
        original=item.get("original_title") or item["title"]
        item["original_title"]=original
        try:
            item["title"]=translate(original)
        except Exception as exc:
            failures+=1
            item["title"]=original
            print(f"Translation unavailable: {type(exc).__name__}",file=sys.stderr)
        item["summary"]="해외 기사 제목을 자동 번역한 취재 후보입니다. 원문 내용과 핵심 사실은 검증되지 않았습니다."
        time.sleep(0.15)
    data["translation_status"]="partial" if failures else "complete"
    file.write_text(json.dumps(data,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(f"Korean headline translations: {len(data.get('items',[]))-failures}/{len(data.get('items',[]))}")

if __name__=="__main__":
    main(sys.argv[1])
