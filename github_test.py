from tools.github_tool import GitHubTool


tool = GitHubTool()


result = tool.execute({
    "action":"repo_info",
    "owner":"openai",
    "repo":"openai-python"
})


print(result)