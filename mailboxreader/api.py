import secrets
from contextlib import asynccontextmanager
from typing import Literal
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import Field
from psycopg.types.json import Jsonb
from .config import Settings
from .db import connect
from .domain import StrictModel
from .sync import Conflict, claim, commit_page
from .worker import run_one


class Page(StrictModel):
    lease: str = Field(pattern=r'^[0-9a-f-]{36}$')
    status: int = Field(ge=100,le=599)
    body: dict = Field(default_factory=dict)
    headers: dict = Field(default_factory=dict)


class Review(StrictModel):
    status: Literal['open','paid','dismissed']
    note: str = Field(min_length=5,max_length=2000)


def create_app(settings=None):
    settings = settings or Settings.from_env()
    @asynccontextmanager
    async def lifespan(app):
        with connect(settings) as db:
            db.execute('''INSERT INTO monitor_settings(mailbox_id,threshold,currency) VALUES(%s,%s,%s)
                ON CONFLICT(mailbox_id) DO UPDATE SET threshold=EXCLUDED.threshold,currency=EXCLUDED.currency''',
                (settings.mailbox_id,settings.high_value_amount,settings.high_value_currency))
        yield

    app = FastAPI(title='Mailbox Reader',lifespan=lifespan,docs_url=None,redoc_url=None,openapi_url=None)
    auth = HTTPBearer(auto_error=False)
    def authorize(credentials: HTTPAuthorizationCredentials | None = Depends(auth)):
        if not credentials or not secrets.compare_digest(credentials.credentials,settings.api_token):
            raise HTTPException(401,'Unauthorized')

    @app.middleware('http')
    async def security(request: Request, call_next):
        # Enforce actual streamed length, not just the untrusted Content-Length header.
        size = 0
        chunks = []
        async for chunk in request.stream():
            size += len(chunk)
            if size > 20_000_000:
                return JSONResponse({'detail':'Request too large'},status_code=413)
            chunks.append(chunk)
        request._body = b''.join(chunks)
        response = await call_next(request)
        response.headers['Cache-Control'] = 'no-store'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        return response

    @app.exception_handler(ValueError)
    async def bad_value(request, error):
        return JSONResponse({'detail':'Invalid input; checkpoint unchanged'},status_code=422)

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request, error):
        # FastAPI's default validation response echoes untrusted inputs.
        return JSONResponse({'detail':'Invalid request'},status_code=422)

    @app.exception_handler(Conflict)
    async def conflict(request, error):
        return JSONResponse({'detail':'Stale lease; claim a new page'},status_code=409)

    @app.get('/health')
    def health():
        with connect(settings) as db:
            db.execute('SELECT 1 FROM monitor_settings LIMIT 1')
        return {'status':'ok'}

    @app.post('/sync/{stream}/claim',dependencies=[Depends(authorize)])
    def next_page(stream: Literal['live','history']):
        return claim(settings,stream)

    @app.post('/sync/{stream}/page',dependencies=[Depends(authorize)])
    def page(stream: Literal['live','history'], data: Page):
        return commit_page(settings,stream,data.lease,data.status,data.body,data.headers)

    @app.post('/extract',dependencies=[Depends(authorize)])
    def extraction():
        return run_one(settings)

    @app.get('/monitor',dependencies=[Depends(authorize)])
    def monitor():
        with connect(settings) as db:
            findings = db.execute('SELECT * FROM possible_overdue WHERE mailbox_id=%s ORDER BY amount DESC LIMIT 1000', (settings.mailbox_id,)).fetchall()
        return {'assessment':'Possible overdue; human review required','findings':findings}

    @app.get('/evidence/{fact_id}',dependencies=[Depends(authorize)])
    def evidence(fact_id: int):
        with connect(settings) as db:
            row = db.execute('SELECT * FROM source_evidence WHERE fact_id=%s AND mailbox_id=%s', (fact_id,settings.mailbox_id)).fetchone()
        if not row:
            raise HTTPException(404,'Not found')
        return row

    @app.post('/review/{key}',dependencies=[Depends(authorize)])
    def review(key: str,data: Review):
        with connect(settings) as db:
            if not db.execute('SELECT 1 FROM transaction_candidates WHERE transaction_key=%s AND mailbox_id=%s', (key,settings.mailbox_id)).fetchone():
                raise HTTPException(404,'Not found')
            db.execute('''INSERT INTO reviews(transaction_key,status,note) VALUES(%s,%s,%s)
                ON CONFLICT(transaction_key) DO UPDATE SET status=EXCLUDED.status,note=EXCLUDED.note,updated_at=now()''', (key,data.status,data.note))
            db.execute('INSERT INTO audit_log(event,details) VALUES(%s,%s)', ('human_review',Jsonb({'transaction_key':key,'status':data.status})))
        return {'saved':True}

    return app
