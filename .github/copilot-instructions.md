# AI Development Guide for QuizNet TCP/UDP

## Project Overview
This is a multiplayer quiz game system implemented in Python with both TCP and UDP variants, plus a Streamlit GUI. The system demonstrates network programming concepts through an interactive quiz game.

## Core Architecture

### Components
- **TCP Implementation** (`tcp_quiz/`)
  - `server_tcp.py`: Threaded TCP server handling multiple clients
  - `client_tcp.py`: TCP client with terminal interface
  - `questions.txt`: Quiz questions database

- **UDP Implementation** (`udp_quiz/`)
  - `server_udp.py`: UDP server with connectionless protocol
  - `client_udp.py`: UDP client implementation

- **GUI Interface** (`app.py`)
  - Streamlit-based web interface
  - Real-time question display and scoring
  - Leaderboard visualization

### Communication Patterns
- **TCP Protocol**:
  - Uses newline-delimited messages ('\n')
  - Implements message buffering for partial receives
  - Example: `message.encode('utf-8') + b'\n'` for sending

- **UDP Protocol**:
  - Uses fixed-size datagrams (1024 bytes)
  - Handles packet loss gracefully
  - Example: `socket.recvfrom(1024)` for receiving

## Development Workflows

### Running the System
1. Start server (TCP/UDP):
   ```bash
   python tcp_quiz/server_tcp.py  # or udp_quiz/server_udp.py
   ```
2. Launch client(s):
   ```bash
   python tcp_quiz/client_tcp.py  # or udp_quiz/client_udp.py
   ```
3. For GUI:
   ```bash
   streamlit run app.py
   ```

### Testing Patterns
- Test question timer expiration (30-second window)
- Verify concurrent client handling
- Check score updates and leaderboard
- Validate disconnection handling

## Key Design Patterns

### Message Format
```python
{
    'type': 'question|feedback|timeout|leaderboard|game_start|game_end',
    'message': 'content',
    # Additional fields based on type
    'number': int,  # for questions
    'total': int,   # for questions
    'scores': []    # for leaderboard
}
```

### Critical Files
- `tcp_quiz/server_tcp.py`: Main server implementation
- `tcp_quiz/questions.txt`: Question database format
- `app.py`: Streamlit GUI architecture

## Common Pitfalls
1. TCP message boundaries must use newline delimiters
2. UDP packet size should not exceed 1024 bytes
3. Always handle socket timeouts gracefully
4. Use locks for thread-safe score updates

## Dependencies
- Python 3.7+
- Streamlit for GUI
- Basic socket library for networking
- Threading for concurrency

## Testing Guide
See `run.md` for comprehensive test scenarios and network fixes in `NETWORK_FIXES.md` and `TROUBLESHOOTING.md`.