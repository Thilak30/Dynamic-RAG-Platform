import streamlit as st
import streamlit.components.v1 as components
import json
import os
from utils.api_clients import run_tavily_search, ask_groq
from utils.logging_utils import log_search, log_llm_call
from utils.text_utils import count_tokens
from utils.database import log_interaction, find_similar_interaction, update_interaction_rating
from utils.prompt_loader import load_prompt
from utils.document_processor import process_uploaded_file
from utils.vector_store_manager import VectorStoreManager
from langchain_core.documents import Document
from utils.retriever_agent import get_retriever_decision, grade_documents

from utils.constants import RetrievalStrategy

# Initialize Vector Store Manager in Session State
if "vector_store_manager" not in st.session_state:
    st.session_state.vector_store_manager = VectorStoreManager()


def check_pending_query():
    if "pending_query" in st.session_state and st.session_state.pending_query:
        q = st.session_state.pending_query
        st.session_state.pending_query = None
        return q
    return None

def render_page():
    """
    Renders the RAG Agent page.
    Handled file uploads, auto-processing, chat interface, and intelligent agent routing.
    """
    st.title("RAG Agent")
    st.caption("Upload documents or ask general questions. The Agent will route your query.")


    


    user_prompt = None # Initialize to avoid UnboundLocalError

    # Find the index of the last user message to show edit button
    last_user_msg_index = -1
    for i in range(len(st.session_state.chat_messages) - 1, -1, -1):
        if st.session_state.chat_messages[i]["role"] == "user":
            last_user_msg_index = i
            break

    # Display chat history
    for i, msg in enumerate(st.session_state.chat_messages):
        with st.chat_message(msg["role"]):
            if "source" in msg: st.caption(msg["source"])
            

            if "retrieval_strategy" in msg:
                strategy = msg["retrieval_strategy"]
                badge_color = "blue"
                if strategy == RetrievalStrategy.WEB_SEARCH.value: badge_color = "red"
                elif strategy == RetrievalStrategy.VECTOR_BASED.value: badge_color = "green"
                elif strategy == RetrievalStrategy.HYBRID.value: badge_color = "orange"
                
                st.markdown(f":{badge_color}[**[{strategy}]**]")

            if i == last_user_msg_index and msg["role"] == "user":
                # Use columns to place text and edit/rerun buttons side-by-side
                c1, c2 = st.columns([0.85, 0.15])
                with c1:
                    st.markdown(msg["content"])
                with c2:
                    # Nested columns for the buttons to keep them close
                    b1, b2 = st.columns([1, 1])
                    with b1:
                        if st.button("✏️", key=f"edit_btn_{i}", help="Edit Query"):
                            st.session_state.editing_query = msg["content"]
                            st.rerun()
                    with b2:
                         if st.button("🔄", key=f"rerun_btn_{i}", help="Rerun Query"):
                            st.session_state.pending_query = msg["content"]
                            st.rerun()
            else:
                st.markdown(msg["content"])

            # Render Sources at the bottom if available
            if "sources" in msg and msg["sources"]:
                with st.expander("📚 Sources & References", expanded=False):
                    for idx, src in enumerate(msg["sources"]):
                        # Handle Web Results (Dict) vs Documents (Object)
                        if isinstance(src, dict):
                            # Web Result
                            st.markdown(f"**{idx+1}. [{src.get('title', 'Link')}]({src.get('url', '#')})**")
                            st.caption(src.get('content', '')[:150] + "...")
                        else:
                            # Document Object
                            meta = src.metadata
                            source_name = meta.get('source', 'Unknown Document')
                            page = meta.get('page', 'N/A')
                            st.markdown(f"**{idx+1}. {source_name}** (Page {page})")
                            st.caption(src.page_content[:150] + "...")
                        st.divider()


            if msg["role"] == "assistant" and "interaction_id" in msg:
                feedback_key_base = f"feedback_{msg['interaction_id']}"
                col1, col2, _ = st.columns([1, 1, 10])
                with col1:
                    if st.button("👍", key=f"{feedback_key_base}_up"):
                        update_interaction_rating(msg["interaction_id"], 1)
                        st.toast("Thanks!")
                with col2:
                    if st.button("👎", key=f"{feedback_key_base}_down"):
                        update_interaction_rating(msg["interaction_id"], -1)


    pending_q = check_pending_query()
    

    with st.popover("📎 Attach Documents", use_container_width=False):
        uploaded_files = st.file_uploader(
            "Upload files to Knowledge Base", 
            type=["pdf", "docx", "xlsx", "xls", "txt"], 
            accept_multiple_files=True
        )
        
        if "processed_files" not in st.session_state:
            st.session_state.processed_files = set()
            
        if uploaded_files:
            new_files = []
            for f in uploaded_files:
                if f.name not in st.session_state.processed_files:
                    new_files.append(f)
            
            if new_files:
                with st.spinner(f"Processing {len(new_files)} new file(s)..."):
                    try:
                        all_docs = []
                        for uploaded_file in new_files:
                            docs = process_uploaded_file(uploaded_file)
                            all_docs.extend(docs)
                            # Mark as processed
                            st.session_state.processed_files.add(uploaded_file.name)
                        
                        if all_docs:
                            st.session_state.vector_store_manager.add_documents(all_docs)
                            st.success(f"Indexed {len(all_docs)} chunks!")
                        else:
                            st.warning("No text found.")
                            
                    except Exception as e:
                        st.error(f"Error: {e}")

    # Edit Mode Logic
    if "editing_query" in st.session_state and st.session_state.editing_query:
        # Scroll to bottom to ensure user sees the edit form
        # We need to target the parent window's main container, not the iframe's window
        components.html("""
            <script>
                // Attempt to find the main scrollable section of Streamlit
                const main = window.parent.document.querySelector('.main') || 
                             window.parent.document.querySelector('section[data-testid="stMain"]');
                if (main) {
                    main.scrollTop = main.scrollHeight;
                }
            </script>
        """, height=0, width=0)
        
        with st.container(border=True):
            st.subheader("✏️ Edit & Rerun")
            with st.form("edit_query_form"):
                edited_query = st.text_area("Your Query", value=st.session_state.editing_query, height=100)
                c1, c2 = st.columns([1, 1])
                cancel = c1.form_submit_button("❌ Cancel")
                run = c2.form_submit_button("🚀 Run")
                
                if cancel:
                    del st.session_state.editing_query
                    st.rerun()
                
                if run:
                    user_prompt = edited_query
                    del st.session_state.editing_query
                    # Clean slate for rerun context if needed

    else:
        user_prompt = st.chat_input("Ask about your documents or anything else...")

    if pending_q:
        user_prompt = pending_q

    if user_prompt:
        st.session_state.chat_messages.append({"role": "user", "content": user_prompt})
        with st.chat_message("user"):
            st.markdown(user_prompt)

        with st.chat_message("assistant"):
            
            # 1. Check Semantic Memory First
            cached_response = st.session_state.vector_store_manager.check_memory(user_prompt)
            if cached_response:
                st.success("⚡ Accessed from Memory")
                st.markdown(cached_response)
                st.session_state.chat_messages.append({
                    "role": "assistant", 
                    "content": cached_response,
                    "source": "Memory Cache"
                })
                st.rerun()

            # 2. Intelligent Agent Classification (Router)
            with st.spinner("Analyzing query..."):
                agent_decision = get_retriever_decision(
                    user_prompt, 
                    st.session_state.get("GROQ_API_KEY"),
                    st.session_state.settings.get("groq_model", "llama3-8b-8192")
                )
            
            context_text = ""
            sources = []
            final_strategy = ""

            # 3. Handle Direct LLM (Chit-Chat, Coding, General) vs RAG
            if agent_decision['strategy'] == RetrievalStrategy.DIRECT_LLM.value:
                final_strategy = RetrievalStrategy.DIRECT_LLM.value
                rag_template = load_prompt("direct_llm_system.txt")
                system_prompt = rag_template # No context injection
            else:
                # Proceed with Dynamic RAG (Vector -> Grade -> Web)
                
                # A. Attempt Vector Search
                docs = []
                final_strategy = RetrievalStrategy.VECTOR_BASED.value # Default start for RAG

                if st.session_state.vector_store_manager.vector_store is not None:
                    with st.spinner("Searching Vector Database..."):
                        docs = st.session_state.vector_store_manager.similarity_search(user_prompt, k=4)
                
                # B. Grade Results
                grade = "no"
                if docs:
                    with st.spinner("Grading retrieved documents..."):
                        grade = grade_documents(
                            user_prompt, 
                            docs, 
                            st.session_state.get("GROQ_API_KEY"),
                            st.session_state.settings.get("groq_model", "llama3-8b-8192")
                        )
                
                # C. Decision: Vector vs Web
                if grade == "yes":
                    st.toast("Relevance Grade: ✅ Relevant")
                    final_strategy = RetrievalStrategy.VECTOR_BASED.value
                    context_text += "\n\n**Retrieved Documents:**\n"
                    for doc in docs:
                        src_name = doc.metadata.get('source', 'Unknown Doc')
                        page_num = doc.metadata.get('page', 'Unknown')
                        context_text += f"--Source: {src_name} (Page {page_num})--\n{doc.page_content}\n"
                        sources.append(doc)
                else:
                    st.toast("Relevance Grade: ❌ Not Relevant. Switching to Web Search.")
                    final_strategy = RetrievalStrategy.WEB_SEARCH.value
                    
                    with st.spinner("Searching the Web (Tavily)..."):
                        depth = st.session_state.settings.get("tavily_depth", "advanced")
                        count = st.session_state.settings.get("search_count", 5)
                        
                        web_context, web_results = run_tavily_search(
                            user_prompt, 
                            search_depth="advanced" if depth != "basic" else "basic", # loose handling
                            result_count=count
                        )
                        
                        if "Error" in web_context:
                            st.error(web_context)
                        else:
                            context_text += f"\n\n**Web Search Results:**\n{web_context}\n"
                            
                            # INDEXING STEP: Convert Web Results to Documents and Add to Vector Store
                            new_docs = []
                            for r in web_results:
                                sources.append(r) # For display
                                # Create a Document for indexing
                                doc_content = f"Title: {r['title']}\nURL: {r['url']}\nContent: {r['content']}"
                                new_doc = Document(
                                    page_content=doc_content, 
                                    metadata={"source": r['title'], "url": r['url'], "page": "Web"}
                                )
                                new_docs.append(new_doc)
                            
                            if new_docs:
                                st.session_state.vector_store_manager.add_documents(new_docs)
                                st.toast(f"Indexed {len(new_docs)} web results for future use.")

                # D. Prepare RAG Prompt
                rag_template = load_prompt("rag_response_system.txt")
                system_prompt = rag_template.format(context_text=context_text)
            
            messages = [{"role": "system", "content": system_prompt}] + [
                {"role": m["role"], "content": m["content"]} for m in st.session_state.chat_messages if m["role"] != "system"
            ]

            provider = "Groq (Web-based)"
            model = st.session_state.settings.get("groq_model", "llama-3.3-70b-versatile")
            
            with st.spinner("Generating answer..."):
                response_text = ask_groq(messages, model, st.session_state.settings.get("temperature", 0.5))
                st.markdown(response_text)
                
                # Render sources immediately for current turn
                if sources:
                     with st.expander("📚 Sources & References", expanded=False):
                        for idx, src in enumerate(sources):
                            if isinstance(src, dict):
                                st.markdown(f"**{idx+1}. [{src.get('title', 'Link')}]({src.get('url', '#')})**")
                            else:
                                meta = src.metadata
                                st.markdown(f"**{idx+1}. {meta.get('source', 'Doc')}**")

            # Log Interaction
            interaction_id = log_interaction(
                user_prompt=user_prompt,
                web_context=context_text,
                llm_response=response_text,
                source=f"Groq ({model}) - {final_strategy}",
                sources=[s.metadata if hasattr(s, 'metadata') else s for s in sources],
                session_id=st.session_state.get("current_session_id", "default")
            )
            
            # Save to Memory
            st.session_state.vector_store_manager.add_to_memory(user_prompt, response_text)

            st.session_state.chat_messages.append({
                "role": "assistant", 
                "content": response_text,
                "source": f"Groq ({model})", 
                "sources": sources,
                "retrieval_strategy": final_strategy,
                "interaction_id": interaction_id
            })
            
            log_llm_call(provider, model, count_tokens(str(messages)), count_tokens(response_text))
            
            st.rerun()
