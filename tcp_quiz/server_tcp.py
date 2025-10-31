#!/usr/bin/env python3
"""
TCP Quiz Server Implementation

This script implements a TCP-based multiplayer quiz game server that:
- Manages multiple clients concurrently using TCP sockets and threading
- Broadcasts quiz questions to all connected clients
- Handles client answers and maintains a leaderboard
- Provides real-time score updates and feedback
- Uses port 8888 for communication

The server uses multithreading to handle multiple clients simultaneously and
provides reliable, ordered communication for the quiz game.

Author: CS411 Lab 4 Implementation
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
        self.clients: Dict[threading.Thread, Dict] = {}  # thread -> client_info
        self.client_sockets: Dict[threading.Thread, socket.socket] = {}  # thread -> socket
        self.questions: List[Dict] = []
        self.current_question_index = 0
        self.game_active = False
        self.question_start_time = 0
        self.question_duration = 30  # 30 seconds per question
        
        # Threading and synchronization
        self.lock = threading.Lock()
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
                            option_letter = option_text[0]  # a, b, c, or d
                            options[option_letter] = option_text[3:]  # Remove "a) " prefix
                    
                    correct_answer = parts[5] if len(parts) > 5 else 'a'
                    
                    self.questions.append({
                        'id': question_id,
                        'text': question_text,
                        'options': options,
                        'correct': correct_answer
                    })
            
            logging.info(f"Loaded {len(self.questions)} questions from questions.txt")
            
        except FileNotFoundError:
            logging.error("questions.txt file not found!")
            # Create sample questions if file doesn't exist
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
        
        # Register new client
        client_info = {
            'username': username,
            'score': 0,
            'last_seen': time.time(),
            'connected': True,
            'address': client_address
        }
        
        self.clients[client_thread] = client_info
        
        logging.info(f"Client {client_address} joined as '{username}'")
        # Send welcome message using the socket
        self.send_message_to_client(f'welcome:{username}', self.client_sockets[client_thread])
        
        # Broadcast updated player list
        self.broadcast_player_list()
        
        # If game is not active and we have clients, start the game
        if not self.game_active and len(self.clients) > 0:
            self.start_game()
        
        return client_info
    
    def handle_client_answer(self, answer: str, client_info: Dict, client_thread: threading.Thread) -> None:
        """
        Handle client answer submission.
        
        Args:
            answer: Answer provided by client (format: "a", "b", "c", or "d")
            client_info: Client information dictionary
            client_thread: Thread handling this client
        """
        if not self.game_active or self.current_question_index >= len(self.questions):
            self.send_message_to_client('error:No active question', self.client_sockets[client_thread])
            return
        
        # Check if question time has expired
        current_time = time.time()
        if current_time - self.question_start_time > self.question_duration:
            self.send_message_to_client('error:Time expired', self.client_sockets[client_thread])
            return
        
        # Process answer
        answer = answer.strip().lower()
        current_question = self.questions[self.current_question_index]
        
        client_info['last_seen'] = current_time
        
        if answer == current_question['correct']:
            # Correct answer - award points
            client_info['score'] += 10
            logging.info(f"Client {client_info['address']} ({client_info['username']}) answered correctly: {answer}")
            self.send_message_to_client('correct:10 points', self.client_sockets[client_thread])
            
            # Broadcast score update
            self.broadcast_score_update(client_info['username'], client_info['score'])
        else:
            # Incorrect answer
            logging.info(f"Client {client_info['address']} ({client_info['username']}) answered incorrectly: {answer}")
            self.send_message_to_client(f'incorrect:Correct answer was {current_question["correct"]}', self.client_sockets[client_thread])
    
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
        
        current_question = self.questions[self.current_question_index]
        self.question_start_time = time.time()
        
        # Format question for broadcasting
        question_text = f"Question {self.current_question_index + 1}: {current_question['text']}"
        options_text = "\n".join([f"{opt}: {text}" for opt, text in current_question['options'].items()])
        
        full_question = f"{question_text}\n{options_text}\nTime limit: {self.question_duration} seconds"
        
        logging.info(f"Broadcasting question {self.current_question_index + 1}")
        self.broadcast_message(full_question)
        
        # Wait for question duration
        time.sleep(self.question_duration)
        
        # Reveal correct answer
        correct_answer = current_question['correct']
        correct_text = current_question['options'][correct_answer]
        self.broadcast_message(f"Time's up! Correct answer: {correct_answer}) {correct_text}")
        
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
        self.game_active = False
        
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
        
        # Wait before starting next game
        time.sleep(5)
        if len(self.clients) > 0:
            self.start_game()
    
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
        - Sending periodic pings
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