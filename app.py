#!/usr/bin/env python3
"""
Streamlit Quiz Game GUI

This Streamlit application provides a graphical user interface for the TCP‑based
quiz game. It connects to the TCP quiz server and provides an interactive
web‑based interface for participating in multiplayer quiz games.

Features:
  - User registration and connection to the TCP server
  - Real‑time question display with countdown timer
  - Interactive answer buttons
  - Live leaderboard updates (including multi‑line messages)
  - Score tracking and feedback
  - Responsive web interface

This version fixes several issues reported by users:

  * Messages sent to the server are now newline‑terminated using ``\n``, which
    matches the server's parsing expectations and prevents registration timeouts.
  * The timer display under each question is driven off the question start
    timestamp and time limit, so it consistently counts down during each
    question without relying on stale session variables.
  * Answer submissions are converted to uppercase before sending to the server
    to avoid mismatches if the server expects capital letters.
  * Leaderboard messages that arrive over multiple lines are assembled
    correctly. A new leaderboard is started whenever a header line (starting
    with 📊 or 🏆) is received, and rank lines are collected until another
    header appears.

Author: Updated for Lab 4 (2025‑11‑01)
"""

from __future__ import annotations

import socket
import threading
import time
import queue
from datetime import datetime
from typing import Dict, List, Optional

import streamlit as st


def _init_session_state() -> None:
    """Initialize the quiz_state dict in Streamlit session_state if missing."""
    if 'quiz_state' not in st.session_state:
        st.session_state.quiz_state = {
            'connected': False,
            'username': None,
            'current_question': None,
            'question_start_time': 0.0,
            'question_time_limit': 0,
            'score': 0,
            'leaderboard': [],
            'messages': [],
            'game_active': False,
            # Flag indicating whether the current user has already
            # submitted an answer to the active question. This can be
            # used to disable answer buttons until the next question.
            'answered_current': False,
        }


