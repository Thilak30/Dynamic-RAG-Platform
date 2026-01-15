import streamlit as st
from streamlit_option_menu import option_menu # Import the component
from utils.state_manager import init_state
from views.dashboard_page import render_page as render_dashboard
from views.chat_page import render_page as render_chat
from views.settings_page import render_page as render_settings

# Set page configuration
st.set_page_config(
    page_title="GenAI Workspace",
    page_icon="🤖",
    layout="wide"
)

# Initialize session state
init_state()

# Inject Custom CSS
def load_css(file_name):
    with open(file_name) as f:
        st.markdown(f'<style>{f.read()}</style>', unsafe_allow_html=True)

load_css("assets/style.css")

# API Key Verification & Setup
if not st.session_state.get("GROQ_API_KEY") or not st.session_state.get("TAVILY_API_KEY"):
    st.title("⚙️ Setup Required")
    st.warning("API Keys are missing. Please provide them below to continue.")
    
    with st.form("api_key_form"):
        groq_key = st.text_input("Groq API Key", type="password", help="Get it from console.groq.com")
        tavily_key = st.text_input("Tavily API Key", type="password", help="Get it from tavily.com")
        
        if st.form_submit_button("Save & Continue", width="stretch"):
            if groq_key and tavily_key:
                st.session_state["GROQ_API_KEY"] = groq_key
                st.session_state["TAVILY_API_KEY"] = tavily_key
                st.success("Keys saved! Reloading...")
                st.rerun()
            else:
                st.error("Both keys are required.")
    
    st.stop() # Stop execution here until keys are provided

# Navigation Logic
default_index = 0
options = ["Dashboard", "Custom Search", "RAG Agent", "Settings"]

if "switch_page" in st.session_state and st.session_state.switch_page:
    target = st.session_state.switch_page
    if target in options:
        default_index = options.index(target)
    # Clear the switch signal so we don't get stuck
    st.session_state.switch_page = None

#  Sidebar 
with st.sidebar:
    st.header("GenAI Workspace")
    
    # Main Navigation Menu
    selected_page = option_menu(
        "Menu",
        ["Dashboard", "Chat", "Settings"],
        icons=['speedometer2', 'chat-dots', 'gear'],
        menu_icon="cast",
        default_index=default_index,
    )
    
    st.divider()
    
    # --- Session Management in Sidebar ---
    from utils.database import get_all_sessions, load_chat_history_from_db, delete_session
    import uuid
    
    if selected_page == "Chat":
        st.subheader("💬 Chat History")
        
        # New Chat Button
        if st.button("➕ New Chat", use_container_width=True):
            new_id = str(uuid.uuid4())
            st.session_state.current_session_id = new_id
            st.session_state.chat_messages = [] # Start blank
            st.rerun()
            
        st.markdown("---")
        
        # List recent sessions
        sessions = get_all_sessions()
        
        for sess in sessions:
            s_id = sess["session_id"]
            last_msg = sess["user_prompt"][:40] + "..." if sess["user_prompt"] else "Empty Chat"
            
            # Highlight current session
            btn_style = "primary" if s_id == st.session_state.get("current_session_id") else "secondary"
            
            col1, col2 = st.columns([0.8, 0.2])
            with col1:
                if st.button(f"{last_msg}", key=f"sess_{s_id}", use_container_width=True, help=s_id):
                    st.session_state.current_session_id = s_id
                    st.session_state.chat_messages = load_chat_history_from_db(s_id)
                    st.rerun()
            with col2:
                if st.button("🗑", key=f"del_{s_id}"):
                    delete_session(s_id)
                    if s_id == st.session_state.get("current_session_id"):
                        # Reset if deleting current
                        st.session_state.current_session_id = str(uuid.uuid4())
                        st.session_state.chat_messages = []
                    st.rerun()
    
    st.divider()
    
    # Global Sidebar Actions
    if selected_page == "Chat":
        if st.session_state.chat_messages: # Only show if history exists
            if st.sidebar.button("🗑️ Clear Chat History", width="stretch"):
                st.session_state.chat_messages = []
                st.rerun()


if "switch_page" in st.session_state:
    target_page = st.session_state.switch_page
    st.session_state.max_nav_page = target_page # Helper to track current page if needed
    # We need to rerun to reflect the change visually in the sidebar if we could control it, 
    # but option_menu is reactive. We just render the target page content.
    # Ideally, we synced default_index above.
    del st.session_state.switch_page
    
# Render selected page
if selected_page == "Dashboard":
    render_dashboard()
elif selected_page == "Chat":
    render_chat()
elif selected_page == "Settings":
    render_settings()
