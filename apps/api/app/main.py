from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .config import settings
from . import realtime  # noqa: F401  (publication temps réel après chaque transaction)
from .routers import admin, auth, catalog, clients, crud, decisions, employee_month, employee_tools, employees, events, exports, legal, periods_setup, period_deletion, history_view, integrations, manual_shifts, optional_needs, replacement_offers, run_summary, months, planning, reports, requests, time_tracking, weights_settings, workflow

app = FastAPI(title="Planning SaaS API", version="0.1.0",
              description="API multi-tenant de planification automatique (Europe/Zurich). "
                          "Aide à la décision : pas un conseil juridique.")
app.add_middleware(CORSMiddleware, allow_origins=[o for o in settings.cors_origins.split(",") if o],
                   allow_credentials=True, allow_methods=["*"], allow_headers=["*"])


_SECURITY_HEADERS = [(b"x-content-type-options", b"nosniff"), (b"x-frame-options", b"DENY"), (b"referrer-policy", b"no-referrer"),
                     (b"cache-control", b"no-store")]


class SecurityHeaders:
    """Middleware ASGI pur : n'intercepte pas le corps des réponses, donc les flux temps réel (/events) détectent bien la
    déconnexion du client et ne restent jamais ouverts (contrairement à un middleware « http » qui met la réponse en tampon)."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        async def send_with_headers(message):
            if message["type"] == "http.response.start":
                names = {k for k, _ in _SECURITY_HEADERS}
                headers = [h for h in message.get("headers", []) if h[0].lower() not in names]
                message = {**message, "headers": headers + _SECURITY_HEADERS}
            await send(message)

        await self.app(scope, receive, send_with_headers)


app.add_middleware(SecurityHeaders)


class InflightLimit:
    """Requêtes en cours limitées par processus, AVANT tout thread et toute connexion à la base (mesure à plusieurs managers du 20/11/2026).
    Sans cette limite, sous forte affluence, les connexions étaient prises par des requêtes en attente d'un thread pendant que tous les
    threads attendaient une connexion : plus rien n'avançait pendant 30 s, puis erreur 500 (« QueuePool limit reached »), processeur au
    repos. Les requêtes au-delà de la limite attendent leur tour sans rien bloquer ; temps d'attente publié (Server-Timing « queue »).
    Le flux temps réel (/events, connexion longue sans base de données) et /health ne sont pas comptés."""

    def __init__(self, app):
        import asyncio
        self.app = app
        self.sem = asyncio.Semaphore(settings.max_inflight_requests)

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope.get("path") in ("/events", "/health"):
            return await self.app(scope, receive, send)
        import asyncio
        import time
        t0 = time.perf_counter()
        try:
            await asyncio.wait_for(self.sem.acquire(), timeout=settings.inflight_wait_s)
        except asyncio.TimeoutError:
            body = b'{"detail":"Serveur momentan\xc3\xa9ment satur\xc3\xa9 : r\xc3\xa9essayez dans quelques secondes. Rien n\'a \xc3\xa9t\xc3\xa9 modifi\xc3\xa9."}'
            await send({"type": "http.response.start", "status": 503, "headers": [(b"content-type", b"application/json"), (b"retry-after", b"2")]})
            await send({"type": "http.response.body", "body": body})
            return
        wait_ms = (time.perf_counter() - t0) * 1000

        async def tagged(message):
            if message["type"] == "http.response.start":
                message = {**message, "headers": [*message.get("headers", []), (b"server-timing", f"queue;dur={wait_ms:.0f}".encode())]}
            await send(message)
        try:
            await self.app(scope, receive, tagged)
        finally:
            self.sem.release()


app.add_middleware(InflightLimit)


class RequestTiming:
    """Diagnostic des lenteurs : en-tête « Server-Timing: app;dur=… » (durée de traitement côté serveur, lisible par le navigateur et les
    tests) et journal des requêtes au-delà de SLOW_REQUEST_MS (méthode, modèle de route, durée ; jamais de données ni d'identifiants)."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope.get("path") == "/events":
            return await self.app(scope, receive, send)
        import time
        t0 = time.perf_counter()

        async def timed(message):
            if message["type"] == "http.response.start":
                ms = (time.perf_counter() - t0) * 1000
                message = {**message, "headers": [*message.get("headers", []), (b"server-timing", f"app;dur={ms:.0f}".encode())]}
                if ms >= settings.slow_request_ms:
                    route = getattr(scope.get("route"), "path", "?")
                    _slow.warning("requête lente : %s %s %.0f ms", scope.get("method"), route, ms)
            await send(message)

        await self.app(scope, receive, timed)


import logging  # noqa: E402

_slow = logging.getLogger("app.slow")
if not _slow.handlers:  # visible dans les journaux du conteneur, même sans configuration de journalisation globale
    _h = logging.StreamHandler()
    _h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    _slow.addHandler(_h)
    _slow.setLevel(logging.WARNING)
    _slow.propagate = False
app.add_middleware(RequestTiming)


@app.exception_handler(Exception)
async def unhandled(request: Request, exc: Exception):  # pas de détails internes ni de données dans la réponse
    return JSONResponse({"detail": "Erreur interne"}, status_code=500)


@app.get("/health")
def health():
    return {"status": "ok"}


for r in [auth.router, admin.router, employees.router, employee_month.router, requests.router, history_view.router, period_deletion.router, integrations.router, optional_needs.router, replacement_offers.router, run_summary.router, planning.router, workflow.router, decisions.router, clients.router, time_tracking.router, reports.router, legal.router, employee_tools.router, manual_shifts.router,
          months.router, weights_settings.router, events.router, periods_setup.router, catalog.router, exports.router, *crud.routers()]:
    app.include_router(r)
