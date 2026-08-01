import streamlit as st
import time

from models.llm import LLM
from tools.llm_guard import LLMGuard
from memory.memory import Memory
from memory.short_term_memory import ShortTermMemory
from agents.coordinator import CoordinatorAgent



# --------------------------------------------------
# PAGE CONFIG
# --------------------------------------------------
st.set_page_config(
    page_title="Multi-AI-Agent Coding Assistant",
    page_icon="🤖",
    layout="wide"
)

# --------------------------------------------------
# SIDEBAR
# --------------------------------------------------
with st.sidebar:

    st.title("🤖 AI Assistant")

    st.markdown("### 🧠 Available Agents")

    st.success("Coding Agent")
    st.success("Debugging Agent")
    st.success("Documentation Agent")
    st.success("Planner Agent")

    st.markdown("---")

    st.markdown("### 🛠 Available Tools")

    st.info("📁 File Tool")
    st.info("📊 Project Analyzer")
    st.info("▶️ Code Executor")
    st.info("📝 Patch Tool")

    st.markdown("---")

    if st.button("🗑 Clear Chat", use_container_width=True):
        st.session_state.messages = []
        st.rerun()

# --------------------------------------------------
# TITLE
# --------------------------------------------------
st.title("🤖 Multi-AI-Agent Coding Assistant")

st.caption(
    "Coding • Debugging • Documentation • Project Analysis"
)

# --------------------------------------------------
# SESSION STATE
# --------------------------------------------------
if "messages" not in st.session_state:
    st.session_state.messages = []

# --------------------------------------------------
# LOAD BACKEND
# --------------------------------------------------
model = LLM()
guard = LLMGuard()
memory = Memory()
short_memory = ShortTermMemory()

coordinator = CoordinatorAgent(
    model,
    guard,
    memory,
    short_memory
)

# --------------------------------------------------
# DISPLAY CHAT HISTORY
# --------------------------------------------------
for message in st.session_state.messages:

    with st.chat_message(message["role"]):

        if message.get("type") == "code":
            st.code(message["content"], language="python")
        else:
            st.markdown(message["content"])

uploaded_file = st.file_uploader(
    "📂 Upload a Python file",
    type=["py", "txt"]
)

if uploaded_file is not None:

    file_content = uploaded_file.read().decode("utf-8")

    st.subheader("📄 Uploaded File")

    st.code(file_content, language="python")
# --------------------------------------------------
# USER INPUT
# --------------------------------------------------
prompt = st.chat_input("Ask me anything about coding...")

if prompt:
    display_prompt = prompt

    if uploaded_file is not None:
        prompt = f"""
    User Request:
    {display_prompt}

    Uploaded File:
    {file_content}
    """


    # --------------------------
    # USER MESSAGE
    # --------------------------
    st.session_state.messages.append(
        {
            "role": "user",
            "content": prompt
        }
    )

    with st.chat_message("user"):
        st.markdown(display_prompt)

    # --------------------------
    # ASSISTANT
    # --------------------------
    with st.chat_message("assistant"):

        with st.spinner("🤖 Thinking..."):

            start = time.time()
            

            result = coordinator.handle_task(prompt)
            

            response = result["response"]
            agent = result["agent"]

            st.info(f"🧠 Agent Used: {agent}")


            # Save conversation to long-term memory
            if "workflow" in result:
                memory_response = "Collaborative workflow completed."
            else:
                memory_response = response

            memory.add_conversation(
                user_message=prompt,
                assistant_message=memory_response
            )
                        

            end = time.time()

            execution_time = end - start

            if "workflow" in result:

                st.subheader("📝 Planning Result")
                st.write(result["workflow"]["planner"])

                st.subheader("💻 Coding Result")
                st.code(
                    result["code"],
                    language="python"
                )

                st.subheader("🔍 Review Result")
                st.write(result["workflow"]["review"])

                st.subheader("📄 Documentation Result")
                st.write(result["workflow"]["documentation"])

            else:
                st.markdown(response)
            

        st.success(
            f"Completed in {execution_time:.2f} seconds"
        )

        # Download Button
        st.download_button(
            label="📥 Download Response",
            data=response,
            file_name="assistant_response.txt",
            mime="text/plain",
            use_container_width=True
        )

    message_type = "text"

    if "workflow" in result:
        message_type = "text"

    elif response.strip().startswith(
        (
            "def ",
            "class ",
            "import ",
            "from "
        )
    ):
        message_type = "code"

    st.session_state.messages.append(
        {
            "role": "assistant",
            "content": response,
            "type": message_type
        }
    )