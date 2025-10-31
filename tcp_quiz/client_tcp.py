#!/usr/bin/env python3
"""
TCP Quiz Client Implementation

This script implements a TCP-based quiz game client that:
- Connects to the TCP quiz server using reliable TCP sockets
- Registers with a unique username
- Receives and displays quiz questions
- Sends answers within time limits
- Displays real-time feedback and leaderboard updates
- Handles network errors and disconnections gracefully

The client uses TCP sockets for reliable, ordered communication and provides
a terminal-based interface for user interaction during the quiz game.

Author: CS411 Lab 4 Implementation
"""

import socket
import threading
import json
import time
import sys
from typing import Optional, Dict, Tuple

class TCPQuizClient:
    """
    TCP-based quiz client that connects to the server and participates in quiz games.
    
    This class handles:
    - Server connection and communication using TCP
    - Message sending and receiving
    - User interface for quiz interaction
    - Error handling and reconnection
    """
    
    def __init__(self, server_host: str = 'localhost', server_port: int = 8888):
        """
        Initialize the TCP quiz client.
        
        Args:
            server_host: Server host address
            server_port: Server port number
        """
        self.server_host = server_host
        self.server_port = server_port
        self.server_address = (server_host, server_port)
        
        # Client state
        self.socket = None
        self.username = None
        self.connected = False
        self.current_question = None
        self.question_timer = None
        self.question_start_time = 0
        
        # Message handling
        self.message_buffer = b''  # Buffer for partial messages
        
        # Threading
        self.receive_thread = None
        self.stop_event = threading.Event()
        
        # Timeouts
        self.CONNECTION_TIMEOUT = 30.0  # 30 seconds for initial connection
        self.RECEIVE_TIMEOUT = 5.0      # 5 seconds for receiving data
        
        print("TCP Quiz Client initialized")
    
    def connect_to_server(self) -> bool:
        """
        Connect to the TCP quiz server.
        
        Returns:
            bool: True if connection successful, False otherwise
        """
        try:
            # Create TCP socket
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.socket.settimeout(self.CONNECTION_TIMEOUT)  # 30-second timeout for connection
            
            # Connect to server
            self.socket.connect(self.server_address)
            self.connected = True
            
            print(f"✅ Connected to server at {self.server_host}:{self.server_port}")
            
            # Test connection with ping
            self.send_message('ping:test')
            
            # Wait for pong response
            try:
                data = self.socket.recv(1024)
                response = data.decode('utf-8').strip()
                if response == 'pong':
                    return True
            except socket.timeout:
                print("❌ Connection test timeout")
                return False
            
        except socket.timeout:
            print("❌ Connection timeout - server may be unavailable")
            return False
        except ConnectionRefusedError:
            print("❌ Connection refused - server may not be running")
            return False
        except Exception as e:
            print(f"❌ Failed to connect to server: {e}")
            return False
        
        return False
    
    def register_username(self) -> bool:
        """
        Register a username with the server.
        
        Returns:
            bool: True if registration successful, False otherwise
        """
        while True:
            username = input("Enter your username: ").strip()
            
            if not username:
                print("❌ Username cannot be empty. Please try again.")
                continue
            
            if len(username) > 20:
                print("❌ Username too long (max 20 characters). Please try again.")
                continue
            
            # Send join request
            self.send_message(f'join:{username}')
            
            # Wait for response
            try:
                data = self.socket.recv(1024)
                response = data.decode('utf-8').strip()
                
                if response.startswith('welcome:'):
                    self.username = username
                    print(f"✅ Welcome, {username}! You're now registered.")
                    return True
                elif response.startswith('error:'):
                    error_msg = response.split(':', 1)[1]
                    print(f"❌ Registration failed: {error_msg}")
                    return False
                else:
                    print(f"❌ Unexpected response: {response}")
                    return False
                    
            except socket.timeout:
                print("❌ Registration timeout - server may be unavailable")
                return False
            except Exception as e:
                print(f"❌ Registration error: {e}")
                return False
    
    def start_receiving(self) -> None:
        """
        Start the background thread for receiving messages from server.
        """
        self.receive_thread = threading.Thread(target=self.receive_loop, daemon=True)
        self.receive_thread.start()
        print("📡 Started receiving messages from server...")
    
    def receive_loop(self) -> None:
        """
        Background loop for receiving and processing server messages.
        """
        while not self.stop_event.is_set() and self.connected:
            try:
                # Set a timeout for receiving
                self.socket.settimeout(5.0)
                data = self.socket.recv(1024)
                
                if not data:
                    # Server disconnected
                    print("❌ Server disconnected")
                    self.connected = False
                    break
                
                # Add to buffer
                self.message_buffer += data
                
                # Process complete messages (newline-delimited)
                while b'\n' in self.message_buffer:
                    message_bytes, self.message_buffer = self.message_buffer.split(b'\n', 1)
                    message = message_bytes.decode('utf-8').strip()
                    
                    if not message:
                        continue
                    
                    # Process the message
                    self.handle_server_message(message)
                
            except socket.timeout:
                # Timeout is normal, continue listening
                continue
            except ConnectionResetError:
                print("❌ Connection lost - server may have closed the connection")
                self.connected = False
                break
            except Exception as e:
                if not self.stop_event.is_set():
                    print(f"❌ Error receiving message: {e}")
                    self.connected = False
                break
    
    def handle_server_message(self, message: str) -> None:
        """Handle server messages with improved message parsing."""
        try:
            # First try parsing as JSON
            try:
                data = json.loads(message)
                if 'type' in data:
                    self.handle_json_message(data)
                    return
            except json.JSONDecodeError:
                pass
            
            # Fall back to text-based message parsing
            if message.startswith('error:'):
                error_msg = message.split(':', 1)[1]
                print(f"❌ Server error: {error_msg}")
                
            elif message.startswith('correct:'):
                points = message.split(':', 1)[1]
                print(f"🎉 Correct! {points}")
                
            elif message.startswith('incorrect:'):
                correct_answer = message.split(':', 1)[1]
                print(f"❌ Incorrect. {correct_answer}")
                
            elif message.startswith('welcome:'):
                # Welcome message during registration
                username = message.split(':', 1)[1]
                print(f"✅ Welcome, {username}! You're now registered.")
                
            elif message.startswith('Score update:'):
                print(f"📊 {message}")
                
            elif message.startswith('📊') or message.startswith('🏆'):
                # Leaderboard or score update
                print(f"\n{message}")
                
            elif message.startswith('Connected players:'):
                print(f"\n{message}")
                
            elif message.startswith('Question') or 'Time limit:' in message:
                # Legacy text-based question format
                self.handle_text_question(message)
                
            elif message.startswith("Time's up!"):
                print(f"⏰ {message}")
                self.current_question = None
                
            elif message.startswith('Game starting!'):
                print(f"🎮 {message}")
                
            elif message.startswith('Quiz completed!'):
                print(f"🏁 {message}")
                
            else:
                # Generic message
                print(f"📢 {message}")
                
        except Exception as e:
            print(f"❌ Error handling message: {e}")
            
    def handle_json_message(self, data: Dict) -> None:
        """Handle JSON-formatted messages from server."""
        message_type = data.get('type', '')
        
        if message_type == 'question':
            self.display_question(data)
        elif message_type == 'feedback':
            print(f"\n{data['message']}")
        elif message_type == 'timeout':
            print(f"\n{data['message']}")
            if self.question_timer and self.question_timer.is_alive():
                self.stop_event.set()
        elif message_type == 'leaderboard':
            print("\n📊 LEADERBOARD")
            print("="*30)
            for score in data['scores']:
                print(f"{score['username']}: {score['score']} points")
            print("="*30)
        elif message_type == 'game_start':
            print(f"\n{data['message']}")
        elif message_type == 'game_end':
            print(f"\n{data['message']}")
            
    def handle_text_question(self, message: str) -> None:
        """Handle legacy text-based question format."""
        lines = message.split('\n')
        question_data = {
            'text': lines[0],
            'options': {},
            'number': 1,
            'total': 1
        }
        
        # Parse options
        for line in lines[1:]:
            if ':' in line and not line.startswith('Time limit'):
                option_letter = line[0].lower()
                option_text = line[3:]  # Remove "x) " prefix
                question_data['options'][option_letter] = option_text
            
        self.display_question(question_data)
    
    def display_question(self, question_data: dict) -> None:
        """Display quiz question with countdown timer."""
        self.current_question = question_data
        self.question_start_time = time.time()
        
        # Clear any existing timer
        self.stop_event.set()
        if self.question_timer and self.question_timer.is_alive():
            self.question_timer.join()
        
        print("\n" + "="*60)
        print(f"📝 QUESTION {question_data.get('number', '?')} of {question_data.get('total', '?')}")
        print("="*60)
        print(question_data['text'])
        print("\nOptions:")
        for letter, text in question_data['options'].items():
            print(f"{letter}) {text}")
        print("="*60)
        print("Enter your answer (a, b, c, or d) or 'quit' to exit:")
        
        # Start new timer
        self.stop_event.clear()
        self.question_timer = threading.Thread(target=self.display_timer, daemon=True)
        self.question_timer.start()
    
    def display_timer(self) -> None:
        """Display countdown timer for current question."""
        end_time = self.question_start_time + 30  # 30 second timer
        
        while time.time() < end_time and not self.stop_event.is_set():
            remaining = int(end_time - time.time())
            sys.stdout.write(f"\r⏱️  Time remaining: {remaining:2d}s ")
            sys.stdout.flush()
            time.sleep(1)
            
        if not self.stop_event.is_set():
            print("\n⌛ Time's up!")
            self.current_question = None
    
    def send_message(self, message: str) -> None:
        """
        Send a message to the server.
        
        Args:
            message: Message to send
        """
        try:
            if self.socket and self.connected:
                data = message.encode('utf-8') + b'\n'
                self.socket.send(data)
        except Exception as e:
            print(f"❌ Error sending message: {e}")
            self.connected = False
    
    def send_answer(self, answer: str) -> None:
        """
        Send an answer to the current question.
        
        Args:
            answer: Answer choice (a, b, c, or d)
        """
        if not self.current_question:
            print("❌ No active question to answer")
            return
        
        if answer.lower() not in ['a', 'b', 'c', 'd']:
            print("❌ Invalid answer. Please enter a, b, c, or d")
            return
        
        self.send_message(f'answer:{answer.lower()}')
        self.current_question = None  # Clear current question
        
        # Stop timer display
        if self.question_timer and self.question_timer.is_alive():
            pass  # Timer will stop naturally
    
    def run(self) -> None:
        """
        Main client loop for user interaction.
        """
        print("🎮 TCP Quiz Game Client")
        print("="*40)
        
        # Connect to server
        if not self.connect_to_server():
            print("❌ Failed to connect to server. Exiting.")
            return
        
        # Register username
        if not self.register_username():
            print("❌ Failed to register username. Exiting.")
            return
        
        # Start receiving messages
        self.start_receiving()
        
        print("\n🎯 You're now in the quiz game!")
        print("Commands:")
        print("  a, b, c, d - Answer current question")
        print("  quit       - Exit the game")
        print("  help       - Show this help")
        print("\nWaiting for questions...")
        
        # Main interaction loop
        try:
            while self.connected and not self.stop_event.is_set():
                try:
                    user_input = input().strip().lower()
                    
                    if user_input == 'quit':
                        print("👋 Goodbye!")
                        break
                    elif user_input == 'help':
                        print("\nCommands:")
                        print("  a, b, c, d - Answer current question")
                        print("  quit       - Exit the game")
                        print("  help       - Show this help")
                    elif user_input in ['a', 'b', 'c', 'd']:
                        self.send_answer(user_input)
                    else:
                        print("❌ Invalid command. Type 'help' for available commands.")
                        
                except KeyboardInterrupt:
                    print("\n👋 Goodbye!")
                    break
                except EOFError:
                    print("\n👋 Goodbye!")
                    break
                except Exception as e:
                    print(f"❌ Input error: {e}")
                    
        finally:
            self.disconnect()
    
    def disconnect(self) -> None:
        """
        Disconnect from the server and clean up resources.
        """
        print("🔌 Disconnecting from server...")
        self.stop_event.set()
        self.connected = False
        
        if self.socket:
            try:
                self.socket.close()
            except:
                pass
        
        print("✅ Disconnected.")

def main():
    """
    Main function to start the TCP quiz client.
    """
    print("=== TCP Quiz Client ===")
    
    # Get server address from user
    server_host = input("Enter server host (default: localhost): ").strip()
    if not server_host:
        server_host = 'localhost'
    
    server_port_input = input("Enter server port (default: 8888): ").strip()
    try:
        server_port = int(server_port_input) if server_port_input else 8888
    except ValueError:
        print("❌ Invalid port number. Using default 8888.")
        server_port = 8888
    
    # Create and run client
    client = TCPQuizClient(server_host, server_port)
    
    try:
        client.run()
    except KeyboardInterrupt:
        print("\n👋 Goodbye!")
        client.disconnect()
    except Exception as e:
        print(f"❌ Client error: {e}")
        client.disconnect()

if __name__ == "__main__":
    main()
