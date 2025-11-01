#!/usr/bin/env python3
"""
UDP Quiz Client (enhanced version)

This client connects to the UDP quiz server and participates in quiz games.  It
is designed to work with the improved server implementation that sends each
question as a single line using pipe delimiters.  The client replaces these
delimiters with newlines for display so the question and options are clearly
separated.  It also displays score updates, leaderboards and other messages
sent by the server.

Key features:

* Handshake (ping/pong) to verify server reachability before proceeding.
* Username registration with retry on error.
* Dedicated receiver thread that prints all incoming messages without
  interfering with the user's ability to type answers.
* Countdown timer display for each question that matches the server's
  ``question_duration`` (default 15 seconds).  The timer stops once a
  question is answered or a new question arrives.
* Simple command loop supporting answer submission and quitting the game.

To run the client, execute this file and enter the server's host and port
when prompted.  Once connected and registered, the game will start
automatically when the server initiates it.
"""

from __future__ import annotations

import socket
import threading
import time
from typing import Tuple


class UDPQuizClient:
    """Client for playing the UDP quiz game."""

    def __init__(self, server_host: str = 'localhost', server_port: int = 8888, question_duration: int = 15):
        self.server_addr: Tuple[str, int] = (server_host, server_port)
        self.question_duration = question_duration
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.settimeout(5.0)
        self.username: str | None = None
        self.connected: bool = False
        self.stop_event = threading.Event()
        # Track the current question text for timer display; None when no question is active.
        self.current_question: str | None = None
        self.question_timer_thread: threading.Thread | None = None

    # -------------------------------------------------------------------------
    # Networking helpers
    # -------------------------------------------------------------------------
    def _send(self, message: str) -> None:
        """Send a UDP message to the server."""
        try:
            self.sock.sendto(message.encode('utf-8'), self.server_addr)
        except Exception as e:
            print(f"❌ Error sending message: {e}")
            self.connected = False

    def _receive_once(self, timeout: float = 5.0) -> Tuple[str, Tuple[str, int]] | None:
        """Receive a single message with a timeout."""
        self.sock.settimeout(timeout)
        try:
            data, addr = self.sock.recvfrom(4096)
            return data.decode('utf-8').strip(), addr
        except socket.timeout:
            return None
        except Exception as e:
            print(f"❌ Error receiving message: {e}")
            self.connected = False
            return None

    # -------------------------------------------------------------------------
    # Connection and registration
    # -------------------------------------------------------------------------
    def connect(self) -> bool:
        """Attempt to ping the server to verify connectivity."""
        # Send ping
        self._send('ping:test')
        # Await pong
        response = self._receive_once(timeout=5.0)
        if response and response[0] == 'pong':
            self.connected = True
            print(f"✅ Connected to server at {self.server_addr[0]}:{self.server_addr[1]}")
            return True
        print("❌ Unable to reach server (no pong reply)")
        return False

    def register(self) -> bool:
        """Register a username with the server."""
        while not self.username:
            name = input("Enter your username: ").strip()
            if not name:
                print("❌ Username cannot be empty. Try again.")
                continue
            if len(name) > 20:
                print("❌ Username too long (max 20 characters). Try again.")
                continue
            # Send join request
            self._send(f'join:{name}')
            response = self._receive_once(timeout=5.0)
            if response:
                msg, _ = response
                if msg.startswith('welcome:'):
                    print(f"✅ Welcome, {name}! You're now registered.")
                    self.username = name
                    return True
                elif msg.startswith('error:'):
                    print(f"❌ Registration failed: {msg.split(':',1)[1]}")
                    return False
                # Fall through to continue on unexpected messages
            print("❌ No response to registration request. Retrying...")
        return False

    # -------------------------------------------------------------------------
    # Receiving and processing messages
    # -------------------------------------------------------------------------
    def _start_receiver(self) -> None:
        """Start a background thread to continuously listen for server messages."""
        threading.Thread(target=self._receive_loop, daemon=True).start()
        print("📡 Started receiving messages from server...")

    def _receive_loop(self) -> None:
        """Background loop that processes incoming server messages."""
        while not self.stop_event.is_set() and self.connected:
            try:
                # Short timeout to allow clean shutdown
                self.sock.settimeout(1.0)
                data, _ = self.sock.recvfrom(4096)
                message = data.decode('utf-8').strip()
                if not message:
                    continue
                # Multiple messages may be newline separated; handle each one.
                for line in message.split('\n'):
                    if line:
                        self._handle_server_message(line)
            except socket.timeout:
                continue
            except Exception as e:
                if not self.stop_event.is_set():
                    print(f"❌ Error receiving message: {e}")
                    self.connected = False
                break

    def _handle_server_message(self, message: str) -> None:
        """Interpret and act on a single message from the server."""
        # When a new question arrives, clear current question
        if message.startswith('Question') or 'Time limit:' in message:
            # Display question nicely (replace pipes with newlines)
            self.current_question = message
            formatted = message.replace(' | ', '\n').strip()
            print("\n" + "="*60)
            print("📝 QUIZ QUESTION")
            print("="*60)
            print(formatted)
            print("="*60)
            print("Enter your answer (a, b, c, or d) or 'quit' to exit:")
            # Start a timer thread if not already running
            self._start_timer_thread()
        elif message.startswith('correct:'):
            points = message.split(':',1)[1]
            print(f"🎉 Correct! {points}")
            # End current question and timer
            self.current_question = None
        elif message.startswith('incorrect:'):
            info = message.split(':',1)[1]
            print(f"❌ Incorrect. {info}")
            self.current_question = None
        elif message.startswith('Score update:'):
            print(f"📊 {message}")
        elif message.startswith('📊') or message.startswith('🏁') or message.startswith('🏆'):
            # Leaderboard or final scoreboard
            print("\n" + message)
        elif message.startswith('Connected players:'):
            print("\n" + message)
        elif message.startswith("Time's up!") or message.startswith('Correct answer:'):
            print(f"⏰ {message}")
            self.current_question = None
        elif message.startswith('Game starting!'):
            print(f"🎮 {message}")
        else:
            # Print any other informational messages
            print(f"📢 {message}")

    # -------------------------------------------------------------------------
    # Timer handling
    # -------------------------------------------------------------------------
    def _start_timer_thread(self) -> None:
        """Spawn a thread to display the countdown timer for the current question."""
        if self.question_timer_thread and self.question_timer_thread.is_alive():
            # A timer is already running; let it finish
            return
        self.question_timer_thread = threading.Thread(target=self._display_timer, daemon=True)
        self.question_timer_thread.start()

    def _display_timer(self) -> None:
        """Display a countdown timer matching the question duration."""
        start = time.time()
        while self.current_question and not self.stop_event.is_set():
            elapsed = time.time() - start
            remaining = max(0, self.question_duration - int(elapsed))
            if remaining <= 0:
                break
            print(f"\r⏰ Time remaining: {remaining:2d} seconds", end='', flush=True)
            time.sleep(1)
        # On timeout, show 0 seconds if still on this question
        if self.current_question:
            print(f"\r⏰ Time remaining:  0 seconds")

    # -------------------------------------------------------------------------
    # Main event loop
    # -------------------------------------------------------------------------
    def run(self) -> None:
        """Run the client: connect, register and handle input."""
        print("🎮 UDP Quiz Game Client")
        print("="*40)
        if not self.connect():
            return
        if not self.register():
            return
        # Start background receiver
        self._start_receiver()
        print("\n🎯 You're now in the quiz game!")
        print("Commands:")
        print("  a, b, c, d - Answer current question")
        print("  quit       - Exit the game")
        print("  help       - Show this help")
        print("\nWaiting for questions...")
        # Main user input loop
        try:
            while self.connected and not self.stop_event.is_set():
                user_input = input().strip().lower()
                if user_input == 'quit':
                    break
                if user_input == 'help':
                    print("\nCommands:")
                    print("  a, b, c, d - Answer current question")
                    print("  quit       - Exit the game")
                    print("  help       - Show this help")
                elif user_input in ['a', 'b', 'c', 'd']:
                    # Send answer
                    self._send(f'answer:{user_input}')
                    # The timer will be stopped once a new question arrives or on correct/incorrect message
                elif user_input:
                    print("❌ Invalid command. Type 'help' for available commands.")
        except KeyboardInterrupt:
            pass
        # Signal receiver thread to stop
        self.stop_event.set()
        self.connected = False
        print("🔌 Disconnecting from server...")
        try:
            self.sock.close()
        finally:
            print("✅ Disconnected.")


def main() -> None:
    """Prompt for server details and start the UDP client."""
    print("=== UDP Quiz Client ===")
    host = input("Enter server host (default: localhost): ").strip() or 'localhost'
    port_str = input("Enter server port (default: 8888): ").strip()
    try:
        port = int(port_str) if port_str else 8888
    except ValueError:
        print("❌ Invalid port number; using default 8888.")
        port = 8888
    client = UDPQuizClient(host, port)
    client.run()


if __name__ == '__main__':
    main()