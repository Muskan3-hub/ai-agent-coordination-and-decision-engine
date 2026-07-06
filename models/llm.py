from groq import Groq
from dotenv import load_dotenv
import os

load_dotenv()

client = Groq(
    api_key=os.getenv("GROQ_API_KEY")
)


class LLM:

    def ask(self, prompt):

        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",   # or your preferred Groq model
            messages=[
                {
                    "role": "user",
                    "content": prompt
                }
            ],
            temperature=0.3
        )

        return response.choices[0].message.content