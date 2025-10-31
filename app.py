#!/usr/bin/env python3
"""
Streamlit Quiz Game GUI

This Streamlit application provides a graphical user interface for the TCP-based
quiz game. It connects to the TCP quiz server and provides an interactive
web-based interface for participating in multiplayer quiz games.

Features:
- User registration and connection to TCP server
- Real-time question display with countdown timer
- Interactive answer buttons
- Live leaderboard updates
- Score tracking and feedback
- Responsive web interface

Author: CS411 Lab 4 Implementation
"""

import streamlit as st
import socket
import threading
import time
import json
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
import queue

# Configure Streamlit page
st.set_page_config(
    page_title="Quiz Game",
    page_icon="🧠",
    layout="wide",
    initial_sidebar_state="expanded"
)

class StreamlitQuizClient:
    """
    Streamlit-based quiz client that connects to the TCP server.
    
    This class handles:
    - TCP connection to the quiz server
    - Message processing and state management
    - Streamlit session state integration
    - Real-time UI updates
    """
    
    def __init__(self):
        """Initialize the Streamlit quiz client."""
        self.socket = None
        self.connected = False
        self.username = None
        self.message_queue = queue.Queue()
        self.receive_thread = None
        self.stop_event = threading.Event()
        
        # Initialize session state
        if 'quiz_state' not in st.session_state:
            st.session_state.quiz_state = {
                'connected': False,
                'username': None,
                'current_question': None,
                'question_timer': 0,
                'question_start_time': 0,
                'score': 0,
                'leaderboard': [],
                'messages': [],
                'game_active': False
            }
    
    def connect_to_server(self, host: str, port: int) -> bool:
        """
        Connect to the TCP quiz server.
        
        Args:
            host: Server host address
            port: Server port number
            
        Returns:
            bool: True if connection successful, False otherwise
        """
        try:
            # Create TCP socket
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.socket.settimeout(10.0)
            
            # Connect to server
            self.socket.connect((host, port))
            self.connected = True
            
            # Start receiving thread
            self.receive_thread = threading.Thread(target=self.receive_loop, daemon=True)
            self.receive_thread.start()
            
            # Update session state
            st.session_state.quiz_state['connected'] = True
            
            return True
            
        except Exception as e:
            st.error(f"Failed to connect to server: {e}")
            return False
    
    def register_username(self, username: str) -> bool:
        """
        Register username with the server.
        
        Args:
            username: Username to register
            
        Returns:
            bool: True if registration successful, False otherwise
        """
        try:
            self.send_message(f'join:{username}')
            
            # Wait for response
            start_time = time.time()
            while time.time() - start_time < 5:  # 5-second timeout
                try:
                    if not self.message_queue.empty():
                        message = self.message_queue.get_nowait()
                        if message.startswith('welcome:'):
                            self.username = username
                            st.session_state.quiz_state['username'] = username
                            return True
                        elif message.startswith('error:'):
                            error_msg = message.split(':', 1)[1]
                            st.error(f"Registration failed: {error_msg}")
                            return False
                except queue.Empty:
                    time.sleep(0.1)
            
            st.error("Registration timeout")
            return False
            
        except Exception as e:
            st.error(f"Registration error: {e}")
            return False
    
    def send_message(self, message: str) -> None:
        """
        Send a message to the server.
        
        Args:
            message: Message to send
        """
        try:
            if self.socket and self.connected:
                data = message.encode('utf-8')
                self.socket.send(data)
        except Exception as e:
            st.error(f"Error sending message: {e}")
            self.connected = False
    
    def receive_loop(self) -> None:
        """
        Background loop for receiving messages from server.
        """
        while not self.stop_event.is_set() and self.connected:
            try:
                self.socket.settimeout(1.0)
                data = self.socket.recv(1024)
                
                if not data:
                    self.connected = False
                    break
                
                message = data.decode('utf-8')
                self.message_queue.put(message)
                
            except socket.timeout:
                continue
            except Exception as e:
                if not self.stop_event.is_set():
                    self.connected = False
                break
    
    def process_messages(self) -> None:
        """
        Process messages from the server queue.
        """
        while not self.message_queue.empty():
            try:
                message = self.message_queue.get_nowait()
                self.handle_server_message(message)
            except queue.Empty:
                break
    
    def handle_server_message(self, message: str) -> None:
        """
        Handle incoming messages from the server.
        
        Args:
            message: Message received from server
        """
        try:
            # Add message to session state for display
            st.session_state.quiz_state['messages'].append({
                'timestamp': datetime.now(),
                'message': message
            })
            
            # Keep only last 10 messages
            if len(st.session_state.quiz_state['messages']) > 10:
                st.session_state.quiz_state['messages'] = st.session_state.quiz_state['messages'][-10:]
            
            # Handle different message types
            if message.startswith('error:'):
                error_msg = message.split(':', 1)[1]
                st.error(f"Server error: {error_msg}")
                
            elif message.startswith('correct:'):
                points = message.split(':', 1)[1]
                st.success(f"Correct! {points}")
                st.session_state.quiz_state['score'] += 10
                
            elif message.startswith('incorrect:'):
                correct_answer = message.split(':', 1)[1]
                st.error(f"Incorrect. {correct_answer}")
                
            elif message.startswith('Score update:'):
                # Extract score from message
                parts = message.split(':')
                if len(parts) >= 4:
                    username = parts[1]
                    score = int(parts[3].split()[0])
                    if username == st.session_state.quiz_state['username']:
                        st.session_state.quiz_state['score'] = score
                
            elif message.startswith('📊') or message.startswith('🏆'):
                # Leaderboard update
                self.parse_leaderboard(message)
                
            elif message.startswith('Question') or 'Time limit:' in message:
                # Quiz question
                self.parse_question(message)
                
            elif message.startswith("Time's up!"):
                st.session_state.quiz_state['current_question'] = None
                st.session_state.quiz_state['question_timer'] = 0
                
            elif message.startswith('Game starting!'):
                st.session_state.quiz_state['game_active'] = True
                st.success("Game starting! Get ready!")
                
            elif message.startswith('Quiz completed!'):
                st.session_state.quiz_state['game_active'] = False
                st.info("Quiz completed!")
                
        except Exception as e:
            st.error(f"Error handling message: {e}")
    
    def parse_question(self, question_text: str) -> None:
        """
        Parse and store quiz question information.
        
        Args:
            question_text: Formatted question text from server
        """
        try:
            lines = question_text.split('\n')
            question_data = {
                'text': lines[0],
                'options': {},
                'time_limit': 30
            }
            
            # Parse options
            for line in lines[1:]:
                if ':' in line and not line.startswith('Time limit'):
                    option_letter = line[0]
                    option_text = line[3:]  # Remove "a) " prefix
                    question_data['options'][option_letter] = option_text
                elif 'Time limit:' in line:
                    time_limit = int(line.split(':')[1].split()[0])
                    question_data['time_limit'] = time_limit
            
            st.session_state.quiz_state['current_question'] = question_data
            st.session_state.quiz_state['question_start_time'] = time.time()
            st.session_state.quiz_state['question_timer'] = time_limit
            
        except Exception as e:
            st.error(f"Error parsing question: {e}")
    
    def parse_leaderboard(self, leaderboard_text: str) -> None:
        """
        Parse and store leaderboard information.
        
        Args:
            leaderboard_text: Formatted leaderboard text from server
        """
        try:
            lines = leaderboard_text.split('\n')[1:]  # Skip header
            leaderboard = []
            
            for line in lines:
                if line.strip() and '. ' in line:
                    parts = line.split('. ', 1)
                    if len(parts) == 2:
                        rank = int(parts[0])
                        name_score = parts[1].split(': ')
                        if len(name_score) == 2:
                            name = name_score[0]
                            score = int(name_score[1].split()[0])
                            leaderboard.append({
                                'rank': rank,
                                'name': name,
                                'score': score
                            })
            
            st.session_state.quiz_state['leaderboard'] = leaderboard
            
        except Exception as e:
            st.error(f"Error parsing leaderboard: {e}")
    
    def send_answer(self, answer: str) -> None:
        """
        Send an answer to the current question.
        
        Args:
            answer: Answer choice (a, b, c, or d)
        """
        if not st.session_state.quiz_state['current_question']:
            st.error("No active question to answer")
            return
        
        self.send_message(f'answer:{answer}')
        st.session_state.quiz_state['current_question'] = None
        st.session_state.quiz_state['question_timer'] = 0
    
    def disconnect(self) -> None:
        """Disconnect from the server and clean up resources."""
        self.stop_event.set()
        self.connected = False
        
        if self.socket:
            try:
                self.socket.close()
            except:
                pass
        
        st.session_state.quiz_state['connected'] = False

