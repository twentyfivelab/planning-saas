from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .config import settings
from .routers import admin, auth, crud, exports, planning

app = FastAPI(title="Planning SaaS API", version="0.1.0",
              description="API multi-tenant de planification automatique (Europe/Zurich). "
                          "Aide à la décision : pas un conseil juridique.")
app.add_middleware(CORSMiddleware, allow_origins=[o for o in settings.cors_origins.split(",") if o],
                   allow_credentials=True, allow_methods=["*"], allow_headers=["*"])


@app.middleware("http")
async def security_headers(request: Request, call_next):
    resp = await call_next(request)
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["Referrer-Policy"] = "no-referrer"
    resp.headers["Cache-Control"] = "no-store"
    return resp


@app.exception_handler(Exception)
async def unhandled(request: Request, exc: Exception):  # pas de détails internes ni de données dans la réponse
    return JSONResponse({"detail": "Erreur interne"}, status_code=500)


@app.get("/health")
def health():
    return {"status": "ok"}


for r in [auth.router, admin.router, planning.router, exports.router, *crud.routers()]:
    app.include_router(r)
