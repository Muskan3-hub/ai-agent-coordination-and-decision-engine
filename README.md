# 🤖 Multi-AI-Agent Coding Assistant with Intelligent Decision Engine

## 📌 Project Overview

The **Multi-AI-Agent Coding Assistant with Intelligent Decision Engine** is an intelligent software development platform designed to assist developers in coding, debugging, documentation, planning, and project analysis tasks.

The system is built using **Python, Streamlit, LangChain, and ChatGroq** and follows a modular **Multi-Agent AI Architecture** where multiple specialized AI agents collaborate to solve different software engineering problems.

Unlike traditional AI assistants that depend on a single AI model for all tasks, this project separates:

* 🧠 Decision Making
* 🤝 Workflow Coordination
* 🤖 Task Execution
* 🛠 Tool Interaction
* 🔐 Security Validation

into independent components.

The system consists of:

* 🧠 Intelligent Decision Engine
* 🤝 Coordinator Agent
* 🤖 Specialized AI Agents
* 🛠 Enterprise Tool Framework
* 🔐 Security Guard Layer
* 💾 Hybrid Memory System
* 📊 Validation & Execution Monitoring System

The **Decision Engine** analyzes user requests, understands the intent, selects the required AI agent, and determines whether external tools are required.

The **Coordinator Agent** manages the complete workflow by assigning tasks to specialized agents, communicating between components, invoking tools, maintaining memory, validating actions, and generating the final response.

The architecture is designed to be scalable, maintainable, and extendable with new AI agents and enterprise tools.

---

# 🎯 Objectives

The main objectives of this project are:

* Build an intelligent Multi-AI Coding Assistant.
* Implement an AI-based Decision Engine for task routing.
* Develop multiple specialized AI agents.
* Enable AI agents to perform real coding operations using tools.
* Provide secure execution and validation of AI-generated actions.
* Maintain conversation history and tool execution records.
* Create a modular architecture that can be extended easily.

---

# ✨ Features

## 🤖 Multi-Agent Intelligence

The system contains multiple specialized AI agents:

### 💻 Coding Agent

* Generates programming solutions.
* Creates new code files.
* Implements software features.

### 🐞 Debugging Agent

* Identifies programming errors.
* Explains bugs.
* Suggests corrections.

### 📖 Documentation Agent

* Generates documentation.
* Explains code functionality.
* Creates project descriptions.

### 📝 Planner Agent

* Breaks complex software tasks into smaller steps.
* Creates development plans.

### 📊 Project Analyzer Agent

* Analyzes project structure.
* Provides project insights.

---

# 🧠 Intelligent Decision Engine

The Decision Engine is responsible for:

* Understanding user intent.
* Classifying the requested task.
* Selecting the appropriate AI agent.
* Selecting required tools.
* Creating an execution plan.

Example:

```
User:
"Fix this Python error"

Decision Engine:
Task Type → Debugging

Selected Agent:
Debugging Agent
```

---

# 🤝 Coordinator Agent

The Coordinator Agent acts as the workflow management layer.

Responsibilities:

* Receives decisions from the Decision Engine.
* Communicates with AI agents.
* Manages agent execution.
* Invokes tools through Tool Manager.
* Collects outputs.
* Returns final responses.

---

# 🛠 Enterprise Tool Integration

The system provides an enterprise-level tool framework.

## 📂 File Tool

Capabilities:

* Create files
* Read files
* Update files
* Delete files

---

## ▶️ Code Executor

Capabilities:

* Execute Python programs.
* Capture output.
* Handle execution errors.

---

## 🔧 Patch Tool

Capabilities:

* Modify existing files.
* Apply targeted code changes.
* Prevent unnecessary rewriting.

---

## 📁 Multi File Parser

Capabilities:

* Handle multiple file operations.
* Parse structured code changes.

---

## 🔍 Project Analyzer Tool

Capabilities:

* Analyze project folders.
* Identify files and structure.
* Generate project summaries.

---

## 🌐 GitHub Tool

Capabilities:

* Analyze GitHub repositories.
* Extract repository information.

---

# 🔐 Security Guard Layer

The Security Guard provides protection while executing AI-generated actions.

Responsibilities:

* Validate AI-generated actions.
* Prevent unsafe operations.
* Check tool execution requests.
* Control access to sensitive operations.
* Improve reliability of automated workflows.

The Security Guard works with the Tool Manager before executing external actions.

Workflow:

```
AI Agent Request

        ↓

Security Guard Validation

        ↓

Tool Manager

        ↓

Tool Execution
```

