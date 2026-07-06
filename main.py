from memory.memory_manager import MemoryManager
from agents.coordinator import CoordinatorAgent
from models.model_manager import ModelManager
from tools.llm_guard import LLMGuard

model = ModelManager()
guard = LLMGuard()
memory=MemoryManager()

agent = CoordinatorAgent(model, guard,memory)

while True:
    task = input("\nEnter your request: ")

    if task.lower() in ["exit", "quit"]:
        break

    response = agent.handle_task(task)
    memory.add(task,response)

    print("\nAI Response:\n")
    print(response)