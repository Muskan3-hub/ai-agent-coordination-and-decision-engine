# 🤖 Multi-AI-Agent Coding Assistant

## 📌 Project Overview

The **Multi-AI-Agent Coding Assistant** is a Streamlit-based intelligent coding assistant that uses multiple specialized AI agents coordinated by a central decision engine. Instead of relying on a single AI model for every task, the system routes user requests to dedicated agents such as Coding, Debugging, Documentation, and Planning agents. It also integrates several tools for file management, project analysis, and code execution.

---

## ✨ Features

* 💻 Code Generation
* 🐞 Code Debugging
* 📖 Documentation & Code Explanation
* 📝 Planning Agent for coding tasks
* 📂 File Creation, Reading, Updating, and Deletion
* ▶️ Python Code Execution
* 📊 Project Analysis
* 💬 ChatGPT-style Streamlit Interface
* 📁 File Upload Support
* 📥 Download Generated Responses
* ⏱ Execution Time Display

---

## 🏗️ Architecture

User

↓

Streamlit Chat Interface

↓

Coordinator Agent

↓

Coding Agent | Debugging Agent | Documentation Agent | Planner Agent

↓

Tools Layer

* File Tool
* Project Analyzer
* Code Executor
* Patch Tool

---

## 📂 Project Structure

```text
Multi-AI-Agent-Coding-Assistant/
│
├── agents/
├── memory/
├── models/
├── tools/
├── app.py
├── requirements.txt
├── README.md
└── .env
```

---

## ⚙️ Installation

1. Clone the repository.

2. Create a virtual environment.

3. Install dependencies:

```bash
pip install -r requirements.txt
```

4. Add your API key to the `.env` file.

Example:

```text
GROQ_API_KEY=your_api_key_here
```

5. Run the application:

```bash
streamlit run app.py
```

---

## 💬 Example Prompts

* Write a Python calculator program.
* Debug this code: `print("Hello"`
* Explain Python decorators.
* Create file `hello.py`.
* Read file `hello.py`.
* Update file `hello.py` to print Welcome.
* Analyze project.
* Run this Python code.

---

## 🛠️ Technologies Used

* Python
* Streamlit
* Groq API
* Large Language Models (LLMs)



---

## 🔮 Future Enhancements

* Support for additional programming languages
* Conversation export
* Authentication
* Voice input
* GitHub integration
* Docker deployment

---

## 👨‍💻 Author

Developed as a Multi-Agent AI Coding Assistant project using Streamlit, Groq API, and Python.
