# OmniZen AI Console

This repository has one application only:

- `frontend_main/` — the React/Vite frontend
- `backend_main/` — the FastAPI backend

All features are available through this single frontend: Workspace management,
Coaider, Static Code Analysis, Modularization, Test Case Generation,
Requirement Understanding, and Diff Kit. The Coaider tab uses the selected
workspace and files attached in the shared sidebar.

## Run the application

Start the backend:

```bash
cd backend_main
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8080
```

In another terminal, start the frontend:

```bash
cd frontend_main
npm install
npm run dev
```

The frontend runs on port 5174 and proxies `/api` requests to
`http://localhost:8080` by default. Set `VITE_API_TARGET` to use another
backend address.
