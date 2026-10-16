import os, json, re, sqlite3, time
from pathlib import Path
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from typing import List, Literal
from datetime import date
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
        init_trades(c)
        tracked={r[0] for r in c.execute('SELECT DISTINCT ticker FROM trades')}
        old={r[0]:(float(r[1]),float(r[2])) for r in c.execute('SELECT ticker,qty,avg FROM holdings')}
        new={x.ticker.upper():(x.qty,x.avg) for x in items}
        for ticker in tracked:
            a=old.get(ticker); b=new.get(ticker)
            if (a is None)!=(b is None) or (a and (abs(a[0]-b[0])>1e-7 or abs(a[1]-b[1])>1e-7)):
                raise HTTPException(409, '거래내역이 있는 종목은 거래 등록으로 수량/매수가를 변경하세요: '+ticker)
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
                result={'price':round(float(hist['Close'].iloc[-1]),4),'currency':('KRW' if t.endswith(('.KS','.KQ')) else 'USD'),'source':'Yahoo Finance (unofficial)','asof':str(hist.index[-1])}
                out[t]=result;_cache[t]=(time.time(),result)
        return out
    except Exception as e:raise HTTPException(503,'외부 시세 제공자 연결 실패: '+str(e)[:180])


# Search suggestions are an explicitly limited local dictionary, not a complete KRX listing.
KR_NAMES = {
  '태광':'023160.KQ','우진':'105840.KS','세진중공업':'075580.KS',
  'TIGER 미국우주테크':'0183J0.KS','RISE 글로벌AI낸드메모리반도체':'0233N0.KS',
  '셀라스 라이프 사이언스 그룹':'SLS','SELLAS Life Sciences Group':'SLS',
 '삼성전자':'005930.KS','삼성전자우':'005935.KS','SK하이닉스':'000660.KS',
 '현대차':'005380.KS','기아':'000270.KS','NAVER':'035420.KS',
 '카카오':'035720.KS','LG에너지솔루션':'373220.KS','셀트리온':'068270.KS',
 '삼성바이오로직스':'207940.KS','POSCO홀딩스':'005490.KS',
 'KODEX 미국S&P500':'379800.KS','TIGER 미국S&P500':'360750.KS',
 '에코프로비엠':'247540.KQ','에코프로':'086520.KQ',
 'QQQ':'QQQ','QLD':'QLD','SPY':'SPY','VOO':'VOO','AAPL':'AAPL',
 'MSFT':'MSFT','NVDA':'NVDA','TSLA':'TSLA'
}
@app.get('/api/symbol-search')
def symbol_search(q:str=''):
    q=q.strip().casefold()
    if not q or len(q)>60:return []
    matches=[{'name':name,'ticker':ticker,'currency':'KRW' if ticker.endswith(('.KS','.KQ')) else 'USD'}
             for name,ticker in KR_NAMES.items() if q in name.casefold() or q in ticker.casefold()]
    return matches[:12]

class Trade(BaseModel):
    ticker:str=Field(pattern=r'^[A-Za-z0-9.^-]{1,15}$')
    side:Literal['BUY','SELL']
    qty:float=Field(gt=0)
    price:float=Field(gt=0)
    fee:float=Field(default=0,ge=0)
    traded_on:date

def init_trades(c):
    c.execute('''CREATE TABLE IF NOT EXISTS trades (
      id BIGSERIAL PRIMARY KEY, ticker TEXT NOT NULL, side TEXT NOT NULL,
      qty DOUBLE PRECISION NOT NULL, price DOUBLE PRECISION NOT NULL,
      fee DOUBLE PRECISION NOT NULL DEFAULT 0, traded_on DATE NOT NULL,
      is_opening BOOLEAN NOT NULL DEFAULT FALSE,
      realized_pnl DOUBLE PRECISION NOT NULL DEFAULT 0,
      created_at TIMESTAMPTZ NOT NULL DEFAULT NOW())''')

def seed_opening(c):
    # Preserve every existing holding as an opening position once, without inventing historical trades.
    if c.execute('SELECT 1 FROM trades LIMIT 1').fetchone():return
    for t,q,a in c.execute('SELECT ticker,qty,avg FROM holdings').fetchall():
        c.execute('INSERT INTO trades(ticker,side,qty,price,traded_on,is_opening) VALUES(%s,%s,%s,%s,%s,TRUE)',
                  (t,'BUY',q,a,date.today()))

@app.get('/api/trades')
def get_trades():
    with conn() as c:
        init_db(c);init_trades(c)
        rows=c.execute('SELECT id,ticker,side,qty,price,fee,traded_on,is_opening,realized_pnl FROM trades ORDER BY id DESC LIMIT 500').fetchall()
        return [dict(zip(('id','ticker','side','qty','price','fee','traded_on','is_opening','realized_pnl'),r)) for r in rows]

@app.post('/api/trades')
def create_trade(trade:Trade):
    ticker=trade.ticker.upper()
    with conn() as c:
        c.execute('SELECT pg_advisory_xact_lock(8540391)')
        init_db(c);init_trades(c);seed_opening(c)
        row=c.execute('SELECT qty,avg,price FROM holdings WHERE ticker=%s FOR UPDATE',(ticker,)).fetchone()
        old_qty=float(row[0]) if row else 0.0
        old_avg=float(row[1]) if row else 0.0
        current=float(row[2]) if row else 0.0
        realized=0.0
        if trade.side=='BUY':
            new_qty=old_qty+trade.qty
            new_avg=(old_qty*old_avg+trade.qty*trade.price+trade.fee)/new_qty
        else:
            if trade.qty>old_qty+1e-8:raise HTTPException(400,'보유 수량보다 많이 매도할 수 없습니다.')
            new_qty=max(0,old_qty-trade.qty)
            new_avg=old_avg
            realized=(trade.price-old_avg)*trade.qty-trade.fee
        if new_qty<1e-8:
            c.execute('DELETE FROM holdings WHERE ticker=%s',(ticker,))
        else:
            c.execute('''INSERT INTO holdings(ticker,qty,avg,price) VALUES(%s,%s,%s,%s)
                ON CONFLICT(ticker) DO UPDATE SET qty=EXCLUDED.qty,avg=EXCLUDED.avg,price=EXCLUDED.price''',
                (ticker,new_qty,new_avg,current))
        c.execute('''INSERT INTO trades(ticker,side,qty,price,fee,traded_on,realized_pnl)
                     VALUES(%s,%s,%s,%s,%s,%s,%s)''',
                  (ticker,trade.side,trade.qty,trade.price,trade.fee,trade.traded_on,realized))
        return {'ok':True,'ticker':ticker,'qty':new_qty,'avg':new_avg,'realized_pnl':realized,
                'currency':'KRW' if ticker.endswith(('.KS','.KQ')) else 'USD'}

@app.get('/api/fx')
def fx():
    try:
        import yfinance as yf
        h=yf.Ticker('KRW=X').history(period='5d')
        if h.empty: raise ValueError('환율 데이터 없음')
        return {'usdkrw':round(float(h['Close'].iloc[-1]),4),'asof':str(h.index[-1]),'source':'Yahoo Finance (unofficial)'}
    except Exception:
        raise HTTPException(503,'USD/KRW 환율 조회 실패')

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
