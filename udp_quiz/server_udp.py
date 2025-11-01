#!/usr/bin/env python3
"""
UDP Quiz Server (enhanced version)

This server implements a multiplayer quiz game over UDP. It mirrors many of the
features of the final TCP implementation, including:

* Single‑line question broadcasts using the pipe (" | ") delimiter to avoid
  splitting messages across datagram boundaries.
* A separate game management thread that runs through all questions without
  blocking the main receive loop.  This ensures the server can continue to
  receive answers and keep track of players even while questions are being
  asked.
* Per‑question timeouts and an early exit if all active clients submit an
  answer.  Clients who answer correctly are awarded points immediately and
  leaderboards are updated on the fly.
* Score, leaderboard and player list broadcasts similar to the TCP version.
* Graceful handling of client joins, pings, invalid messages and timeouts.

To run the server simply execute this file.  It listens on all interfaces on
port 8888 by default.  Questions are loaded from ``questions.txt`` which must
be located in the same directory as this script.  See the accompanying
``client_udp.py`` for a compatible client implementation.
"""

from __future__ import annotations

import socket
import threading
import time
import logging
from typing import Dict, Tuple, List


# Configure logging to both a file and stderr.  Adjust the level to DEBUG
# during development for more verbose output.
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('udp_server.log'),
        logging.StreamHandler()
    ]
)


