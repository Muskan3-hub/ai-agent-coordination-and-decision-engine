from agents.coordinator import CoordinatorAgent
from memory.memory import Memory
from memory.short_term_memory import ShortTermMemory
from models.llm import LLM
from tools.llm_guard import LLMGuard

model = LLM()
guard = LLMGuard()
memory = Memory()
short_memory = ShortTermMemory()

agent = CoordinatorAgent(model, guard, memory, short_memory)

print("Multi-AI-Agent Coding Assistant (type 'exit' to quit)")

while True:
    task = input("\nEnter your request: ")

    if task.lower() in ["exit", "quit"]:
        break

    result = agent.handle_task(task)
    memory.add_conversation(task, result["response"])

    print("\nAI Response:\n")
    print(result["response"])
