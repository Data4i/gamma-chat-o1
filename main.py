import streamlit as st
import uuid
import groq
from langchain_groq import ChatGroq
from langchain.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.messages import SystemMessage, trim_messages
from langchain.schema import SystemMessage
from langgraph.graph import StateGraph, START
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph.message import add_messages
from streamlit_float import *
from streamlit_chat_widget import chat_input_widget
from typing_extensions import Annotated, TypedDict
from typing import Sequence
from datetime import datetime


from pymongo import DESCENDING
from models import UserSchema, MessageSchema, TitleSchema
from dbase import users_collection, messages_collection, titles_collection

# Initialize API Key
GROQ_API_KEY = st.secrets['GROQ_API_KEY']
client = groq.Client(api_key=GROQ_API_KEY)
OPENAI_API_KEY = st.secrets['OPENAI_API_KEY']


# Database Functions
def add_user(username, email):
    user = UserSchema(username=username, email=email)
    users_collection.insert_one(user.dict())


def save_message(user_id, session_id, message, response):
    chat_entry = MessageSchema(user_id=user_id, session_id=session_id, message=message, response=response)
    messages_collection.insert_one(chat_entry.dict())


def get_messages(user_id):
    # Fetch messages for a specific session
    messages = messages_collection.find( {"user_id": user_id }).sort("timestamp", DESCENDING)

    # Convert the cursor to a list of messages
    return list(messages)

def save_session_title(user_id, session_id, title):
    title = TitleSchema(user_id=user_id, session_id=session_id, title=title)
    titles_collection.insert_one(title.dict())

def fetch_session_titles(user_id):

    # Fetch session titles sorted by timestamp in descending order (most recent first)
    session_titles = titles_collection.find(
        {"user_id": user_id}
    ).sort("timestamp", DESCENDING)  # Ensure sorting is done at the database level

    return [session["title"] for session in session_titles]  # Extract only the titles

#Session title generation
def generate_session_title(conversation_text, modelName):
    """
    Uses Groq's LLM API to generate a session title from conversation history.
    """
    prompt = f"Summarize this conversation into a short and meaningful title:\n\n{conversation_text}"

    try:
        response = client.chat.completions.create(
            model=modelName,  # You can switch to "llama3-70b" if needed
            messages=[{"role": "system", "content": prompt}],
            temperature=0.4,
            max_tokens=20  # Limit the response length for a short title
        )
        return response.choices[0].message.content.strip()  # Extract and clean up title
    except Exception as e:
        st.error(f"Error generating title: {str(e)}")
        return "Untitled Conversation"












# Set up Streamlit app
st.set_page_config(page_title="Gamma-o1-chatBot", page_icon="🤖")
float_init()
st.title("Gamma-o1-chatBot")

# Initialize session state
if "user_id" not in st.session_state:
    st.session_state["user_id"] = ""
if "messages" not in st.session_state:
    st.session_state["messages"] = []
if 'memory' not in st.session_state:
    st.session_state.memory = MemorySaver()

# LangGraph's Checkpointer requires a unique thread_id to manage conversation history properly.
if "thread_id" not in st.session_state:
    st.session_state.thread_id = str(uuid.uuid4())  # Generates a unique session ID

config = {"configurable": {"thread_id": st.session_state.thread_id}}

# User authentication
if not st.session_state["user_id"]:
    username = st.text_input("Enter your username to start:")
    if username:
        # Check if user exists in the database
        user = users_collection.find_one({"username": username})
        if not user:
            # Add user to the database if not found
            add_user(username, f"{username}@email.com")  # A dummy email to simulate its existence
        st.session_state["user_id"] = username
        st.rerun()

