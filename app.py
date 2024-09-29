import streamlit as st
from pathlib import Path
from langchain.agents import create_sql_agent
from langchain.sql_database import SQLDatabase
from langchain.agents.agent_types import AgentType
from langchain.callbacks import StreamlitCallbackHandler
from langchain.agents.agent_toolkits import SQLDatabaseToolkit
from sqlalchemy import create_engine, exc, event, select
from urllib.parse import quote_plus
import sqlite3
from langchain_groq import ChatGroq
from langchain.agents import AgentExecutor

# Page Configuration
st.set_page_config(page_title="LangChain: Chat with SQL DB", page_icon="🦜")
st.title("🦜 LangChain: Chat with SQL DB")

# Constants for Database Types
LOCALDB = "USE_LOCALDB"
MYSQL = "USE_MYSQL"

# Sidebar: Choose Database Option
radio_opt = ["Use SQLite 3 Database - Student.db", "Connect to MySQL Database"]
selected_opt = st.sidebar.radio(label="Choose the DB you want to chat with", options=radio_opt)

# Database Credentials for MySQL (if selected)
if radio_opt.index(selected_opt) == 1:
    db_uri = MYSQL
    mysql_host = st.sidebar.text_input("MySQL Host")
    mysql_user = st.sidebar.text_input("MySQL User")
    mysql_password = st.sidebar.text_input("MySQL Password", type="password")
    mysql_db = st.sidebar.text_input("MySQL Database Name")
else:
    db_uri = LOCALDB

# Sidebar: API Key Input
api_key = st.sidebar.text_input(label="GRoq API Key", type="password")

# Validate Input: API Key and Database Info
if not db_uri:
    st.info("Please select a database option to proceed.")
    st.stop()

if not api_key:
    st.info("Please provide the GRoq API key to proceed.")
    st.stop()

# Define and configure the LLM Model
llm = ChatGroq(groq_api_key=api_key, model_name="Llama3-8b-8192", streaming=True)

# Function to Configure Database Connection with Connection Retry Logic
@st.cache_resource(ttl="2h")
def configure_db(db_uri, mysql_host=None, mysql_user=None, mysql_password=None, mysql_db=None):
    if db_uri == LOCALDB:
        dbfilepath = (Path(__file__).parent / "student.db").absolute()
        creator = lambda: sqlite3.connect(f"file:{dbfilepath}?mode=ro", uri=True)
        engine = create_engine("sqlite:///", creator=creator)
        return engine

    elif db_uri == MYSQL:
        if not (mysql_host and mysql_user and mysql_password and mysql_db):
            st.error("Please provide all MySQL connection details.")
            st.stop()

        encoded_password = quote_plus(mysql_password)  # URL-encode the password
        engine = create_engine(f"mysql+mysqlconnector://{mysql_user}:{encoded_password}@{mysql_host}/{mysql_db}")

        # Event listener for MySQL connection retry on failure
        @event.listens_for(engine, "engine_connect")
        def ping_connection(connection, branch):
            if branch:
                return  # Do not ping for branched connections

            try:
                # Run a simple SELECT 1 to check the connection
                connection.scalar(select(1))
            except exc.DBAPIError as err:
                if err.connection_invalidated:
                    # If connection is invalidated, try to revalidate by running the query again
                    connection.scalar(select(1))
                else:
                    raise

        return engine

# Initialize Database based on user selection
if db_uri == MYSQL:
    db_engine = configure_db(db_uri, mysql_host, mysql_user, mysql_password, mysql_db)
else:
    db_engine = configure_db(db_uri)

# Toolkit for interacting with the database
db = SQLDatabase(db_engine)
toolkit = SQLDatabaseToolkit(db=db, llm=llm)

# Create an agent that can run SQL queries based on LLM responses
agent = create_sql_agent(
    llm=llm,
    toolkit=toolkit,
    verbose=True,
    agent_type=AgentType.ZERO_SHOT_REACT_DESCRIPTION
)

# Manage Chat History and Display Messages
if "messages" not in st.session_state or st.sidebar.button("Clear message history"):
    st.session_state["messages"] = [{"role": "assistant", "content": "How can I help you?"}]

# Display messages from session history
for msg in st.session_state.messages:
    st.chat_message(msg["role"]).write(msg["content"])

# Input: User's Chat Query
user_query = st.chat_input(placeholder="Ask anything from the database")

# Process the User Query and Generate Response
if user_query:
    st.session_state.messages.append({"role": "user", "content": user_query})
    st.chat_message("user").write(user_query)

    with st.chat_message("assistant"):
        # Streamlit callback handler for LLM response streaming
        streamlit_callback = StreamlitCallbackHandler(st.container())

        try:
            # Run the agent to get a response based on the user's query
            response = agent.run(user_query, callbacks=[streamlit_callback])

            # Handle the case where response is not a single key/value output
            if isinstance(response, dict):
                response = response.get("output", "No valid response")

            st.session_state.messages.append({"role": "assistant", "content": response})
            st.write(response)
        except Exception as e:
            st.error(f"An error occurred: {str(e)}")
