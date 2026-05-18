import httpx

from sdlc_copilot.config import Settings


class GitHubClient:
    def __init__(self, settings: Settings) -> None:
        if not settings.github_token:
            raise ValueError("GitHub integration requires GITHUB_TOKEN.")
        self.headers = {
            "Authorization": f"Bearer {settings.github_token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    async def create_issue(self, owner: str, repo: str, title: str, body: str) -> dict:
        async with httpx.AsyncClient(headers=self.headers, timeout=30) as client:
            response = await client.post(
                f"https://api.github.com/repos/{owner}/{repo}/issues",
                json={"title": title, "body": body},
            )
            response.raise_for_status()
            return response.json()