---

# 📊 Validation & Monitoring System

The system includes monitoring components:

## Action Validator

* Checks whether requested actions are valid.
* Prevents incorrect execution.

## Execution Tracker

* Tracks tool execution details.
* Records execution status.

## Logger

* Stores system events.
* Helps debugging and monitoring.

---

# 💾 Hybrid Memory System

The project implements memory management for maintaining context.

Components:

## Short-Term Memory

Stores:

* Current conversation context.
* Active task information.

## Long-Term Memory

Stores:

* Previous interactions.
* Tool execution history.

Files:

```
history.json

tool_execution_history.json
```

---

# 🏗️ System Architecture

```
                         User
                           │
                           ▼
                Streamlit Chat Interface
                           │
                           ▼
                  Intelligent Decision Engine
              (Intent Detection & Task Routing)
                           │
                           ▼
                    Coordinator Agent
              (Workflow Orchestration Layer)
                           │
          ┌────────────────┼────────────────┐
          │                │                │
          ▼                ▼                ▼

 Specialized AI Agents       Enterprise Tools

          │                      │
          │                      ▼
          │              Security Guard
          │                      │
          │                      ▼
          │              Tool Manager
          │
          ▼

 ┌───────────────────────────────────────┐
 │ Coding Agent                          │
 │ Debugging Agent                       │
 │ Documentation Agent                   │
 │ Planner Agent                         │
 │ Project Analyzer Agent                │
 └───────────────────────────────────────┘

                           │
                           ▼

                  LangChain Prompt System

                           │
                           ▼

                     ChatGroq LLM

                           │
                           ▼

              Validation & Monitoring Layer

        ┌─────────────────────────────┐
        │ Action Validator             │
        │ Execution Tracker            │
        │ Logger                       │
        └─────────────────────────────┘

                           │
                           ▼

                    Hybrid Memory Layer

        ┌─────────────────────────────┐
        │ Short-Term Memory            │
        │ Long-Term Memory             │
        │ history.json                 │
        │ tool_execution_history.json  │
        └─────────────────────────────┘
```

---

# 📂 Project Structure

```
Multi-AI-Agent-Coding-Assistant/

├── agents/
│   ├── coordinator.py
│   ├── decision_engine.py
│   ├── coding_agent.py
│   ├── debugging_agent.py
│   ├── documentation_agent.py
│   ├── planner.py
│   └── project_analyzer_agent.py

├── assets/
│   └── image.png

├── config/

├── memory/
│   ├── history.json
│   ├── memory.py
│   ├── memory_manager.py
│   └── storage.py

├── models/
│   ├── llm.py
│   └── model_manager.py

├── prompts/
│   ├── coding_prompt.py
│   ├── debugging_prompt.py
│   ├── documentation_prompt.py
│   ├── planner_prompt.py
│   └── project_analyzer_prompt.py

├── tests/
│   ├── test_agents.py
│   ├── test_tools.py
│   └── test_workflows.py

├── tools/
│   ├── action_validator.py
│   ├── security_guard.py
│   ├── base_tool.py
│   ├── code_executor.py
│   ├── execution_tracker.py
│   ├── file_tool.py
│   ├── github_tool.py
│   ├── llm_guard.py
│   ├── logger.py
│   ├── multi_file_parser.py
│   ├── patch_parser.py
│   ├── patch_tool.py
│   ├── project_analyzer.py
│   └── tool_manager.py

├── .env
├── .gitignore
├── app.py
├── main.py
├── pytest.ini
├── README.md
└── requirements.txt
```

---

# 🛠 Technologies Used

* Python
* Streamlit
* LangChain
* ChatGroq LLM
* Prompt Engineering
* Object-Oriented Programming
* JSON-based Memory Storage
* File Processing
* Subprocess Execution
* AI Agent Architecture

---

# 🚀 Future Enhancements

Possible future improvements:

* Docker-based secure code execution.
* More programming language support.
* Advanced multi-agent collaboration.
* GitHub automation.
* Cloud deployment.
* Enterprise authentication.
* Improved AI planning capabilities.

---

# ✅ Conclusion

The **Multi-AI-Agent Coding Assistant with Intelligent Decision Engine** demonstrates how multiple specialized AI agents can collaborate through an intelligent coordination framework.

The Decision Engine provides intelligent task routing, the Coordinator Agent manages workflow execution, AI agents perform specialized tasks, and enterprise tools enable real coding operations.

With security validation, memory management, and monitoring capabilities, the system provides a scalable foundation for next-generation AI-powered software development assistants.

