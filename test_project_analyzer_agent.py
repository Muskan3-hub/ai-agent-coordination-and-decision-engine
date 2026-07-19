from agents.project_analyzer_agent import ProjectAnalyzer
from models.llm import LLM
from tools.llm_guard import LLMGuard

llm = LLM()
guard = LLMGuard()

agent = ProjectAnalyzer(llm, guard)

result = agent.use_tool(
    "analyze project",
    {
        "root": "."
    }
)

print(result["structure"])