# Proceed only if user_id is set
if st.session_state.get("user_id"):
    st.write(f"Welcome, **{st.session_state['user_id']}**!")

    # AI Model Selection
    MODEL_OPTIONS = {
        "Mixtral (Fast & Efficient)": "mixtral-8x7b-32768",
        "Llama-3 (More Detailed)": "llama-3.3-70b-specdec"
    }
    selected_model = st.sidebar.radio("Choose AI Model:", list(MODEL_OPTIONS.keys()))
    model_name = MODEL_OPTIONS[selected_model]

    groq_llm = ChatGroq(api_key=GROQ_API_KEY, model=model_name, temperature=0.4, max_retries=2)

    # AI Character Selection
    CHARACTERS = {
        "Professor AI": (
            "You are an esteemed professor with deep knowledge across various disciplines. "
            "You explain complex concepts in a clear, engaging way, using historical context, "
            "examples, and structured reasoning to guide your students."
        ),
        "Comedian Bot": (
            "You are a hilarious AI comedian who sees humor in everything. "
            "You turn even the most serious conversations into lighthearted moments, using witty remarks, puns, and jokes."
        ),
        "Motivator AI": (
            "You are a high-energy motivational speaker, always uplifting and encouraging. "
            "You inspire people to chase their dreams, overcome adversity, and unlock their full potential "
            "with powerful words and actionable advice."
        ),
        "Detective Noir": (
            "You are a 1940s-style detective, full of grit and street smarts. "
            "You speak in a noir film style, piecing together clues with dramatic flair, "
            "always looking for the next big case in the shadows of the city."
        ),
        "Culinary Maestro": (
            "You are a world-renowned chef with expertise in fine dining, exotic cuisines, and culinary science. "
            "You give detailed cooking instructions, ingredient recommendations, and pro tips for gourmet meals."
        ),
        "Custom Character": None
    }
    selected_character = st.sidebar.selectbox("Choose an AI Character:", list(CHARACTERS.keys()))

    if selected_character == "Custom Character":
        custom_character = st.sidebar.text_input("Enter Character Name:")
        custom_description = st.sidebar.text_area("Enter Character Description:")

        if custom_character and custom_description:
            selected_character = custom_character
            CHARACTERS[custom_character] = custom_description  # Store the custom description

    # Store selected character in session and update system message
    if "character" not in st.session_state or st.session_state["character"] != selected_character:
        st.session_state["character"] = selected_character
        st.session_state["messages"] = []  # Reset chat history



    # Sidebar for chat history
    st.sidebar.header("Chat History")

    # Show clickable titles in the sidebar
    titles = fetch_session_titles(st.session_state["user_id"])

    # Add a placeholder for explicit selection
    titles.insert(0, "Select a convo...")

    clicked_title = st.sidebar.selectbox("Past conversations:", titles, index=0)

    if clicked_title != "Select a convo...":
        # Retrieve the session data by title or session_id and display the full conversation
        session_data = titles_collection.find_one({"user_id": st.session_state["user_id"], "title": clicked_title})
        full_conversation = messages_collection.find({"session_id": session_data["session_id"]}).sort("timestamp", DESCENDING)
        
        # Reset chat and display full conversation
        st.session_state['messages'] = []
        
        for message in full_conversation:
            st.chat_message('user').markdown(message['message'])
            st.chat_message('assistant').markdown(message['response'])
            

    # Define LangGraph Workflow
    class State(TypedDict):
        messages: Annotated[Sequence[SystemMessage], add_messages]
        character: str

    def call_model(state: State):
        # trim the messages that are stored as memory     
        trimmed_messages = trim_messages(
            messages = state['messages'],
            max_tokens=100,
            strategy='last',
            token_counter= groq_llm,
            include_system=True,
            allow_partial=False,
            start_on='human',
        )
        
        prompt_template = ChatPromptTemplate.from_messages([
            SystemMessage(content=f"You are {state['character']}. Stay fully in character at all times and respond exactly as {state['character']} would. Answer all questions directly, without internal thoughts, explanations, or reasoning—just pure, in-character responses."),
            MessagesPlaceholder(variable_name='messages')
        ])
        
        prompt = prompt_template.invoke({
            'messages': trimmed_messages,
            'character': state['character']
        })

        response = groq_llm.invoke(prompt)
        return {'messages': [response]}
    
    workflow = StateGraph(state_schema=State)
    workflow.add_edge(START, "model")
    workflow.add_node("model", call_model)

    memory = st.session_state.memory

    app = workflow.compile(checkpointer=memory)
    
    # getting the user query
    def transcribe_audio(audio_file):
        with open(audio_file, "rb") as file:
            response = client.audio.transcriptions.create(
                model="whisper-large-v3-turbo",
                file=file
            )
        return response.text

    for message in st.session_state.messages:
        st.chat_message(message['role']).markdown(message['content'])

    # Chat Input
    chat_placeholder = st.container()
    with chat_placeholder:
        user_input = chat_input_widget()
        query = ""
        if user_input:
            if 'text' in user_input:
                query = user_input['text']
            elif 'audioFile' in user_input:
                with open("temp_audio.wav", "wb") as f:
                    f.write(bytes(user_input["audioFile"]))
                query = transcribe_audio("temp_audio.wav")
    chat_placeholder.float(
        "display:flex; align-items:center;justify-content:center; overflow:hidden visible;flex-direction:column; position:fixed;bottom:15px;"
    )

    # Process User Input
    if query:
        st.session_state.messages.append({'role': 'user', 'content': query})
        st.chat_message('user').markdown(query)

        #process model output
        output = app.invoke(input={
            'messages': st.session_state.messages,
            'character': selected_character,
        }, config=config)

        current_output = output['messages'][-1].content if output['messages'] else None
            
        if current_output:
            st.session_state.messages.append({'role': 'assistant', 'content': current_output})
            st.chat_message('assistant').markdown(current_output)

            # Save user message to the database
            user_id = st.session_state["user_id"]
            session_id = st.session_state["thread_id"]  # Unique session ID
            save_message(user_id, session_id, query, current_output)  # Store user message 

            # After at least 2 exchanges (2 turns: 1 user + 1 assistant), generate a title
            if len(st.session_state.messages) == 2 and 'session_title' not in st.session_state:
                session_title = generate_session_title(st.session_state.messages, model_name)
                st.session_state['session_title'] = session_title
                save_session_title(st.session_state["user_id"], st.session_state["thread_id"], session_title)
        else:
            st.error('Something went wrong! Please try again.')
