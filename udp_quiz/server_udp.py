#!/usr/bin/env python3
"""
UDP Quiz Server Implementation

This script implements a UDP-based multiplayer quiz game server that:
- Manages multiple clients concurrently using UDP sockets
- Broadcasts quiz questions to all connected clients
- Handles client answers and maintains a leaderboard
- Provides real-time score updates and feedback
- Uses port 8888 for communication

The server reads questions from questions.txt and manages game state including:
- Client registration and management
- Question broadcasting with 30-second timers
- Answer validation and scoring
- Leaderboard maintenance and broadcasting
- Graceful error handling and logging

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
        logging.FileHandler('udp_server.log'),
        logging.StreamHandler()
    ]
)

class UDPQuizServer:
    """
    UDP-based quiz server that manages multiple clients and conducts quiz games.
    
    This class handles:
    - Client registration and management
    - Question broadcasting with timers
    - Answer processing and scoring
    - Leaderboard maintenance
    - Error handling and logging
    """
    
    def __init__(self, host: str = '0.0.0.0', port: int = 8888):
        """
        Initialize the UDP quiz server.
        
        Args:
            host: Server host address (0.0.0.0 for all interfaces)
            port: Server port number (default: 8888)
        """
        self.host = host
        self.port = port
        self.socket = None
        
        # Game state management
        self.clients: Dict[Tuple[str, int], Dict] = {}  # (ip, port) -> client_info
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
        
        logging.info(f"UDP Quiz Server initialized on {host}:{port}")
    
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
                    'text': 'What is UDP?',
                    'options': {'a': 'User Datagram Protocol', 'b': 'Universal Data Protocol', 'c': 'Unified Data Protocol', 'd': 'User Data Protocol'},
                    'correct': 'a'
                }
            ]
        except Exception as e:
            logging.error(f"Error loading questions: {e}")
            self.questions = []
    
    def start_server(self) -> None:
        """
        Start the UDP server and begin accepting client connections.
        
        This method:
        - Creates and binds the UDP socket
        - Starts the broadcast thread for game management
        - Begins listening for client messages
        """
        try:
            # Create UDP socket
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.socket.bind((self.host, self.port))
            
            logging.info(f"UDP Quiz Server started on {self.host}:{self.port}")
            print(f"UDP Quiz Server running on {self.host}:{self.port}")
            print("Waiting for clients to connect...")
            
            # Start broadcast thread for game management
            self.broadcast_thread = threading.Thread(target=self.broadcast_loop, daemon=True)
            self.broadcast_thread.start()
            
            # Main server loop - listen for client messages
            while not self.stop_event.is_set():
                try:
                    # Receive data from clients
                    data, client_address = self.socket.recvfrom(1024)
                    
                    # Process message in a separate thread to handle multiple clients
                    client_thread = threading.Thread(
                        target=self.handle_client_message,
                        args=(data, client_address),
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
    
    def handle_client_message(self, data: bytes, client_address: Tuple[str, int]) -> None:
        """
        Handle incoming messages from clients.
        
        Args:
            data: Raw message data from client
            client_address: Tuple of (IP, port) of the client
        """
        try:
            # Decode message from UTF-8
            message = data.decode('utf-8').strip()
            logging.info(f"Received from {client_address}: {message}")
            
            # Parse message format: command:data
            if ':' in message:
                command, data_part = message.split(':', 1)
                command = command.lower()
                
                with self.lock:
                    if command == 'join':
                        self.handle_client_join(data_part, client_address)
                    elif command == 'answer':
                        self.handle_client_answer(data_part, client_address)
                    elif command == 'ping':
                        self.send_message('pong', client_address)
                    else:
                        logging.warning(f"Unknown command from {client_address}: {command}")
            else:
                logging.warning(f"Invalid message format from {client_address}: {message}")
                
        except UnicodeDecodeError:
            logging.error(f"Invalid UTF-8 data from {client_address}")
        except Exception as e:
            logging.error(f"Error handling message from {client_address}: {e}")
    
    def handle_client_join(self, username: str, client_address: Tuple[str, int]) -> None:
        """
        Handle client registration/join request.
        
        Args:
            username: Username provided by client
            client_address: Client's address tuple
        """
        if not username or len(username.strip()) == 0:
            self.send_message('error:Invalid username', client_address)
            return
        
        username = username.strip()
        
        # Check if username already exists
        existing_client = None
        for addr, client_info in self.clients.items():
            if client_info['username'] == username:
                existing_client = addr
                break
        
        if existing_client:
            # Remove old client with same username
            del self.clients[existing_client]
            logging.info(f"Removed existing client {existing_client} with username '{username}'")
        
        # Register new client
        self.clients[client_address] = {
            'username': username,
            'score': 0,
            'last_seen': time.time(),
            'connected': True
        }
        
        logging.info(f"Client {client_address} joined as '{username}'")
        self.send_message(f'welcome:{username}', client_address)
        
        # Broadcast updated player list
        self.broadcast_player_list()
        
        # If game is not active and we have clients, start the game
        if not self.game_active and len(self.clients) > 0:
            self.start_game()
    
    def handle_client_answer(self, answer: str, client_address: Tuple[str, int]) -> None:
        """
        Handle client answer submission.
        
        Args:
            answer: Answer provided by client (format: "a", "b", "c", or "d")
            client_address: Client's address tuple
        """
        if client_address not in self.clients:
            self.send_message('error:Not registered', client_address)
            return
        
        if not self.game_active or self.current_question_index >= len(self.questions):
            self.send_message('error:No active question', client_address)
            return
        
        # Check if question time has expired
        current_time = time.time()
        if current_time - self.question_start_time > self.question_duration:
            self.send_message('error:Time expired', client_address)
            return
        
        # Process answer
        answer = answer.strip().lower()
        current_question = self.questions[self.current_question_index]
        
        client_info = self.clients[client_address]
        client_info['last_seen'] = current_time
        
        if answer == current_question['correct']:
            # Correct answer - award points
            client_info['score'] += 10
            logging.info(f"Client {client_address} ({client_info['username']}) answered correctly: {answer}")
            self.send_message('correct:10 points', client_address)
            
            # Broadcast score update
            self.broadcast_score_update(client_info['username'], client_info['score'])
        else:
            # Incorrect answer
            logging.info(f"Client {client_address} ({client_info['username']}) answered incorrectly: {answer}")
            self.send_message(f'incorrect:Correct answer was {current_question["correct"]}', client_address)
    
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
            self.clients.items(),
            key=lambda x: x[1]['score'],
            reverse=True
        )
        
        # Broadcast final leaderboard
        leaderboard_text = "🏆 FINAL LEADERBOARD 🏆\n"
        for i, (addr, client_info) in enumerate(sorted_clients, 1):
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
            for client_address in list(self.clients.keys()):
                self.send_message(message, client_address)
    
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
    
    def send_message(self, message: str, client_address: Tuple[str, int]) -> None:
        """
        Send a message to a specific client.
        
        Args:
            message: Message to send
            client_address: Target client address
        """
        try:
            data = message.encode('utf-8')
            self.socket.sendto(data, client_address)
            logging.debug(f"Sent to {client_address}: {message}")
        except Exception as e:
            logging.error(f"Error sending message to {client_address}: {e}")
            # Remove client if sending fails
            with self.lock:
                if client_address in self.clients:
                    del self.clients[client_address]
    
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
                    for client_address, client_info in self.clients.items():
                        if current_time - client_info['last_seen'] > 60:
                            disconnected_clients.append(client_address)
                    
                    # Remove disconnected clients
                    for client_address in disconnected_clients:
                        username = self.clients[client_address]['username']
                        del self.clients[client_address]
                        logging.info(f"Client {client_address} ({username}) disconnected due to timeout")
                    
                    # Broadcast updated player list if clients were removed
                    if disconnected_clients:
                        self.broadcast_player_list()
                
            except Exception as e:
                logging.error(f"Error in broadcast loop: {e}")
    
    def stop_server(self) -> None:
        """
        Stop the server and clean up resources.
        """
        logging.info("Stopping UDP Quiz Server...")
        self.stop_event.set()
        
        if self.socket:
            self.socket.close()
        
        print("UDP Quiz Server stopped.")

def main():
    """
    Main function to start the UDP quiz server.
    """
    print("=== UDP Quiz Server ===")
    print("Starting server on port 8888...")
    
    # Create and start server
    server = UDPQuizServer()
    
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