class StreamlitQuizClient:
    """TCP quiz client that integrates with Streamlit session state."""

    def __init__(self) -> None:
        # Underlying socket and connection state
        self.socket: Optional[socket.socket] = None
        self.connected: bool = False
        self.username: Optional[str] = None

        # Threading constructs
        self._message_queue: queue.Queue[str] = queue.Queue()
        self._receive_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

        # Buffer used to assemble leaderboards across multiple lines
        self._current_leaderboard: List[Dict[str, int]] = []

        # Ensure session state is initialized
        _init_session_state()

    # ------------------------------------------------------------------
    # Connection methods
    # ------------------------------------------------------------------
    def connect_to_server(self, host: str, port: int) -> bool:
        """Attempt to connect to the TCP quiz server.

        Returns True if connected, False otherwise.
        """
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(10.0)
            sock.connect((host, port))
            self.socket = sock
            self.connected = True

            # Start background thread to receive messages
            self._receive_thread = threading.Thread(target=self._receive_loop, daemon=True)
            self._receive_thread.start()

            st.session_state.quiz_state['connected'] = True
            return True
        except Exception as e:
            st.error(f"Failed to connect to server: {e}")
            return False

    def register_username(self, username: str) -> bool:
        """Send a join message and wait for welcome or error response.

        On success, stores the username into session_state. Pending messages
        unrelated to registration are buffered and requeued.
        """
        try:
            self._send_raw(f"join:{username}")
            start_time = time.time()
            pending: List[str] = []
            while time.time() - start_time < 5:
                if not self._message_queue.empty():
                    msg = self._message_queue.get_nowait().strip()
                    if msg.startswith('welcome:'):
                        self.username = username
                        st.session_state.quiz_state['username'] = username
                        # requeue any pending messages
                        for other in pending:
                            self._message_queue.put(other)
                        return True
                    if msg.startswith('error:'):
                        for other in pending:
                            self._message_queue.put(other)
                        st.error(f"Registration failed: {msg.split(':',1)[1]}")
                        return False
                    # else store pending
                    pending.append(msg)
                else:
                    time.sleep(0.05)
            # timeout
            for other in pending:
                self._message_queue.put(other)
            st.error("Registration timeout")
            return False
        except Exception as e:
            st.error(f"Registration error: {e}")
            return False

    def disconnect(self) -> None:
        """Disconnect from the server and cleanup resources."""
        self._stop_event.set()
        if self.socket:
            try:
                self.socket.close()
            except Exception:
                pass
        self.connected = False
        st.session_state.quiz_state['connected'] = False

    # ------------------------------------------------------------------
    # Sending and receiving
    # ------------------------------------------------------------------
    def _send_raw(self, message: str) -> None:
        """Send a raw message terminated by newline to the server."""
        if not self.socket or not self.connected:
            return
        try:
            self.socket.sendall((message + '\n').encode('utf-8'))
        except Exception as e:
            st.error(f"Error sending message: {e}")
            self.connected = False

    def send_answer(self, answer: str) -> None:
        """Submit an answer to the current question.

        The answer is converted to uppercase before sending to the server.

        Note: we intentionally do not clear the current question or reset
        the timer here. Doing so caused the UI to stop updating the
        countdown on subsequent questions and to prematurely hide the
        question. Instead we allow the server to control when the
        question ends (via "Time's up!" or a new question). This
        preserves the timer display for all players until the server
        broadcasts the next event.
        """
        # If there is no active question, nothing to answer
        if st.session_state.quiz_state['current_question'] is None:
            st.error("No active question to answer")
            return
        # Normalize answer to lowercase before sending. The server
        # converts incoming answers to lowercase before comparison, so
        # lowercase submissions avoid any casing mismatches.
        self._send_raw(f"answer:{answer.lower()}")
        # Record that the user has submitted an answer by storing a flag
        # in the session state. This flag could be used to disable
        # buttons in the future if desired. We do not clear the
        # current_question or timer here; the server will indicate
        # completion via a new question or a "Time's up!" message.
        st.session_state.quiz_state['answered_current'] = True

    def _receive_loop(self) -> None:
        """Background loop that reads data from the socket and queues complete lines."""
        buffer = ''
        sock = self.socket
        while not self._stop_event.is_set() and self.connected:
            try:
                sock.settimeout(1.0)
                data = sock.recv(1024)
                if not data:
                    self.connected = False
                    break
                buffer += data.decode('utf-8')
                while '\n' in buffer:
                    line, buffer = buffer.split('\n', 1)
                    if line:
                        self._message_queue.put(line)
            except socket.timeout:
                continue
            except Exception:
                self.connected = False
                break

    def process_messages(self) -> None:
        """Process all pending messages from the server."""
        while not self._message_queue.empty():
            msg = self._message_queue.get_nowait()
            self._handle_message(msg)

    def _handle_message(self, message: str) -> None:
        """Dispatch a message based on its prefix and update UI state."""
        # Strip leading/trailing whitespace which can break prefix detection
        message = message.strip()
        # Add to recent messages log
        st.session_state.quiz_state['messages'].append({
            'timestamp': datetime.now(),
            'message': message,
        })
        # Retain only last 10 messages
        if len(st.session_state.quiz_state['messages']) > 10:
            st.session_state.quiz_state['messages'] = st.session_state.quiz_state['messages'][-10:]

        # Leaderboard header (start collecting new leaderboard entries)
        if message.startswith('📊') or message.startswith('🏆'):
            # When a new leaderboard header arrives, clear any existing
            # entries and wait for rank lines to follow.
            self._current_leaderboard.clear()
            return

        # Leaderboard lines begin with a rank number followed by a period.
        # Some servers may include emojis or whitespace before the number, so
        # strip known prefix characters before testing for a digit.
        msg_no_prefix = message.lstrip('📊🏆 ').lstrip()
        if msg_no_prefix and msg_no_prefix[0].isdigit() and '. ' in msg_no_prefix:
            rank_str, rest = msg_no_prefix.split('. ', 1)
            try:
                rank = int(rank_str)
            except ValueError:
                rank = None
            if rank is not None:
                # Split the remainder into name and score separated by ': '
                name_part, score_part = rest.split(': ', 1)
                name = name_part.strip()
                try:
                    score = int(score_part.split()[0])
                except ValueError:
                    score = 0
                self._current_leaderboard.append({'rank': rank, 'name': name, 'score': score})
                # Update leaderboard display for the user
                st.session_state.quiz_state['leaderboard'] = list(self._current_leaderboard)
            return

        # Error messages
        if message.startswith('error:'):
            st.error(message.split(':', 1)[1])
            return

        # Correct answer message
        if message.startswith('correct:'):
            # award points; message contains e.g. "10 points" or similar
            info = message.split(':', 1)[1]
            st.success(f"Correct! {info}")
            st.session_state.quiz_state['score'] += 10
            return

        # Incorrect answer message
        if message.startswith('incorrect:'):
            explanation = message.split(':', 1)[1]
            st.error(f"Incorrect. {explanation}")
            return

        # Score update broadcast
        if message.startswith('Score update:'):
            parts = message.split(':')
            if len(parts) >= 4:
                user = parts[1]
                try:
                    score_val = int(parts[3].split()[0])
                except ValueError:
                    score_val = 0
                if user == st.session_state.quiz_state['username']:
                    st.session_state.quiz_state['score'] = score_val
            return

        # New question (pipe‑delimited string)
        if 'Time limit:' in message or message.startswith('Question'):
            self._parse_question(message)
            return

        # Time's up message
        if message.startswith("Time's up!"):
            st.session_state.quiz_state['current_question'] = None
            st.session_state.quiz_state['question_start_time'] = 0.0
            st.session_state.quiz_state['question_time_limit'] = 0
            # Reset answered flag on time up
            st.session_state.quiz_state['answered_current'] = False
            return

        # Game start/complete messages
        if message.startswith('Game starting!'):
            st.session_state.quiz_state['game_active'] = True
            st.success("Game starting! Get ready!")
            return
        if message.startswith('Quiz completed!'):
            st.session_state.quiz_state['game_active'] = False
            st.info("Quiz completed!")
            return

        # Game over message (e.g., new client joined after game ended)
        if message.startswith('Game over!'):
            # No more questions will be sent; set game inactive
            st.session_state.quiz_state['game_active'] = False
            st.info(message)
            return

    # ------------------------------------------------------------------
    # Message parsing helpers
    # ------------------------------------------------------------------
    def _parse_question(self, message: str) -> None:
        """Parse a single‑line, pipe‑delimited question into session state."""
        parts = [p.strip() for p in message.split('|')]
        if not parts:
            return
        text = parts[0]
        options: Dict[str, str] = {}
        time_limit = 30
        # Expect next four parts to be options like "a) Option text"
        for segment in parts[1:5]:
            if ') ' in segment:
                letter, option_text = segment.split(') ', 1)
                letter = letter.strip().lower()
                options[letter] = option_text.strip()
        # Time limit segment
        for segment in parts:
            if segment.lower().startswith('time limit'):
                try:
                    time_limit = int(segment.split(':')[1].split()[0])
                except Exception:
                    time_limit = 30
                break

        st.session_state.quiz_state['current_question'] = {
            'text': text,
            'options': options,
            'time_limit': time_limit,
        }
        # Store start time and limit for the timer/progress bar
        st.session_state.quiz_state['question_start_time'] = time.time()
        st.session_state.quiz_state['question_time_limit'] = time_limit
        # Reset answered flag for the new question
        st.session_state.quiz_state['answered_current'] = False


