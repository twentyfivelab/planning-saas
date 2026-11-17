from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .config import settings
from . import realtime  # noqa: F401  (publication temps réel après chaque transaction)
from .routers import admin, auth, catalog, clients, crud, decisions, employee_month, employee_tools, employees, events, exports, legal, periods_setup, manual_shifts, months, planning, reports, requests, time_tracking, weights_settings, workflow

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


@app.exception_handler(Exception)
async def unhandled(request: Request, exc: Exception):  # pas de détails internes ni de données dans la réponse
    return JSONResponse({"detail": "Erreur interne"}, status_code=500)


@app.get("/health")
def health():
    return {"status": "ok"}


for r in [auth.router, admin.router, employees.router, employee_month.router, requests.router, planning.router, workflow.router, decisions.router, clients.router, time_tracking.router, reports.router, legal.router, employee_tools.router, manual_shifts.router,
          months.router, weights_settings.router, events.router, periods_setup.router, catalog.router, exports.router, *crud.routers()]:
    app.include_router(r)