class UDPQuizServer:
    """A UDP‑based quiz server that manages multiple clients and runs quiz games."""

    def __init__(self, host: str = '0.0.0.0', port: int = 8888, question_duration: int = 15):
        """
        Initialise the UDP quiz server.

        :param host: bind address.  Use '0.0.0.0' to listen on all network interfaces.
        :param port: UDP port on which to listen.
        :param question_duration: number of seconds to wait for answers per question.
        """
        self.host = host
        self.port = port
        self.question_duration = question_duration
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind((self.host, self.port))

        # Mapping of client address to client info (username, score, last_seen).
        self.clients: Dict[Tuple[str, int], Dict[str, any]] = {}
        # List of questions loaded from file.
        self.questions: List[Dict[str, any]] = []
        # Game state tracking variables.
        self.game_active: bool = False
        self.current_question_index: int = -1
        self.current_question_start: float = 0.0
        # Event used to terminate waiting when all active clients have answered.
        self.question_answered_event = threading.Event()
        # Track which client addresses have answered the current question.
        self.current_question_responders: set[Tuple[str, int]] = set()

        # Concurrency primitives.
        self.lock = threading.RLock()
        self.stop_event = threading.Event()

        # Load quiz questions at startup.
        self._load_questions()

        logging.info(f"UDP Quiz Server initialised on {self.host}:{self.port}")

    def _load_questions(self) -> None:
        """Load quiz questions from ``questions.txt``.  Creates a sample question on failure."""
        try:
            with open('questions.txt', 'r', encoding='utf-8') as file:
                lines = [line.strip() for line in file.readlines() if line.strip()]
            for line in lines:
                parts = line.split('|')
                # Expected format: id:question|a)option1|b)option2|c)option3|d)option4|correct
                if len(parts) >= 6:
                    qid = parts[0].split(':')[0]
                    qtext = parts[0].split(':', 1)[1]
                    options = {}
                    for opt in parts[1:5]:
                        # Each option starts with e.g. "a) text" or "a)text".  Grab the key and body.
                        letter = opt[0].lower()
                        body = opt[2:].lstrip(' )')  # remove "a) " or "a)" prefix and extra space
                        options[letter] = body
                    correct = parts[5].strip().lower()
                    self.questions.append({'id': qid, 'text': qtext, 'options': options, 'correct': correct})
            logging.info(f"Loaded {len(self.questions)} questions from questions.txt")
        except FileNotFoundError:
            logging.error("questions.txt file not found; using a sample question.")
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

    def start(self) -> None:
        """Start the server and begin listening for client messages."""
        # Thread to receive and handle incoming messages.
        threading.Thread(target=self._receive_loop, daemon=True).start()
        print(f"UDP Quiz Server running on {self.host}:{self.port}")
        print("Waiting for clients to connect...")
        try:
            while not self.stop_event.is_set():
                time.sleep(1)
        except KeyboardInterrupt:
            logging.info("Server interrupted by keyboard; shutting down.")
            self.stop_event.set()

    def _receive_loop(self) -> None:
        """Continuously receive messages and dispatch them to handlers."""
        while not self.stop_event.is_set():
            try:
                data, addr = self.sock.recvfrom(2048)
                message = data.decode('utf-8').strip()
                if not message:
                    continue
                # Split at first colon to get command and remainder.
                if ':' in message:
                    command, payload = message.split(':', 1)
                else:
                    command, payload = message, ''
                command = command.lower()
                if command == 'ping':
                    self._send('pong', addr)
                elif command == 'join':
                    self._handle_join(payload.strip(), addr)
                elif command == 'answer':
                    self._handle_answer(payload.strip(), addr)
                else:
                    logging.warning(f"Unknown command '{command}' from {addr}")
            except Exception as e:
                logging.error(f"Error receiving message: {e}")

    # -------------------------------------------------------------------------
    # Client join/answer handlers
    # -------------------------------------------------------------------------
    def _handle_join(self, username: str, addr: Tuple[str, int]) -> None:
        """Register a new client and start a game if none is active."""
        if not username:
            self._send('error:Invalid username', addr)
            return
        username = username.strip()
        with self.lock:
            # Remove existing record for this username (if connected from elsewhere).
            to_remove = [a for a, info in self.clients.items() if info['username'] == username]
            for rem in to_remove:
                del self.clients[rem]
                logging.info(f"Removed existing client {rem} with username '{username}'")
            # Add new client.
            self.clients[addr] = {'username': username, 'score': 0, 'last_seen': time.time(), 'connected': True}
        logging.info(f"Client {addr} joined as '{username}'")
        self._send(f'welcome:{username}', addr)
        self._broadcast_player_list()
        # Start the game if not already running.
        if not self.game_active and len(self.clients) > 0:
            threading.Thread(target=self._start_game, daemon=True).start()

    def _handle_answer(self, answer: str, addr: Tuple[str, int]) -> None:
        """Handle an answer submission from a client."""
        with self.lock:
            # Verify client registration
            if addr not in self.clients:
                self._send('error:Not registered', addr)
                return
            # Verify game state
            if not self.game_active or self.current_question_index < 0 or self.current_question_index >= len(self.questions):
                self._send('error:No active question', addr)
                return
            # Check timeout
            if time.time() - self.current_question_start > self.question_duration:
                self._send('error:Time expired', addr)
                return
            # Mark this client as having responded to current question.
            self.current_question_responders.add(addr)
            # Fetch current question and check correctness
            question = self.questions[self.current_question_index]
            answer = answer.lower().strip()
            client_info = self.clients[addr]
            client_info['last_seen'] = time.time()
            if answer == question['correct']:
                client_info['score'] += 10
                logging.info(f"Client {addr} ({client_info['username']}) answered correctly: {answer}")
                self._send('correct:10 points', addr)
                self._broadcast_score_update(client_info['username'], client_info['score'])
            else:
                logging.info(f"Client {addr} ({client_info['username']}) answered incorrectly: {answer}")
                correct_letter = question['correct']
                correct_text = question['options'][correct_letter]
                self._send(f'incorrect:Correct answer was {correct_letter}) {correct_text}', addr)
            # If all active clients have responded, signal event to skip remaining wait.
            active_clients = [a for a, info in self.clients.items() if info['connected']]
            if len(self.current_question_responders) >= len(active_clients):
                self.question_answered_event.set()

    # -------------------------------------------------------------------------
    # Game management
    # -------------------------------------------------------------------------
    def _start_game(self) -> None:
        """Begin a new quiz session in a separate thread."""
        # Prevent multiple games from running concurrently.
        with self.lock:
            if self.game_active:
                return
            self.game_active = True
        logging.info("Starting new quiz game")
        self._broadcast("Game starting! Get ready for the quiz!")
        time.sleep(2)
        # Iterate through each question
        for idx in range(len(self.questions)):
            # Check stop condition
            if self.stop_event.is_set():
                break
            self._ask_question(idx)
        self._end_game()

    def _ask_question(self, index: int) -> None:
        """Broadcast a single question and handle timing/answers."""
        with self.lock:
            self.current_question_index = index
            self.current_question_start = time.time()
            self.current_question_responders = set()
            self.question_answered_event.clear()
            question = self.questions[index]
        # Format as single‑line pipe‑delimited question
        qtext = f"Question {index + 1}: {question['text']}"
        options_text = " | ".join([f"{opt}) {txt}" for opt, txt in question['options'].items()])
        full_question = f"{qtext} | {options_text} | Time limit: {self.question_duration} seconds"
        logging.info(f"Broadcasting question {index + 1}")
        self._broadcast(full_question)
        # Wait either for all answers or for timeout
        answered = self.question_answered_event.wait(self.question_duration)
        # Reveal correct answer
        correct_letter = question['correct']
        correct_text = question['options'][correct_letter]
        prefix = "" if answered else "Time's up! "
        self._broadcast(f"{prefix}Correct answer: {correct_letter}) {correct_text}")
        # Short pause before next question
        time.sleep(2)

    def _end_game(self) -> None:
        """Conclude the current quiz and broadcast final results."""
        with self.lock:
            if not self.game_active:
                return
            self.game_active = False
            scores = sorted(self.clients.values(), key=lambda x: x['score'], reverse=True)
        logging.info("Quiz game ended")
        # Build final leaderboard string
        leaderboard = "🏁 Quiz completed!\n🏆 FINAL LEADERBOARD 🏆\n"
        for idx, info in enumerate(scores, start=1):
            leaderboard += f"{idx}. {info['username']}: {info['score']} points\n"
        self._broadcast(leaderboard.strip())

    # -------------------------------------------------------------------------
    # Broadcast and send helpers
    # -------------------------------------------------------------------------
    def _broadcast(self, message: str) -> None:
        """Send a message to all connected clients."""
        with self.lock:
            for addr in list(self.clients.keys()):
                self._send(message, addr)

    def _broadcast_player_list(self) -> None:
        """Broadcast the list of connected players and their scores."""
        with self.lock:
            if not self.clients:
                return
            msg = "Connected players:\n"
            for info in self.clients.values():
                msg += f"- {info['username']} ({info['score']} points)\n"
        self._broadcast(msg.strip())

    def _broadcast_score_update(self, username: str, score: int) -> None:
        """Broadcast a score update and the current leaderboard."""
        self._broadcast(f"Score update: {username} now has {score} points!")
        self._broadcast_leaderboard()

    def _broadcast_leaderboard(self) -> None:
        """Broadcast the current leaderboard sorted by score."""
        with self.lock:
            if not self.clients:
                return
            sorted_clients = sorted(self.clients.values(), key=lambda x: x['score'], reverse=True)
            board = "📊 CURRENT LEADERBOARD 📊\n"
            for idx, info in enumerate(sorted_clients, start=1):
                board += f"{idx}. {info['username']}: {info['score']} points\n"
        self._broadcast(board.strip())

    def _send(self, message: str, addr: Tuple[str, int]) -> None:
        """Send a single UDP message to a client."""
        try:
            self.sock.sendto((message + '\n').encode('utf-8'), addr)
        except Exception as e:
            logging.error(f"Error sending to {addr}: {e}")


def main() -> None:
    """Entry point for launching the UDP quiz server."""
    print("=== UDP Quiz Server ===")
    server = UDPQuizServer()
    server.start()


if __name__ == '__main__':
    main()