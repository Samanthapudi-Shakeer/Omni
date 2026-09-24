from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routers import workspace, analysis, modularize, jobs, testgen, translate, pty

app = FastAPI(title="Aider Console API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173", "http://127.0.0.1:5173",
        "http://localhost:5174", "http://127.0.0.1:5174",
    ],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(workspace.router)
app.include_router(analysis.router)
app.include_router(modularize.router)
app.include_router(jobs.router)
app.include_router(testgen.router)
app.include_router(translate.router)
app.include_router(pty.router)


@app.get("/api/health")
async def health():
    return {"status": "ok"}
