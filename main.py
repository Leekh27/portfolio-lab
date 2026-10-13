import os, json, re, sqlite3, time
from pathlib import Path
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from typing import List
from dotenv import load_dotenv
load_dotenv()
BASE=Path(__file__).resolve().parent
DB=Path(os.getenv('DATABASE_PATH',str(BASE/'portfolio.db')))
app=FastAPI(title='Portfolio Lab API', docs_url=None, redoc_url=None, openapi_url=None)
from cloud_security import require_login
app.middleware('http')(require_login)
class Holding(BaseModel):
    ticker:str=Field(pattern=r'^[A-Za-z0-9.^-]{1,15}$')
    qty:float=Field(gt=0)
    avg:float=Field(gt=0)
    price:float=Field(ge=0)
class Ask(BaseModel):
    ticker:str
    question:str=Field(max_length=3000)
def conn():
    url=os.getenv('DATABASE_URL','')
    if not url:
        raise HTTPException(503,'DATABASE_URL (Neon PostgreSQL) is not configured')
    import psycopg
    return psycopg.connect(url, connect_timeout=12)

def init_db(c):
    c.execute('CREATE TABLE IF NOT EXISTS holdings (ticker TEXT PRIMARY KEY, qty DOUBLE PRECISION NOT NULL, avg DOUBLE PRECISION NOT NULL, price DOUBLE PRECISION NOT NULL)')

@app.get('/')
def index():return FileResponse(BASE/'index.html')
@app.get('/api/health')
def health():return {'status':'ok'}
@app.get('/api/portfolio')
def portfolio():
    with conn() as c:
        init_db(c)
        return [dict(zip(('ticker','qty','avg','price'),r)) for r in c.execute('SELECT ticker,qty,avg,price FROM holdings ORDER BY ticker')]
@app.put('/api/portfolio')
def save(items:List[Holding]):
    if len(items)>100:raise HTTPException(400,'종목은 최대 100개입니다.')
    keys=[x.ticker.upper() for x in items]
    if len(set(keys))!=len(keys):raise HTTPException(400,'중복 티커가 있습니다.')
    with conn() as c:
        init_db(c)
        c.execute('DELETE FROM holdings')
        with c.cursor() as cur:
            cur.executemany('INSERT INTO holdings VALUES(%s,%s,%s,%s)',[(x.ticker.upper(),x.qty,x.avg,x.price) for x in items])
    return {'saved':len(items)}
_cache={}
@app.get('/api/backup')
def backup():
    from fastapi.responses import JSONResponse
    return JSONResponse({'format':'portfolio-lab-backup-v1','holdings':portfolio()},headers={'Content-Disposition':'attachment; filename=portfolio-backup.json'})

@app.get('/api/quotes')
def quotes(symbols:str=''):
    tickers=list(dict.fromkeys(x.strip().upper() for x in symbols.split(',') if x.strip()))
    if len(tickers)>30 or any(not re.fullmatch(r'[A-Z0-9.^-]{1,15}',t) for t in tickers):raise HTTPException(400,'티커 형식 또는 개수 오류')
    try:
        import yfinance as yf
        out={}
        for t in tickers:
            if t in _cache and time.time()-_cache[t][0]<120:out[t]=_cache[t][1];continue
            hist=yf.Ticker(t).history(period='5d')
            if not hist.empty:
                result={'price':round(float(hist['Close'].iloc[-1]),4),'currency':'USD (공급자 통화 확인 필요)','source':'Yahoo Finance (unofficial)','asof':str(hist.index[-1])}
                out[t]=result;_cache[t]=(time.time(),result)
        return out
    except Exception as e:raise HTTPException(503,'외부 시세 제공자 연결 실패: '+str(e)[:180])
def ai(prompt):
    key=os.getenv('OPENAI_API_KEY')
    if not key:raise HTTPException(503,'OPENAI_API_KEY가 설정되지 않았습니다. .env 파일에 입력하세요.')
    try:
        from openai import OpenAI
        r=OpenAI(api_key=key,timeout=45).responses.create(model=os.getenv('OPENAI_MODEL','gpt-4.1-mini'),instructions='한국어로 답하라. 금융 정보는 불확실성을 명확히 하고, 실시간 뉴스나 시세를 확인하지 않았다면 확인했다고 주장하지 마라. 투자 권유를 하지 마라.',input=prompt,max_output_tokens=1100)
        return r.output_text
    except Exception as e:raise HTTPException(502,'AI 서비스 오류: '+str(e)[:180])
@app.post('/api/analyze')
def analyze(req:Ask):
    holdings=portfolio()
    selected=next((x for x in holdings if x['ticker']==req.ticker.upper()),None)
    if not selected:raise HTTPException(404,'보유 종목을 찾을 수 없습니다.')
    return {'answer':ai('보유 종목 데이터: '+json.dumps(selected,ensure_ascii=False)+'\n질문: '+req.question+'\n외부 뉴스 조회는 하지 않았음. 데이터에 근거한 분석과 추가 확인 사항을 구분하라.')}
@app.post('/api/research')
def research():
    return {'answer':ai('다음 보유 포트폴리오를 집중도, 성과, ETF/레버리지 위험, 추가 조사 항목 중심으로 분석하라. 최신 시장 뉴스 조회는 하지 않았다.\n'+json.dumps(portfolio(),ensure_ascii=False))}