def _render_connection_settings(client: StreamlitQuizClient) -> None:
    """Render the sidebar connection panel."""
    st.header("🔧 Connection Settings")
    if not st.session_state.quiz_state['connected']:
        host = st.text_input("Server Host", value="localhost", help="Enter the server IP address")
        port = st.number_input("Server Port", value=8888, min_value=1, max_value=65535, step=1)
        if st.button("Connect to Server", type="primary"):
            with st.spinner("Connecting to server..."):
                if client.connect_to_server(host, int(port)):
                    st.success("Connected to server!")
                    st.rerun()
                else:
                    st.error("Failed to connect to server")
    else:
        st.success("✅ Connected to server")
        if st.button("Disconnect", type="secondary"):
            client.disconnect()
            st.rerun()


def _render_registration(client: StreamlitQuizClient) -> None:
    """Render the user registration form."""
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


def _render_game_interface(client: StreamlitQuizClient) -> None:
    """Render the main game interface once the user is registered."""
    col1, col2 = st.columns([2, 1])
    with col1:
        st.header(f"🎮 Welcome, {st.session_state.quiz_state['username']}!")
        # Display current question
        current = st.session_state.quiz_state['current_question']
        if current:
            st.subheader("📝 Current Question")
            st.write(current['text'])
            # Answer buttons
            a_col, b_col = st.columns(2)
            c_col, d_col = st.columns(2)
            # Disable buttons if the user already answered the current question
            answered = st.session_state.quiz_state.get('answered_current', False)
            if a_col.button("A", key="answer_a", use_container_width=True, disabled=answered):
                client.send_answer('a')
            if b_col.button("B", key="answer_b", use_container_width=True, disabled=answered):
                client.send_answer('b')
            if c_col.button("C", key="answer_c", use_container_width=True, disabled=answered):
                client.send_answer('c')
            if d_col.button("D", key="answer_d", use_container_width=True, disabled=answered):
                client.send_answer('d')
            # Display options with labels
            st.markdown("**Options:**")
            for opt_letter, opt_text in current['options'].items():
                st.write(f"**{opt_letter.upper()}**: {opt_text}")
            # Progress bar timer
            start = st.session_state.quiz_state['question_start_time']
            limit = st.session_state.quiz_state['question_time_limit']
            if limit > 0 and start > 0:
                elapsed = int(time.time() - start)
                remaining = max(0, limit - elapsed)
                progress = remaining / limit if limit > 0 else 0.0
                st.progress(progress)
                st.write(f"⏰ Time remaining: {remaining} seconds")
        else:
            # No current question
            if st.session_state.quiz_state['game_active']:
                st.info("Waiting for the next question...")
            else:
                st.info("Game not active. Waiting for other players...")

    with col2:
        st.header("📊 Your Score")
        st.metric("Points", st.session_state.quiz_state['score'])
        # Leaderboard top entries
        if st.session_state.quiz_state['leaderboard']:
            st.header("🏆 Leaderboard")
            for entry in st.session_state.quiz_state['leaderboard'][:5]:
                if entry['name'] == st.session_state.quiz_state['username']:
                    st.write(f"**{entry['rank']}. {entry['name']}: {entry['score']} points** ⭐")
                else:
                    st.write(f"{entry['rank']}. {entry['name']}: {entry['score']} points")
        # Recent messages
        if st.session_state.quiz_state['messages']:
            st.header("📢 Recent Messages")
            for msg in st.session_state.quiz_state['messages'][-5:]:
                ts = msg['timestamp'].strftime("%H:%M:%S")
                st.write(f"**{ts}**: {msg['message']}")


