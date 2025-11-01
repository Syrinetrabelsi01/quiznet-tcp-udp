#!/usr/bin/env python3
"""
TCP Quiz Client Implementation (modified)

This version of the TCP quiz client is compatible with the modified server that
broadcasts each quiz question as a single line separated by the pipe
delimiter (" | ").  The client replaces these pipe characters with
newlines when displaying the question so that the question text, options and
time limit appear on separate lines.  The rest of the client logic (join,
answer submission, timer display, etc.) remains the same.

Author: Adapted from CS411 Lab 4 Implementation
"""

import socket
import threading
import time
import sys
from typing import Optional, Tuple


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
        self.message_buffer = b''  # Buffer for partial messages

        # Duration for each quiz question in seconds.  This should match the
        # server's question duration.  The default server duration is 15 seconds.
        self.question_duration = 15

        # Threading
        self.receive_thread = None
        self.stop_event = threading.Event()

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
            self.socket.settimeout(30.0)  # 30-second timeout for connection

            # Connect to server
            self.socket.connect(self.server_address)
            self.connected = True

            print(f"✅ Connected to server at {self.server_host}:{self.server_port}")

            # Test connection with ping
            self.send_message('ping:test')

            # Wait for pong response (shorter timeout for test)
            try:
                self.socket.settimeout(5.0)
                data = self.socket.recv(1024)
                response = data.decode('utf-8').strip()
                if response == 'pong':
                    return True
            except socket.timeout:
                print("❌ Connection test timeout: server responded too slowly to ping")
                return False
            finally:
                # Restore longer timeout for normal receiving
                self.socket.settimeout(None)

        except socket.timeout:
            print("❌ Connection timeout - server not reachable (check IP/port and firewall)")
            return False
        except ConnectionRefusedError:
            print("❌ Connection refused - server may not be running or blocked by firewall")
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
        """
        Handle incoming messages from the server.

        Args:
            message: Message received from server
        """
        try:
            # Clear previous question display
            if self.current_question:
                print("\n" + "="*60)

            # Handle different message types
            if message.startswith('error:'):
                error_msg = message.split(':', 1)[1]
                print(f"❌ Server error: {error_msg}")

            elif message.startswith('correct:'):
                points = message.split(':', 1)[1]
                print(f"🎉 Correct! {points}")

            elif message.startswith('incorrect:'):
                correct_answer = message.split(':', 1)[1]
                print(f"❌ Incorrect. {correct_answer}")

            elif message.startswith('Score update:'):
                print(f"📊 {message}")

            elif message.startswith('📊') or message.startswith('🏆'):
                # Leaderboard or score update
                print(f"\n{message}")

            elif message.startswith('Connected players:'):
                print(f"\n{message}")

            elif message.startswith('Question') or 'Time limit:' in message:
                # This is a quiz question broadcast as a single-line message
                self.display_question(message)

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

    def display_question(self, question_text: str) -> None:
        """
        Display a quiz question and start the answer timer.

        Args:
            question_text: Formatted question text from server.  The server sends
                           the entire question, options and time limit on one
                           line using the pipe delimiter (" | ").
        """
        self.current_question = question_text
        self.question_start_time = time.time()

        # Replace pipe delimiters with newlines for readability
        formatted = question_text.replace(" | ", "\n").strip()

        print("\n" + "="*60)
        print("📝 QUIZ QUESTION")
        print("="*60)
        print(formatted)
        print("="*60)
        print("Enter your answer (a, b, c, or d) or 'quit' to exit:")

        # Start timer display thread
        self.start_question_timer()

    def start_question_timer(self) -> None:
        """
        Start a thread to display the question timer.
        """
        if self.question_timer and self.question_timer.is_alive():
            return

        self.question_timer = threading.Thread(target=self.display_timer, daemon=True)
        self.question_timer.start()

    def display_timer(self) -> None:
        """
        Display countdown timer for the current question.
        """
        start_time = time.time()
        while self.current_question and not self.stop_event.is_set():
            elapsed = time.time() - start_time
            remaining = max(0, self.question_duration - int(elapsed))

            if remaining <= 0:
                break

            # Update timer display (overwrite previous line)
            print(f"\r⏰ Time remaining: {remaining:2d} seconds", end='', flush=True)
            time.sleep(1)

        if self.current_question:
            print(f"\r⏰ Time's up! Time remaining:  0 seconds")

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