def main():
    """
    Main Streamlit application function.
    """
    st.title("🧠 Multiplayer Quiz Game")
    st.markdown("---")
    
    # Initialize client
    if 'quiz_client' not in st.session_state:
        st.session_state.quiz_client = StreamlitQuizClient()
    
    client = st.session_state.quiz_client
    
    # Sidebar for connection settings
    with st.sidebar:
        st.header("🔧 Connection Settings")
        
        if not st.session_state.quiz_state['connected']:
            server_host = st.text_input("Server Host", value="localhost", help="Enter the server IP address")
            server_port = st.number_input("Server Port", value=8888, min_value=1, max_value=65535)
            
            if st.button("Connect to Server", type="primary"):
                with st.spinner("Connecting to server..."):
                    if client.connect_to_server(server_host, server_port):
                        st.success("Connected to server!")
                        st.rerun()
                    else:
                        st.error("Failed to connect to server")
        
        else:
            st.success("✅ Connected to server")
            
            if st.button("Disconnect", type="secondary"):
                client.disconnect()
                st.rerun()
    
    # Main content area
    if not st.session_state.quiz_state['connected']:
        st.info("Please connect to a server using the sidebar to start playing.")
        
        # Display connection instructions
        st.markdown("### How to Connect:")
        st.markdown("""
        1. Make sure the TCP quiz server is running
        2. Enter the server host (localhost for local server)
        3. Enter the server port (default: 8888)
        4. Click "Connect to Server"
        """)
        
        st.markdown("### To Start the Server:")
        st.code("""
        # Navigate to the project directory
        cd quiznet-tcp-udp
        
        # Start the TCP server
        python tcp_quiz/server_tcp.py
        """, language="bash")
        
    else:
        # Process incoming messages
        client.process_messages()
        
        # Registration section
        if not st.session_state.quiz_state['username']:
            st.header("👤 User Registration")
            username = st.text_input("Enter your username:", max_chars=20)
            
            if st.button("Register", type="primary"):
                if username:
                    with st.spinner("Registering..."):
                        if client.register_username(username):
                            st.success(f"Welcome, {username}!")
                            st.rerun()
                        else:
                            st.error("Registration failed")
                else:
                    st.error("Please enter a username")
        
        else:
            # Main game interface
            col1, col2 = st.columns([2, 1])
            
            with col1:
                st.header(f"🎮 Welcome, {st.session_state.quiz_state['username']}!")
                
                # Current question display
                if st.session_state.quiz_state['current_question']:
                    question_data = st.session_state.quiz_state['current_question']
                    
                    st.subheader("📝 Current Question")
                    st.write(question_data['text'])
                    
                    # Answer buttons
                    col_a, col_b = st.columns(2)
                    col_c, col_d = st.columns(2)
                    
                    with col_a:
                        if st.button("A", key="answer_a", use_container_width=True):
                            client.send_answer('a')
                    
                    with col_b:
                        if st.button("B", key="answer_b", use_container_width=True):
                            client.send_answer('b')
                    
                    with col_c:
                        if st.button("C", key="answer_c", use_container_width=True):
                            client.send_answer('c')
                    
                    with col_d:
                        if st.button("D", key="answer_d", use_container_width=True):
                            client.send_answer('d')
                    
                    # Display options
                    st.markdown("**Options:**")
                    for option, text in question_data['options'].items():
                        st.write(f"**{option.upper()}**: {text}")
                    
                    # Timer display
                    if st.session_state.quiz_state['question_timer'] > 0:
                        elapsed = time.time() - st.session_state.quiz_state['question_start_time']
                        remaining = max(0, st.session_state.quiz_state['question_timer'] - int(elapsed))
                        
                        if remaining > 0:
                            progress = remaining / st.session_state.quiz_state['question_timer']
                            st.progress(progress)
                            st.write(f"⏰ Time remaining: {remaining} seconds")
                        else:
                            st.write("⏰ Time's up!")
                
                else:
                    if st.session_state.quiz_state['game_active']:
                        st.info("Waiting for the next question...")
                    else:
                        st.info("Game not active. Waiting for other players...")
            
            with col2:
                st.header("📊 Your Score")
                st.metric("Points", st.session_state.quiz_state['score'])
                
                # Leaderboard
                if st.session_state.quiz_state['leaderboard']:
                    st.header("🏆 Leaderboard")
                    leaderboard_df = st.session_state.quiz_state['leaderboard']
                    
                    for entry in leaderboard_df[:5]:  # Show top 5
                        if entry['name'] == st.session_state.quiz_state['username']:
                            st.write(f"**{entry['rank']}. {entry['name']}: {entry['score']} points** ⭐")
                        else:
                            st.write(f"{entry['rank']}. {entry['name']}: {entry['score']} points")
                
                # Recent messages
                if st.session_state.quiz_state['messages']:
                    st.header("📢 Recent Messages")
                    for msg in st.session_state.quiz_state['messages'][-5:]:  # Show last 5
                        timestamp = msg['timestamp'].strftime("%H:%M:%S")
                        st.write(f"**{timestamp}**: {msg['message']}")
    
    # Auto-refresh every second to update timer and messages
    if st.session_state.quiz_state['connected'] and st.session_state.quiz_state['current_question']:
        time.sleep(1)
        st.rerun()

if __name__ == "__main__":
    main()
