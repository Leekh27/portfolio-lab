import os, secrets
from fastapi import Request
from fastapi.responses import JSONResponse, Response

async def require_login(request: Request, call_next):
    if request.url.path == '/api/health':
        return await call_next(request)
    user = os.getenv('APP_USERNAME', '')
    password = os.getenv('APP_PASSWORD', '')
    if not user or not password:
        return JSONResponse({'detail':'APP_USERNAME and APP_PASSWORD must be configured'}, status_code=503)
    import base64
    auth = request.headers.get('authorization','')
    valid = False
    if auth.startswith('Basic '):
        try:
            raw = base64.b64decode(auth[6:], validate=True).decode('utf-8')
            supplied_user, supplied_password = raw.split(':', 1)
            valid = secrets.compare_digest(supplied_user, user) and secrets.compare_digest(supplied_password, password)
        except (ValueError, UnicodeError):
            pass
    if not valid:
        return Response(status_code=401, headers={'WWW-Authenticate':'Basic realm="Private Portfolio"', 'Cache-Control':'no-store'})
    response = await call_next(request)
    response.headers['Cache-Control'] = 'no-store'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['Referrer-Policy'] = 'no-referrer'
    return response
