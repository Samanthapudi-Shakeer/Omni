import httpx


async def get_ollama_models(base_url: str, timeout: float = 3.0) -> dict:
    url = base_url.rstrip("/") + "/api/tags"
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            res = await client.get(url)
            res.raise_for_status()
            data = res.json()
            models = [m.get("name") for m in data.get("models", []) if m.get("name")]
            return {"connected": True, "models": models}
    except Exception as exc:
        return {"connected": False, "models": [], "error": str(exc)}


async def generate_direct(base_url: str, model: str, prompt: str, timeout: float = 180.0) -> dict:
    """Calls Ollama's /api/generate directly over HTTP -- no Aider, no PTY,
    no chat history, no file editing/commits. Used for the Test Case
    Generation feature, which is deliberately kept separate from Aider: it
    just asks the model to produce text and hands that text back for the
    user to review and optionally save themselves."""
    # Ollama model names in this app are stored Aider-style (e.g.
    # "ollama/qwen2.5-coder:32b"); Ollama's own API wants just the bare name.
    bare_model = model.split("/", 1)[1] if model.startswith("ollama/") else model
    url = base_url.rstrip("/") + "/api/generate"
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            res = await client.post(url, json={"model": bare_model, "prompt": prompt, "stream": False})
            res.raise_for_status()
            data = res.json()
            return {"ok": True, "text": data.get("response", ""), "model": bare_model}
    except Exception as exc:
        return {"ok": False, "text": "", "error": str(exc), "model": bare_model}
