from dotenv import load_dotenv
import os

from langchain_groq import ChatGroq

load_dotenv()


class LLM:

    def __init__(self):

        self.llm = ChatGroq(
            model="llama-3.3-70b-versatile",
            api_key=os.getenv("GROQ_API_KEY"),
            temperature=0.3,
        )

    def ask(self, prompt):

        # If prompt is a normal string
        if isinstance(prompt, str):
            response = self.llm.invoke(prompt)

        # If prompt is already formatted LangChain messages
        else:
            response = self.llm.invoke(prompt)

        return response.content