
# 🤖 Multi-AI-Agent Coding Assistant

## 📌 Project Overview

The **Multi-AI-Agent Coding Assistant** is a Streamlit-based intelligent coding assistant built using a modular multi-agent architecture.

The system uses **LangChain for LLM integration, prompt management, and AI workflow handling**. Instead of depending on a single AI model for every task, the application uses multiple specialized AI agents coordinated by a central **Coordinator Agent**.

The system intelligently routes user requests to dedicated agents such as Coding, Debugging, Documentation, Planning, and Project Analysis agents. It also integrates tools for file management, project analysis, code execution, and automated code modification.

---

# ✨ Features

* 💻 AI Code Generation
* 🐞 AI Code Debugging
* 📖 Code Explanation and Documentation
* 📝 Planning Agent for Software Development Tasks
* 📊 Project Structure Analysis
* 📂 File Creation, Reading, Updating, and Deletion
* ▶️ Python Code Execution with Dynamic Test Input
* 🔧 Patch-based Code Modification
* 📁 Multi-file Code Generation
* 💬 ChatGPT-style Streamlit Interface
* 🧠 JSON-based Conversation Memory
* 🔗 LangChain ChatGroq Integration
* 📝 LangChain Prompt Templates
* ⏱ Execution Time Monitoring
* 📥 Download Generated Responses

---

# 🏗️ Architecture

```

User

↓

Streamlit Chat Interface

↓

Coordinator Agent

↓

Specialized AI Agents

├── Coding Agent
├── Debugging Agent
├── Documentation Agent
├── Planner Agent
└── Project Analyzer Agent

↓

LangChain Prompt Templates

↓

ChatGroq LLM Integration

↓

Tools Layer

├── File Tool
├── Project Analyzer
├── Code Executor
├── Patch Tool
└── Multi File Parser

↓

Memory Layer

├── JSON Conversation Memory
└── History Storage

```

---

# 📂 Project Structure

```

Multi-AI-Agent-Coding-Assistant/

│
├── agents/
│   ├── coordinator.py
│   ├── coding_agent.py
│   ├── debugging_agent.py
│   ├── documentation_agent.py
│   ├── planner.py
│   └── project_analyzer_agent.py
│
├── models/
│   ├── llm.py
│   └── model_manager.py
│
├── prompts/
│   ├── coding_prompt.py
│   ├── debugging_prompt.py
│   ├── documentation_prompt.py
│   ├── planner_prompt.py
│   └── project_analyzer_prompt.py
│
├── memory/
│   ├── memory.py
│   ├── memory_manager.py
│   ├── storage.py
│   └── history.json
│
├── tools/
│   ├── file_tool.py
│   ├── code_executor.py
│   ├── project_analyzer.py
│   ├── patch_tool.py
│   └── multi_file_parser.py
│
├── app.py
├── main.py
├── requirements.txt
├── README.md
└── .env

````

---

# ⚙️ Installation

## 1. Clone the repository

```bash
git clone <repository-url>
````

## 2. Create a virtual environment

```bash
python -m venv venv
```

Activate environment:

Windows:

```bash
venv\Scripts\activate
```

Linux/Mac:

```bash
source venv/bin/activate
```

---

## 3. Install dependencies

```bash
pip install -r requirements.txt
```

---

## 4. Configure Environment Variables

Create a `.env` file:

```
GROQ_API_KEY=your_api_key_here
```

---

## 5. Run the Application

```bash
streamlit run app.py
```

The application will start at:

```
http://localhost:8501
```

---

# 💬 Example Prompts

### Code Generation

```
Create a Python calculator program.
```

### Debugging

```
Debug this Python error:
IndexError: list index out of range
```

### Documentation

```
Explain Python decorators.
```

### Project Analysis

```
Analyze my project structure.
```

### File Management

```
Create file hello.py.
```

### Code Execution

```
Create a Python Fibonacci program and execute it.
```

---

# 🔗 LangChain Integration

The project uses LangChain components for:

* LLM communication using ChatGroq
* ChatPromptTemplate based prompt management
* Structured AI agent workflows
* Modular prompt architecture
* Future support for advanced LangChain chains and memory

---

# 🧠 Memory System

The project implements a hybrid memory approach:

## Short-Term Memory

Used during conversations for maintaining context.

## Long-Term Memory

Stored using:

```
memory/history.json
```

This allows previous interactions to be saved and reused.

---

# 🛠️ Technologies Used

* Python
* Streamlit
* LangChain
* LangChain Core
* LangChain ChatGroq
* Groq LLM API
* Large Language Models
* JSON-based Memory Storage

---

# 🚀 Development Progress

## Milestone 1 Completed ✅

Implemented:

* LangChain environment setup
* ChatGroq LLM integration
* Modular AI agent architecture
* Coordinator-based decision workflow
* LangChain ChatPromptTemplates
* Specialized AI agents
* Streamlit testing interface
* Code execution workflow
* File management tools
* JSON conversation memory

---

# 🔮 Future Enhancements

* LangChain Conversation Memory integration
* Advanced LangChain Chains
* Support for additional programming languages
* Conversation export
* Authentication system
* Voice input support
* GitHub repository analysis
* Docker deployment
* Cloud deployment

---

# 👨‍💻 Author

Developed as a **Multi-AI-Agent Coding Assistant project** using:

* Streamlit
* LangChain
* ChatGroq
* Python
* Modular AI Agent Architecture

