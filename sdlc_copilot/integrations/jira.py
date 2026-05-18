import httpx

from sdlc_copilot.config import Settings


class JiraClient:
    def __init__(self, settings: Settings) -> None:
        if not settings.jira_base_url or not settings.jira_email or not settings.jira_api_token:
            raise ValueError("Jira integration requires JIRA_BASE_URL, JIRA_EMAIL, and JIRA_API_TOKEN.")
        self.base_url = settings.jira_base_url.rstrip("/")
        self.auth = (settings.jira_email, settings.jira_api_token)

    async def create_issue(self, project_key: str, summary: str, description: str, issue_type: str = "Task") -> dict:
        payload = {
            "fields": {
                "project": {"key": project_key},
                "summary": summary,
                "description": {
                    "type": "doc",
                    "version": 1,
                    "content": [{"type": "paragraph", "content": [{"type": "text", "text": description}]}],
                },
                "issuetype": {"name": issue_type},
            }
        }
        async with httpx.AsyncClient(auth=self.auth, timeout=30) as client:
            response = await client.post(f"{self.base_url}/rest/api/3/issue", json=payload)
            response.raise_for_status()
            return response.json()
