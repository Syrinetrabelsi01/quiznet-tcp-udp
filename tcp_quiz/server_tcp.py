#!/usr/bin/env python3
"""
TCP Quiz Server Implementation (modified)

This version of the TCP quiz server fixes an issue where quiz questions
were sent as multi‑line messages.  The original implementation joined the
question text and each answer option with newline characters, which caused
clients to split the question into multiple separate messages.  To avoid
this, the server now formats each question and its options as a single
newline‑terminated string using a pipe delimiter (" | ").  Clients can
replace the pipes with newlines when displaying the question, ensuring the
entire question arrives in one piece.

Author: Adapted from CS411 Lab 4 Implementation
"""

import socket
import threading
import time
import json
import logging
from datetime import datetime
from typing import Dict, List, Tuple, Optional

# Configure logging for the server
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('tcp_server.log'),
        logging.StreamHandler()
    ]
)


class TCPQuizServer:
    """
    TCP-based quiz server that manages multiple clients and conducts quiz games.

    This class handles:
    - Client connection management using TCP sockets
    - Multithreaded client handling
    - Question broadcasting with timers
    - Answer processing and scoring
    - Leaderboard maintenance
    - Error handling and logging
    """

    def __init__(self, host: str = '0.0.0.0', port: int = 8888):
        """
        Initialize the TCP quiz server.

        Args:
            host: Server host address (0.0.0.0 for all interfaces)
            port: Server port number (default: 8888)
        """
        self.host = host
        self.port = port
        self.socket = None

        # Game state management
        # Mapping of client threads to their information.  Each client_info
        # dictionary stores the username, score, question index, whether the
        # client has finished the quiz, and the start time of the current
        # question.  We also keep a reference to the client's timer thread
        # (used to cancel timeouts when the client answers early).
        self.clients: Dict[threading.Thread, Dict] = {}
        # Mapping of client threads to their sockets
        self.client_sockets: Dict[threading.Thread, socket.socket] = {}
        # List of all questions loaded from questions.txt
        self.questions: List[Dict] = []
        # Duration in seconds for each question.  Clients must answer within
        # this time; otherwise, they will be notified that time is up and the
        # correct answer will be revealed.  After that, the next question will
        # be sent to the client individually.  Adjust this value to speed up
        # or slow down the quiz.
        self.question_duration = 15

        # Flag indicating whether the quiz has ended.  Once set to True in
        # end_game(), new clients will not receive questions.  The game does
        # not automatically restart.
        self.game_over: bool = False

        # The following fields related to global per-question tracking from the
        # previous implementation are no longer needed.  They are retained
        # for backward compatibility but are unused in the per-client logic.
        self.current_question_index = 0
        self.game_active = False
        self.question_start_time = 0
        self.question_answered_event = threading.Event()
        self.current_question_responders: set = set()

        # Threading and synchronization
        # Use a reentrant lock (RLock) to allow the same thread to re-acquire
        # the lock when methods like handle_client_join invoke other methods
        # that also use this lock (e.g., broadcast_message).  Without RLock,
        # acquiring the lock twice in the same thread would cause a deadlock.
        self.lock = threading.RLock()
        self.broadcast_thread = None
        self.stop_event = threading.Event()

        # Load questions from file
        self.load_questions()

        logging.info(f"TCP Quiz Server initialized on {host}:{port}")

    def load_questions(self) -> None:
        """
        Load quiz questions from questions.txt file.

        Each question is parsed and stored in a structured format with:
        - Question text
        - Multiple choice options (a, b, c, d)
        - Correct answer
        """
        try:
            with open('questions.txt', 'r', encoding='utf-8') as file:
                lines = file.readlines()

            self.questions = []
            for line in lines:
                line = line.strip()
                if not line:
                    continue

                # Parse question format: id:question|a)option1|b)option2|c)option3|d)option4|correct_answer
                parts = line.split('|')
                if len(parts) >= 6:
                    question_id = parts[0].split(':')[0]
                    question_text = parts[0].split(':', 1)[1]

                    options = {}
                    for i in range(1, 5):
                        if i < len(parts):
                            option_text = parts[i]
                            option_letter = option_text[0].lower()  # a, b, c, or d
                            # Remove "a) " prefix and extra whitespace
                            option_body = option_text[2:].lstrip(' )')
                            options[option_letter] = option_body

                    correct_answer = parts[5] if len(parts) > 5 else 'a'

                    self.questions.append({
                        'id': question_id,
                        'text': question_text,
                        'options': options,
                        'correct': correct_answer.lower()
                    })

            logging.info(f"Loaded {len(self.questions)} questions from questions.txt")

        except FileNotFoundError:
            logging.error("questions.txt file not found!")
            # Create sample question if file doesn't exist
            self.questions = [
                {
                    'id': '1',
                    'text': 'What is TCP?',
                    'options': {'a': 'Transmission Control Protocol', 'b': 'Transfer Control Protocol', 'c': 'Transmission Check Protocol', 'd': 'Transfer Check Protocol'},
                    'correct': 'a'
                }
            ]
        except Exception as e:
            logging.error(f"Error loading questions: {e}")
            self.questions = []

    def start_server(self) -> None:
        """
        Start the TCP server and begin accepting client connections.

        This method:
        - Creates and binds the TCP socket
        - Starts the broadcast thread for game management
        - Begins accepting client connections
        """
        try:
            # Create TCP socket
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.socket.bind((self.host, self.port))
            self.socket.listen(10)  # Allow up to 10 pending connections

            logging.info(f"TCP Quiz Server started on {self.host}:{self.port}")
            print(f"TCP Quiz Server running on {self.host}:{self.port}")
            print("Waiting for clients to connect...")

            # Start broadcast thread for game management
            self.broadcast_thread = threading.Thread(target=self.broadcast_loop, daemon=True)
            self.broadcast_thread.start()

            # Main server loop - accept client connections
            while not self.stop_event.is_set():
                try:
                    # Accept client connection
                    client_socket, client_address = self.socket.accept()
                    logging.info(f"New client connected from {client_address}")

                    # Create thread for this client
                    client_thread = threading.Thread(
                        target=self.handle_client,
                        args=(client_socket, client_address),
                        daemon=True
                    )
                    client_thread.start()

                except socket.error as e:
                    if not self.stop_event.is_set():
                        logging.error(f"Socket error: {e}")
                except Exception as e:
                    logging.error(f"Unexpected error in main loop: {e}")

        except Exception as e:
            logging.error(f"Failed to start server: {e}")
            print(f"Error starting server: {e}")
        finally:
            self.stop_server()

    def handle_client(self, client_socket: socket.socket, client_address: Tuple[str, int]) -> None:
        """
        Handle communication with a single client.

        Args:
            client_socket: Socket connected to the client
            client_address: Tuple of (IP, port) of the client
        """
        current_thread = threading.current_thread()
        client_info = None

        # Store the client socket for this thread
        with self.lock:
            self.client_sockets[current_thread] = client_socket

        # Buffer for partial messages
        buffer = b''

        try:
            # Set socket timeout for receiving
            client_socket.settimeout(1.0)

            while not self.stop_event.is_set():
                try:
                    # Receive data from client
                    data = client_socket.recv(1024)
                    if not data:
                        # Client disconnected
                        break

                    # Add to buffer
                    buffer += data

                    # Process complete messages (newline-delimited)
                    while b'\n' in buffer:
                        message_bytes, buffer = buffer.split(b'\n', 1)
                        message = message_bytes.decode('utf-8').strip()

                        if not message:
                            continue

                        logging.info(f"Received from {client_address}: {message}")

                        # Parse message format: command:data
                        if ':' in message:
                            command, data_part = message.split(':', 1)
                            command = command.lower()

                            with self.lock:
                                if command == 'join':
                                    client_info = self.handle_client_join(data_part, client_address, current_thread)
                                elif command == 'answer' and client_info:
                                    self.handle_client_answer(data_part, client_info, current_thread)
                                elif command == 'ping':
                                    self.send_message_to_client('pong', client_socket)
                                else:
                                    logging.warning(f"Unknown command from {client_address}: {command}")
                        else:
                            logging.warning(f"Invalid message format from {client_address}: {message}")

                except socket.timeout:
                    # Timeout is normal, continue listening
                    continue
                except Exception as e:
                    logging.error(f"Error handling message from {client_address}: {e}")
                    break

        except Exception as e:
            logging.error(f"Error in client handler for {client_address}: {e}")
        finally:
            # Clean up client connection
            self.cleanup_client(current_thread, client_socket, client_address)

    def handle_client_join(self, username: str, client_address: Tuple[str, int], client_thread: threading.Thread) -> Optional[Dict]:
        """
        Handle client registration/join request.

        Args:
            username: Username provided by client
            client_address: Client's address tuple
            client_thread: Thread handling this client

        Returns:
            Dict: Client info dictionary if successful, None otherwise
        """
        if not username or len(username.strip()) == 0:
            self.send_message_to_client('error:Invalid username', self.client_sockets[client_thread])
            return None

        username = username.strip()

        # Check if username already exists
        existing_thread = None
        for thread, client_info in self.clients.items():
            if client_info['username'] == username:
                existing_thread = thread
                break

        if existing_thread:
            # Remove old client with same username
            self.cleanup_client(existing_thread, self.client_sockets[existing_thread], client_address)
            logging.info(f"Removed existing client with username '{username}'")

        # Register new client.  Initialize per-client state:
        # - 'question_index' tracks which question the client is currently on.
        # - 'finished' indicates whether the client has completed the quiz.
        # - 'timer_thread' will hold a reference to the per-question timer
        #   thread so that it can be cancelled or ignored when the client
        #   answers early.
        client_info = {
            'username': username,
            'score': 0,
            'last_seen': time.time(),
            'connected': True,
            'address': client_address,
            'question_index': 0,
            'finished': False,
            'timer_thread': None,
            'question_start_time': 0.0
        }

        self.clients[client_thread] = client_info

        logging.info(f"Client {client_address} joined as '{username}'")
        # Send welcome message using the socket
        self.send_message_to_client(f'welcome:{username}', self.client_sockets[client_thread])

        # Broadcast updated player list
        self.broadcast_player_list()

        # If the game is over (all clients finished previously), do not start
        # new quizzes for new clients.  They will join as spectators.
        if self.game_over:
            self.send_message_to_client("Game over! Please wait for the next session.", self.client_sockets[client_thread])
            return client_info

        # Start the first question for this client immediately.  Each client
        # progresses through questions independently of others.
        self.send_question_to_client(client_thread)

        return client_info

    def handle_client_answer(self, answer: str, client_info: Dict, client_thread: threading.Thread) -> None:
        """
        Handle client answer submission.

        Args:
            answer: Answer provided by client (format: "a", "b", "c", or "d")
            client_info: Client information dictionary
            client_thread: Thread handling this client
        """
        # In the per-client model, each client has its own question index and
        # finishes independently.  Ignore answers if the client has finished.
        if client_info.get('finished', False):
            self.send_message_to_client('error:Quiz completed', self.client_sockets[client_thread])
            return

        idx = client_info.get('question_index', 0)
        # Validate question index
        if idx >= len(self.questions):
            # Mark finished and ignore
            client_info['finished'] = True
            if all(ci.get('finished', False) for ci in self.clients.values()):
                self.end_game()
            return

        current_question = self.questions[idx]
        current_time = time.time()
        client_info['last_seen'] = current_time

        # Normalize answer
        answer = answer.strip().lower()
        correct = current_question['correct']

        # Cancel existing timer thread by incrementing the question index after handling
        # (The timer thread will check the question index and exit automatically.)

        if answer == correct:
            # Correct answer - award points
            client_info['score'] += 10
            logging.info(f"Client {client_info['address']} ({client_info['username']}) answered correctly: {answer}")
            self.send_message_to_client('correct:10 points', self.client_sockets[client_thread])
        else:
            # Incorrect answer
            logging.info(f"Client {client_info['address']} ({client_info['username']}) answered incorrectly: {answer}")
            correct_text = current_question['options'][correct]
            self.send_message_to_client(
                f'incorrect:Correct answer was {correct}) {correct_text}',
                self.client_sockets[client_thread]
            )

        # Advance to next question for this client
        client_info['question_index'] = idx + 1

        # If the client has completed all questions, mark finished
        if client_info['question_index'] >= len(self.questions):
            client_info['finished'] = True
            # Check if all clients have finished; if so, end the game and show leaderboard
            if all(ci.get('finished', False) for ci in self.clients.values()):
                self.end_game()
            else:
                # Notify this client that they have finished
                self.send_message_to_client('Quiz completed! Waiting for other players to finish...',
                                            self.client_sockets[client_thread])
        else:
            # Send next question to this client
            self.send_question_to_client(client_thread)

    def start_game(self) -> None:
        """
        Start a new quiz game session.

        This method:
        - Resets game state
        - Broadcasts game start message
        - Begins the question sequence
        """
        if self.game_active:
            return

        self.game_active = True
        self.current_question_index = 0

        logging.info("Starting new quiz game")
        self.broadcast_message("Game starting! Get ready for the quiz!")

        # Start first question after a short delay
        time.sleep(2)
        self.next_question()

    def next_question(self) -> None:
        """
        Move to the next question and broadcast it to all clients.

        This method:
        - Checks if there are more questions
        - Broadcasts the current question
        - Starts the timer
        - Handles game completion
        """
        if self.current_question_index >= len(self.questions):
            self.end_game()
            return

        # Reset responders for the new question
        self.current_question_responders = set()

        current_question = self.questions[self.current_question_index]
        self.question_start_time = time.time()

        # Format question for broadcasting as a single-line string
        # Join options with a pipe delimiter to avoid embedding newlines in the message.
        question_text = f"Question {self.current_question_index + 1}: {current_question['text']}"
        options_list = [f"{opt}) {text}" for opt, text in current_question['options'].items()]
        options_text = " | ".join(options_list)

        full_question = (
            f"{question_text} | {options_text} | Time limit: {self.question_duration} seconds"
        )

        logging.info(f"Broadcasting question {self.current_question_index + 1}")
        self.broadcast_message(full_question)

        # Clear the event and wait either for a client answer (event set) or for the
        # question timeout.  If a client answers, the event will be set in
        # handle_client_answer(), causing the wait to return early.  Otherwise,
        # wait() will time out after question_duration seconds.
        self.question_answered_event.clear()
        answered = self.question_answered_event.wait(self.question_duration)

        # Reveal correct answer after waiting for the event or timeout
        correct_answer = current_question['correct']
        correct_text = current_question['options'][correct_answer]
        # If the question was answered before the timeout, avoid the "Time's up" prefix.
        if answered:
            prefix = ""
        else:
            prefix = "Time's up! "
        self.broadcast_message(f"{prefix}Correct answer: {correct_answer}) {correct_text}")

        # Move to next question
        self.current_question_index += 1

        # Brief pause before next question
        time.sleep(3)
        self.next_question()

    def end_game(self) -> None:
        """
        End the current quiz game and announce final results.

        This method:
        - Stops the game
        - Calculates final scores
        - Broadcasts final leaderboard
        - Resets game state for next round
        """
        # Mark the game as over so that new clients do not start a new quiz
        self.game_active = False
        self.game_over = True

        logging.info("Quiz game ended")
        self.broadcast_message("Quiz completed! Final results:")

        # Sort clients by score (descending)
        sorted_clients = sorted(
            self.clients.values(),
            key=lambda x: x['score'],
            reverse=True
        )

        # Broadcast final leaderboard
        leaderboard_text = "🏆 FINAL LEADERBOARD 🏆\n"
        for i, client_info in enumerate(sorted_clients, 1):
            leaderboard_text += f"{i}. {client_info['username']}: {client_info['score']} points\n"

        self.broadcast_message(leaderboard_text)

        # Reset scores for next game
        for client_info in self.clients.values():
            client_info['score'] = 0

        # Do not automatically restart the game.  The quiz ends after the
        # final leaderboard is broadcast.  To start another game, the
        # server must be restarted or a new game must be initiated manually.

    def broadcast_message(self, message: str) -> None:
        """
        Broadcast a message to all connected clients.

        Args:
            message: Message to broadcast
        """
        with self.lock:
            for client_thread, client_socket in self.client_sockets.items():
                if client_thread in self.clients and self.clients[client_thread]['connected']:
                    self.send_message_to_client(message, client_socket)

    def send_question_to_client(self, client_thread: threading.Thread) -> None:
        """
        Send the current question to a specific client based on their
        individual question index.  This method also starts a timer thread
        that will handle the timeout for this client's answer.  If the client
        finishes all questions, they will be marked as finished and the server
        will check whether all clients are done.

        Args:
            client_thread: The thread identifying the client to send the question to
        """
        with self.lock:
            # Retrieve client info; if client has disconnected, do nothing
            client_info = self.clients.get(client_thread)
            if not client_info or client_info.get('finished', False):
                return

            idx = client_info.get('question_index', 0)
            if idx >= len(self.questions):
                # Client has completed all questions
                client_info['finished'] = True
                # If all clients are done, end the game
                if all(ci.get('finished', False) for ci in self.clients.values()):
                    self.end_game()
                else:
                    # Inform this client that the quiz is completed
                    self.send_message_to_client('Quiz completed! Waiting for other players to finish...',
                                                self.client_sockets[client_thread])
                return

            # Prepare question
            question = self.questions[idx]
            question_text = f"Question {idx + 1}: {question['text']}"
            options_list = [f"{opt}) {text}" for opt, text in question['options'].items()]
            options_text = " | ".join(options_list)
            full_question = (
                f"{question_text} | {options_text} | Time limit: {self.question_duration} seconds"
            )

            # Record start time
            client_info['question_start_time'] = time.time()

            # Cancel any existing timer thread (it will exit on its own when index changes)
            # and start a new timer thread for this question.
            timer_thread = threading.Thread(
                target=self.question_timeout_handler,
                args=(client_thread, idx),
                daemon=True
            )
            client_info['timer_thread'] = timer_thread

            # Send question to client
            self.send_message_to_client(full_question, self.client_sockets[client_thread])

            # Start timer thread
            timer_thread.start()

    def question_timeout_handler(self, client_thread: threading.Thread, question_index: int) -> None:
        """
        Handle the case where a client does not answer a question within the
        allotted time.  After waiting for question_duration seconds, this
        function checks whether the client has already advanced to the next
        question.  If not, it sends a time's up message with the correct
        answer, advances the client's question index, and either sends the
        next question or marks the client as finished.

        Args:
            client_thread: The thread identifying the client
            question_index: The index of the question that was sent
        """
        # Wait for the duration of the question
        time.sleep(self.question_duration)

        with self.lock:
            client_info = self.clients.get(client_thread)
            if not client_info:
                return

            # If the client is finished or has already moved on to the next
            # question, do nothing.  The timer thread becomes a no-op.
            if client_info.get('finished', False) or client_info.get('question_index', 0) != question_index:
                return

            # Client did not answer in time.  Reveal correct answer and move on.
            question = self.questions[question_index]
            correct = question['correct']
            correct_text = question['options'][correct]
            self.send_message_to_client(
                f"Time's up! Correct answer: {correct}) {correct_text}",
                self.client_sockets[client_thread]
            )

            # Advance question index
            client_info['question_index'] = question_index + 1

            # If client has finished all questions, mark finished
            if client_info['question_index'] >= len(self.questions):
                client_info['finished'] = True
                # Check if all clients have finished
                if all(ci.get('finished', False) for ci in self.clients.values()):
                    self.end_game()
                else:
                    # Notify this client of completion
                    self.send_message_to_client('Quiz completed! Waiting for other players to finish...',
                                                self.client_sockets[client_thread])
            else:
                # Send next question to this client
                self.send_question_to_client(client_thread)

    def broadcast_player_list(self) -> None:
        """
        Broadcast the current player list to all clients.
        """
        if not self.clients:
            return

        player_list = "Connected players:\n"
        for client_info in self.clients.values():
            player_list += f"- {client_info['username']} ({client_info['score']} points)\n"

        self.broadcast_message(player_list)

    def broadcast_score_update(self, username: str, score: int) -> None:
        """
        Broadcast a score update to all clients.

        Args:
            username: Username whose score was updated
            score: New score value
        """
        self.broadcast_message(f"Score update: {username} now has {score} points!")
        self.broadcast_leaderboard()

    def broadcast_leaderboard(self) -> None:
        """
        Broadcast the current leaderboard to all clients.
        """
        if not self.clients:
            return

        # Sort by score (descending)
        sorted_clients = sorted(
            self.clients.values(),
            key=lambda x: x['score'],
            reverse=True
        )

        leaderboard = "📊 CURRENT LEADERBOARD 📊\n"
        for i, client_info in enumerate(sorted_clients, 1):
            leaderboard += f"{i}. {client_info['username']}: {client_info['score']} points\n"

        self.broadcast_message(leaderboard)

    def send_message_to_client(self, message: str, client_socket: socket.socket) -> None:
        """
        Send a message to a specific client.

        Args:
            message: Message to send
            client_socket: Target client socket
        """
        try:
            data = message.encode('utf-8') + b'\n'
            client_socket.send(data)
            logging.debug(f"Sent message: {message}")
        except Exception as e:
            logging.error(f"Error sending message to client: {e}")

    def cleanup_client(self, client_thread: threading.Thread, client_socket: socket.socket, client_address: Tuple[str, int]) -> None:
        """
        Clean up resources for a disconnected client.

        Args:
            client_thread: Thread that was handling the client
            client_socket: Client's socket
            client_address: Client's address
        """
        with self.lock:
            if client_thread in self.clients:
                username = self.clients[client_thread]['username']
                del self.clients[client_thread]
                logging.info(f"Client {client_address} ({username}) disconnected")

            if client_thread in self.client_sockets:
                del self.client_sockets[client_thread]

        try:
            client_socket.close()
        except:
            pass

        # Broadcast updated player list
        self.broadcast_player_list()

    def broadcast_loop(self) -> None:
        """
        Background thread that handles periodic tasks like:
        - Cleaning up disconnected clients
        - Managing game state
        """
        while not self.stop_event.is_set():
            try:
                time.sleep(10)  # Check every 10 seconds

                with self.lock:
                    current_time = time.time()
                    disconnected_clients = []

                    # Check for disconnected clients (no activity for 60 seconds)
                    for client_thread, client_info in self.clients.items():
                        if current_time - client_info['last_seen'] > 60:
                            disconnected_clients.append(client_thread)

                    # Remove disconnected clients
                    for client_thread in disconnected_clients:
                        client_info = self.clients[client_thread]
                        client_socket = self.client_sockets.get(client_thread)
                        self.cleanup_client(client_thread, client_socket, client_info['address'])
                        logging.info(f"Client {client_info['address']} ({client_info['username']}) disconnected due to timeout")

            except Exception as e:
                logging.error(f"Error in broadcast loop: {e}")

    def stop_server(self) -> None:
        """
        Stop the server and clean up resources.
        """
        logging.info("Stopping TCP Quiz Server...")
        self.stop_event.set()

        # Close all client connections
        with self.lock:
            for client_socket in self.client_sockets.values():
                try:
                    client_socket.close()
                except:
                    pass

        if self.socket:
            self.socket.close()

        print("TCP Quiz Server stopped.")


def main():
    """
    Main function to start the TCP quiz server.
    """
    print("=== TCP Quiz Server ===")
    print("Starting server on port 8888...")

    # Create and start server
    server = TCPQuizServer()

    try:
        server.start_server()
    except KeyboardInterrupt:
        print("\nShutting down server...")
        server.stop_server()
    except Exception as e:
        print(f"Server error: {e}")
        server.stop_server()


if __name__ == "__main__":
    main()