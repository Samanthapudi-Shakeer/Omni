"""
Convenience entry point: `python run.py` from the backend/ directory.

Running uvicorn this way (as a module import, not `python app/main.py`)
guarantees `app` is resolved as a proper package, so the relative imports
inside app/*.py (`from .config import settings`, etc.) work correctly.
"""
import uvicorn

from app.config import settings

if __name__ == "__main__":
    uvicorn.run("app.main:app", host="0.0.0.0", port=settings.port, reload=False)
