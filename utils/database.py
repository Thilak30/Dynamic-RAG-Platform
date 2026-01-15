import sqlite3
import json
import os

DB_FILE = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "data", "interactions.db"))
# Ensure we refer to DB_FILE correctly relative to CWD or absolute?
# The original utils.py just used "interactions.db", implying CWD. We keep it same.

def setup_database():
    """Create the database and table, with all necessary columns for persistence."""
    os.makedirs(os.path.dirname(DB_FILE), exist_ok=True)
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    # Create table if not exists with new schema
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS interactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT DEFAULT 'default',
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            user_prompt TEXT NOT NULL,
            web_context TEXT,
            llm_response TEXT,
            rating INTEGER DEFAULT 0,
            source TEXT,
            sources TEXT
        )
    """)
    
    # Migration: Check if session_id column exists
    cursor.execute("PRAGMA table_info(interactions)")
    columns = [info[1] for info in cursor.fetchall()]
    if "session_id" not in columns:
        cursor.execute("ALTER TABLE interactions ADD COLUMN session_id TEXT DEFAULT 'default'")
        
    conn.commit()
    conn.close()

def log_interaction(user_prompt: str, web_context: str, llm_response: str, source: str, sources: list, session_id: str = "default"):
    """Logs a complete user interaction to the database and returns its ID."""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    sources_json = json.dumps(sources)
    cursor.execute(
        "INSERT INTO interactions (session_id, user_prompt, web_context, llm_response, source, sources) VALUES (?, ?, ?, ?, ?, ?)",
        (session_id, user_prompt, web_context, llm_response, source, sources_json)
    )
    interaction_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return interaction_id

def update_interaction_rating(interaction_id: int, rating: int):
    """Updates the rating for a specific interaction."""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("UPDATE interactions SET rating = ? WHERE id = ?", (rating, interaction_id))
    conn.commit()
    conn.close()

def find_similar_interaction(query: str):
    """Finds a similar, highly-rated past interaction from the database."""
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT user_prompt, llm_response 
        FROM interactions 
        WHERE user_prompt LIKE ? AND rating >= 1
        ORDER BY rating DESC, timestamp DESC
        LIMIT 1
        """,
        (f'%{query.strip()}%',)
    )
    result = cursor.fetchone()
    conn.close()
    if result:
        return {"past_question": result["user_prompt"], "past_answer": result["llm_response"]}
    return None

def load_chat_history_from_db(session_id: str = "default", limit: int = 50):
    """Loads the last N interactions for a specific session."""
    if not os.path.exists(DB_FILE): return []
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM interactions WHERE session_id = ? ORDER BY timestamp DESC LIMIT ?", (session_id, limit))
    rows = cursor.fetchall()
    conn.close()
    messages = []
    for row in reversed(rows):
        messages.append({"role": "user", "content": row["user_prompt"]})
        messages.append({
            "role": "assistant",
            "content": row["llm_response"],
            "source": row["source"],
            "sources": json.loads(row["sources"]) if row["sources"] else [],
            "interaction_id": row["id"]
        })
    return messages

def get_all_sessions():
    """Returns a list of all distinct sessions with their last update time."""
    if not os.path.exists(DB_FILE): return []
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    # Group by session and get the snippet of the first (latest) message
    cursor.execute("""
        SELECT session_id, MAX(timestamp) as last_active, user_prompt 
        FROM interactions 
        GROUP BY session_id 
        ORDER BY last_active DESC
    """)
    rows = cursor.fetchall()
    conn.close()
    return rows

def delete_session(session_id: str):
    """Deletes all interactions for a given session."""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM interactions WHERE session_id = ?", (session_id,))
    conn.commit()
    conn.close()

def load_query_history_from_db(limit: int = 10):
    """Loads the last N user prompts from the DB for the dashboard."""
    if not os.path.exists(DB_FILE): return []
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT user_prompt FROM interactions ORDER BY timestamp DESC LIMIT ?", (limit,))
    rows = cursor.fetchall()
    conn.close()
    # We create a history list compatible with the dashboard dataframe
    # For now, we assume 'RAG Agent' for DB items as they come from the chat page
    # In a full app, we would store the type in the DB.
    history = [{"Query": row[0], "Type": "RAG Agent"} for row in rows]
    return history