def main() -> None:
    """Entry point for the Streamlit application."""
    st.title("🧠 Multiplayer Quiz Game")
    st.markdown("---")

    # Ensure session state is ready
    _init_session_state()
    # Retrieve or create a client instance
    if 'quiz_client' not in st.session_state:
        st.session_state.quiz_client = StreamlitQuizClient()
    client: StreamlitQuizClient = st.session_state.quiz_client

    # Render sidebar connection controls
    with st.sidebar:
        _render_connection_settings(client)

    # Process any incoming messages before rendering UI
    if st.session_state.quiz_state['connected']:
        client.process_messages()

    # If not connected, show instructions
    if not st.session_state.quiz_state['connected']:
        st.info("Please connect to a server using the sidebar to start playing.")
        st.markdown("### How to Connect:")
        st.markdown(
            "1. Make sure the TCP quiz server is running\n"
            "2. Enter the server host (localhost for local server)\n"
            "3. Enter the server port (default: 8888)\n"
            "4. Click \"Connect to Server\""
        )
        st.markdown("### To Start the Server:")
        st.code(
            """
            # Navigate to the project directory
            cd quiznet-tcp-udp

            # Start the TCP server
            python tcp_quiz/server_tcp.py
            """,
            language="bash",
        )
        return

    # If connected but username not set, show registration
    if st.session_state.quiz_state['username'] is None:
        _render_registration(client)
        return

    # Otherwise, show the game interface
    _render_game_interface(client)

    # Auto‑refresh when a question is active
    if (
        st.session_state.quiz_state['current_question'] is not None
        and st.session_state.quiz_state['connected']
    ):
        # Sleep briefly and then rerun to update timer and UI
        time.sleep(1)
        st.rerun()


if __name__ == "__main__":
    main()