#!/usr/bin/env python3
"""
UDP Quiz Server with per-client question progression.

This server replicates the behaviour of the TCP quiz server but uses UDP
sockets.  Each client proceeds through the list of questions independently.
One client's answer does not affect the timing or questions for another
client.  When all clients have completed the quiz, a final leaderboard is
broadcast and the game does not automatically restart.  New clients who join
after the game has ended will be informed that the session is over.

Key features:
- Per-client question index, timer and finished state.
- Questions loaded from questions.txt with fallback sample question.
- Score updates and leaderboards broadcast to all clients.
- Clients removed after inactivity timeout (60 seconds).
- 'ping' / 'pong' handshake to verify connectivity.
"""

from __future__ import annotations

import os
import socket
import threading
import time
import logging
from typing import Dict, Tuple, List, Any

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('udp_server.log'),
        logging.StreamHandler()
    ]
)


class UDPQuizServer:
    """A UDP-based quiz server where each client progresses through the quiz independently."""

    def __init__(self, host: str = '0.0.0.0', port: int = 8888, question_duration: int = 15):
        """
        Initialise the UDP quiz server.

        :param host: bind address ('0.0.0.0' listens on all interfaces).
        :param port: UDP port.
        :param question_duration: seconds allowed per question.
        """
        self.host = host
        self.port = port
        self.question_duration = question_duration
        # Create UDP socket
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind((self.host, self.port))

        # Client state: mapping from address to info.
        # Each info dict contains:
        #  - username (str)
        #  - score (int)
        #  - last_seen (float)
        #  - connected (bool)
        #  - question_index (int) : next question number for this client
        #  - finished (bool)
        #  - timer_thread (threading.Thread | None)
        #  - question_start_time (float)
        self.clients: Dict[Tuple[str, int], Dict[str, Any]] = {}

        # Load quiz questions
        self.questions: List[Dict[str, Any]] = []
        self._load_questions()

        # Game state: whether the quiz has ended.  When True, no new games will start.
        self.game_over: bool = False

        # Concurrency
        self.lock = threading.RLock()
        self.stop_event = threading.Event()
        self.client_cleanup_thread: threading.Thread | None = None

        logging.info(f"UDP Quiz Server initialised on {self.host}:{self.port}")

    def _load_questions(self) -> None:
        """Load questions from questions.txt or use a fallback question."""
        script_dir = os.path.dirname(os.path.abspath(__file__))
        candidate_paths = [
            os.path.join(script_dir, 'questions.txt'),
            os.path.join(script_dir, '..', 'questions.txt'),
            os.path.join(script_dir, '..', 'tcp_quiz', 'questions.txt'),
        ]
        for path in candidate_paths:
            try:
                with open(path, 'r', encoding='utf-8') as file:
                    lines = [line.strip() for line in file.readlines() if line.strip()]
                for line in lines:
                    parts = line.split('|')
                    if len(parts) >= 6:
                        qid = parts[0].split(':')[0]
                        qtext = parts[0].split(':', 1)[1]
                        options: Dict[str, str] = {}
                        for opt in parts[1:5]:
                            letter = opt[0].lower()
                            body = opt[2:].lstrip(' )')
                            options[letter] = body
                        correct = parts[5].strip().lower()
                        self.questions.append({'id': qid, 'text': qtext, 'options': options, 'correct': correct})
                if self.questions:
                    logging.info(f"Loaded {len(self.questions)} questions from {os.path.basename(path)}")
                    return
            except FileNotFoundError:
                continue
            except Exception as e:
                logging.error(f"Error loading questions from {path}: {e}")
                self.questions = []
                return
        logging.error("questions.txt file not found; using a sample question.")
        self.questions = [
            {
                'id': '1',
                'text': 'What is UDP?',
                'options': {
                    'a': 'User Datagram Protocol',
                    'b': 'Universal Data Protocol',
                    'c': 'Unified Data Protocol',
                    'd': 'User Data Protocol'
                },
                'correct': 'a'
            }
        ]

    def start(self) -> None:
        """Start the server, receive messages and clean up inactive clients."""
        # Start receiver thread
        threading.Thread(target=self._receive_loop, daemon=True).start()
        # Start cleanup thread
        if self.client_cleanup_thread is None:
            self.client_cleanup_thread = threading.Thread(target=self._cleanup_loop, daemon=True)
            self.client_cleanup_thread.start()
        print(f"UDP Quiz Server running on {self.host}:{self.port}")
        print("Waiting for clients to connect...")
        try:
            while not self.stop_event.is_set():
                time.sleep(1)
        except KeyboardInterrupt:
            logging.info("Server interrupted by keyboard; shutting down.")
            self.stop_event.set()

    # -------------------------------------------------------------------------
    # Networking
    # -------------------------------------------------------------------------
    def _receive_loop(self) -> None:
        """Receive messages and dispatch to handlers."""
        while not self.stop_event.is_set():
            try:
                data, addr = self.sock.recvfrom(2048)
                message = data.decode('utf-8').strip()
                if not message:
                    continue
                # Split command and payload
                if ':' in message:
                    command, payload = message.split(':', 1)
                else:
                    command, payload = message, ''
                command = command.lower()
                if command == 'ping':
                    # Update last_seen if client exists and reply
                    with self.lock:
                        if addr in self.clients:
                            self.clients[addr]['last_seen'] = time.time()
                    self._send('pong', addr)
                elif command == 'join':
                    self._handle_join(payload.strip(), addr)
                elif command == 'answer':
                    self._handle_answer(payload.strip(), addr)
                else:
                    logging.warning(f"Unknown command '{command}' from {addr}")
            except Exception as e:
                logging.error(f"Error receiving message: {e}")

    def _send(self, message: str, addr: Tuple[str, int]) -> None:
        """Send a UDP message terminated with newline."""
        try:
            self.sock.sendto((message + '\n').encode('utf-8'), addr)
        except Exception as e:
            logging.error(f"Error sending to {addr}: {e}")

    def _broadcast(self, message: str) -> None:
        """Broadcast a message to all connected clients."""
        with self.lock:
            for addr in list(self.clients.keys()):
                self._send(message, addr)

    # -------------------------------------------------------------------------
    # Client handlers
    # -------------------------------------------------------------------------
    def _handle_join(self, username: str, addr: Tuple[str, int]) -> None:
        """Register a new client and start their quiz if the game is not over."""
        if not username:
            self._send('error:Invalid username', addr)
            return
        username = username.strip()
        with self.lock:
            # Remove existing client with same username
            to_remove = [a for a, info in self.clients.items() if info['username'] == username]
            for rem in to_remove:
                del self.clients[rem]
                logging.info(f"Removed existing client {rem} with username '{username}'")
            # Register new client
            self.clients[addr] = {
                'username': username,
                'score': 0,
                'last_seen': time.time(),
                'connected': True,
                'question_index': 0,
                'finished': False,
                'timer_thread': None,
                'question_start_time': 0.0
            }
        logging.info(f"Client {addr} joined as '{username}'")
        self._send(f'welcome:{username}', addr)
        self._broadcast_player_list()
        # If game already ended, tell client to wait
        if self.game_over:
            self._send("Game over! Please wait for the next session.", addr)
            return
        # Start first question for this client
        self._send_question_to_client(addr)

    def _handle_answer(self, answer: str, addr: Tuple[str, int]) -> None:
        """Process an answer from a client."""
        with self.lock:
            if addr not in self.clients:
                self._send('error:Not registered', addr)
                return
            client_info = self.clients[addr]
            if client_info.get('finished'):
                self._send('error:Quiz completed', addr)
                return
            idx = client_info.get('question_index', 0)
            if idx >= len(self.questions):
                # Should not happen, but mark finished
                client_info['finished'] = True
                if all(ci.get('finished', False) for ci in self.clients.values()):
                    self._end_game()
                else:
                    self._send('Quiz completed! Waiting for other players to finish...', addr)
                return
            # Normalize answer
            answer = answer.lower().strip()
            question = self.questions[idx]
            client_info['last_seen'] = time.time()
            # Evaluate answer
            correct_letter = question['correct']
            correct_text = question['options'][correct_letter]
            if answer == correct_letter:
                client_info['score'] += 10
                logging.info(f"Client {addr} ({client_info['username']}) answered correctly: {answer}")
                # Inform the client they were correct and award points, but do not
                # broadcast the score to other players mid-game.  The final
                # leaderboard will be shown once everyone has finished.
                self._send('correct:10 points', addr)
            else:
                logging.info(f"Client {addr} ({client_info['username']}) answered incorrectly: {answer}")
                self._send(f'incorrect:Correct answer was {correct_letter}) {correct_text}', addr)
            # Advance to next question
            client_info['question_index'] = idx + 1
            # If completed all questions
            if client_info['question_index'] >= len(self.questions):
                client_info['finished'] = True
                # If all clients finished, end game
                if all(ci.get('finished', False) for ci in self.clients.values()):
                    self._end_game()
                else:
                    # Notify client that they finished; others still playing
                    self._send('Quiz completed! Waiting for other players to finish...', addr)
            else:
                # Send next question to this client
                self._send_question_to_client(addr)

    # -------------------------------------------------------------------------
    # Per-client quiz functions
    # -------------------------------------------------------------------------
    def _send_question_to_client(self, addr: Tuple[str, int]) -> None:
        """Send the current question to a specific client and start their timer."""
        with self.lock:
            client_info = self.clients.get(addr)
            if not client_info or client_info.get('finished'):
                return
            idx = client_info.get('question_index', 0)
            # Sanity check
            if idx >= len(self.questions):
                client_info['finished'] = True
                if all(ci.get('finished', False) for ci in self.clients.values()):
                    self._end_game()
                else:
                    self._send('Quiz completed! Waiting for other players to finish...', addr)
                return
            question = self.questions[idx]
            question_text = f"Question {idx + 1}: {question['text']}"
            options_list = [f"{opt}) {text}" for opt, text in question['options'].items()]
            options_text = " | ".join(options_list)
            full_question = f"{question_text} | {options_text} | Time limit: {self.question_duration} seconds"
            # Record start time
            client_info['question_start_time'] = time.time()
            # Start timer thread for this question
            timer_thread = threading.Thread(target=self._question_timeout_handler, args=(addr, idx), daemon=True)
            client_info['timer_thread'] = timer_thread
            timer_thread.start()
        self._send(full_question, addr)

    def _question_timeout_handler(self, addr: Tuple[str, int], question_index: int) -> None:
        """Handle timeout for a client's question."""
        time.sleep(self.question_duration)
        with self.lock:
            client_info = self.clients.get(addr)
            if not client_info:
                return
            # If client has moved on or finished, do nothing
            if client_info.get('finished') or client_info.get('question_index') != question_index:
                return
            # Client did not answer in time; reveal correct answer and advance
            question = self.questions[question_index]
            correct_letter = question['correct']
            correct_text = question['options'][correct_letter]
            self._send(f"Time's up! Correct answer: {correct_letter}) {correct_text}", addr)
            # Advance question
            client_info['question_index'] = question_index + 1
            if client_info['question_index'] >= len(self.questions):
                client_info['finished'] = True
                if all(ci.get('finished', False) for ci in self.clients.values()):
                    self._end_game()
                else:
                    self._send('Quiz completed! Waiting for other players to finish...', addr)
            else:
                # Send next question
                self._send_question_to_client(addr)

    # -------------------------------------------------------------------------
    # Game end and leaderboards
    # -------------------------------------------------------------------------
    def _end_game(self) -> None:
        """Conclude the quiz for all clients and broadcast final leaderboard."""
        """
        Conclude the quiz for all clients and broadcast the final leaderboard.

        This method sets the `game_over` flag, logs that the game has ended,
        builds a leaderboard sorted by score, and sends a clear final results
        message to every connected client.  To improve the client display,
        each line of the leaderboard is prefaced with a trophy emoji so the
        client recognizes it as part of the leaderboard (the client prints
        any message starting with 🏆 directly without prefixing it with 📢).

        After broadcasting, all client scores are reset so that if a new
        session is manually started later, everyone begins at zero.  The
        `game_over` flag prevents new clients from joining an ended game.
        """
        with self.lock:
            # Do not end the game twice
            if self.game_over:
                return
            self.game_over = True
            # Gather clients sorted by score (descending)
            sorted_clients = sorted(self.clients.values(), key=lambda x: x['score'], reverse=True)
        logging.info("Quiz game ended")
        # Inform clients that the quiz is complete before showing the leaderboard
        self._broadcast("Quiz completed! Final results:")
        # Build list of leaderboard lines, prefixing each with a trophy emoji
        leaderboard_lines: List[str] = []
        leaderboard_lines.append("🏆 FINAL LEADERBOARD 🏆")
        for position, info in enumerate(sorted_clients, start=1):
            leaderboard_lines.append(f"🏆 {position}. {info['username']}: {info['score']} points")
        # Send each leaderboard line separately.  Each line begins with 🏆 so
        # the client prints it without an extra 📢 prefix.
        for line in leaderboard_lines:
            self._broadcast(line)
        # Reset scores to zero for all clients (in case another game starts later)
        with self.lock:
            for info in self.clients.values():
                info['score'] = 0

    def _broadcast_player_list(self) -> None:
        """Broadcast list of connected players and their scores."""
        with self.lock:
            if not self.clients:
                return
            msg = "Connected players:\n"
            for info in self.clients.values():
                msg += f"- {info['username']} ({info['score']} points)\n"
        # Broadcast connected players without showing the leaderboard until the game ends.
        self._broadcast(msg.strip())

    def _broadcast_score_update(self, username: str, score: int) -> None:
        """Broadcast a score update and current leaderboard."""
        self._broadcast(f"Score update: {username} now has {score} points!")
        self._broadcast_leaderboard()

    def _broadcast_leaderboard(self) -> None:
        """Broadcast current leaderboard sorted by score."""
        with self.lock:
            if not self.clients:
                return
            sorted_clients = sorted(self.clients.values(), key=lambda x: x['score'], reverse=True)
            board = "📊 CURRENT LEADERBOARD 📊\n"
            for idx, info in enumerate(sorted_clients, start=1):
                board += f"{idx}. {info['username']}: {info['score']} points\n"
        self._broadcast(board.strip())

    # -------------------------------------------------------------------------
    # Cleanup
    # -------------------------------------------------------------------------
    def _cleanup_loop(self) -> None:
        """Remove inactive clients periodically."""
        idle_timeout = 60
        while not self.stop_event.is_set():
            time.sleep(10)
            with self.lock:
                now = time.time()
                to_remove: List[Tuple[str, int]] = []
                for addr, info in list(self.clients.items()):
                    if info.get('connected', False) and now - info.get('last_seen', 0) > idle_timeout:
                        to_remove.append(addr)
                if to_remove:
                    for addr in to_remove:
                        username = self.clients[addr]['username']
                        del self.clients[addr]
                        logging.info(f"Removed inactive client {addr} ({username}) due to timeout")
                    # Broadcast updated player list and leaderboard if clients remain
                    if self.clients:
                        self._broadcast_player_list()
                    else:
                        # If all clients have left, we do not reset game_over; session remains ended
                        pass


def main() -> None:
    """Entry point to start the UDP quiz server."""
    print("=== UDP Quiz Server ===")
    server = UDPQuizServer()
    server.start()


if __name__ == '__main__':
    main()