from tools.base_tool import BaseTool
import requests


class GitHubTool(BaseTool):

    def execute(self, input_data):

        action = input_data.get("action")

        if action == "repo_info":

            return self.get_repo(
                input_data.get("owner"),
                input_data.get("repo")
            )

        return "Unsupported GitHub action"


    def get_repo(self, owner, repo):

        url = f"https://api.github.com/repos/{owner}/{repo}"

        response = requests.get(url)

        if response.status_code != 200:
            return "Repository not found"

        data = response.json()

        return {
            "name": data["name"],
            "stars": data["stargazers_count"],
            "forks": data["forks_count"],
            "language": data["language"]
        }