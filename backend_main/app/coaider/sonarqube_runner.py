"""SonarQube issue lookup for an organization-hosted SonarQube server."""
import httpx

async def run_sonarqube(url: str, token: str, project: str, timeout: int = 30) -> dict:
    if not url or not token or not project:
        return {"findings": [], "raw": "", "error": "SonarQube URL, token, and project key are required."}
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.get(url.rstrip('/') + '/api/issues/search', params={'componentKeys': project, 'ps': 500}, auth=(token, ''))
            response.raise_for_status(); payload = response.json()
    except Exception as exc:
        return {"findings": [], "raw": "", "error": f"SonarQube request failed: {exc}"}
    findings = [{"path": issue.get('component', '').split(':', 1)[-1], "line": issue.get('line') or 1,
                 "column": issue.get('textRange', {}).get('startOffset', 0) + 1, "type": issue.get('severity', 'warning').lower(),
                 "symbol": issue.get('rule', 'sonarqube'), "message": issue.get('message', ''), "messageId": issue.get('rule')}
                for issue in payload.get('issues', [])]
    return {"findings": findings, "raw": "", "error": None}
