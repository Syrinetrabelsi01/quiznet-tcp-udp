# CS411 Lab 4 - Multiplayer Quiz Game

## 🎯 Project Overview

This project implements a multiplayer quiz game system using both UDP and TCP socket programming with a Streamlit GUI. The system supports multiple clients connecting to a server, answering quiz questions in real-time, and competing on a live leaderboard.

## 📁 Project Structure

```
quiznet-tcp-udp/
├── udp_quiz/
│   ├── server_udp.py      # UDP server implementation
│   └── client_udp.py      # UDP client implementation
├── tcp_quiz/
│   ├── server_tcp.py      # TCP server implementation
│   └── client_tcp.py      # TCP client implementation
├── app.py                 # Streamlit GUI application
├── questions.txt          # Quiz questions database
└── run.md                # This instruction file
```

## 🚀 How to Run

### Prerequisites

1. **Python 3.7+** installed on your system
2. **Streamlit** installed for the GUI version
3. **Network access** between client and server machines

### Installation

1. **Install required packages:**
   ```bash
   pip install streamlit
   ```

2. **Navigate to the project directory:**
   ```bash
   cd quiznet-tcp-udp
   ```

### 🎮 Running the UDP Version

#### Start the UDP Server
```bash
python udp_quiz/server_udp.py
```
- Server will start on port 8888
- Logs will be saved to `udp_server.log`
- Server will wait for clients to connect

#### Connect UDP Clients
```bash
python udp_quiz/client_udp.py
```
- Enter server host (default: localhost)
- Enter server port (default: 8888)
- Enter your username when prompted
- Answer questions by typing a, b, c, or d

### 🔗 Running the TCP Version

#### Start the TCP Server
```bash
python tcp_quiz/server_tcp.py
```
- Server will start on port 8888
- Logs will be saved to `tcp_server.log`
- Server supports multiple concurrent clients

#### Connect TCP Clients
```bash
python tcp_quiz/client_tcp.py
```
- Enter server host (default: localhost)
- Enter server port (default: 8888)
- Enter your username when prompted
- Answer questions by typing a, b, c, or d

### 🌐 Running the Streamlit GUI

#### Start the Streamlit Application
```bash
streamlit run app.py
```
- GUI will be available at `http://localhost:8501`
- Access from other machines using your LAN IP: `http://YOUR_IP:8501`
- Connect to TCP server using the sidebar
- Register with a username
- Use the interactive interface to answer questions

#### Access from Other Devices
1. Find your computer's IP address:
   - Windows: `ipconfig`
   - Mac/Linux: `ifconfig`
2. Access from other devices: `http://YOUR_IP:8501`

## 🧪 Testing Scenarios

### 1. Basic Functionality Test
1. Start the TCP server
2. Connect 2-3 clients (terminal or GUI)
3. Verify all clients receive questions
4. Test answer submission and scoring
5. Check leaderboard updates

### 2. Simultaneous Answers Test
1. Start server with multiple clients
2. Have clients answer the same question quickly
3. Verify only the first correct answer gets points
4. Check that all clients see the correct answer

### 3. Timeout Test
1. Start a question
2. Wait for the 30-second timer to expire
3. Verify correct answer is revealed
4. Check that no more answers are accepted

### 4. Disconnection Test
1. Start server with multiple clients
2. Disconnect one client mid-game
3. Verify other clients continue playing
4. Check that disconnected client is removed from leaderboard

### 5. UDP Packet Loss Simulation
1. Use UDP version
2. Test with network interference
3. Verify graceful handling of lost packets
4. Check client reconnection capability

## 🔧 Configuration

### Server Configuration
- **Port**: 8888 (configurable in server files)
- **Question Duration**: 30 seconds per question
- **Client Timeout**: 60 seconds of inactivity
- **Max Questions**: 10 questions per game

### Client Configuration
- **Connection Timeout**: 10 seconds
- **Message Timeout**: 5 seconds
- **Username Length**: Maximum 20 characters

## 🐛 Common Issues and Fixes

### Connection Refused Error
**Problem**: `ConnectionRefusedError` when connecting to server
**Solution**: 
- Ensure server is running before starting clients
- Check that port 8888 is not blocked by firewall
- Verify server host address is correct

### Port Already in Use Error
**Problem**: `Address already in use` when starting server
**Solution**:
- Wait for previous server instance to fully close
- Use `netstat -an | findstr 8888` to check port usage
- Restart terminal/command prompt

### Streamlit Not Found Error
**Problem**: `streamlit: command not found`
**Solution**:
```bash
pip install streamlit
# Or if using conda:
conda install streamlit
```

### Questions File Not Found
**Problem**: Server can't load questions.txt
**Solution**:
- Ensure questions.txt is in the same directory as server files
- Check file permissions
- Verify file encoding is UTF-8

### GUI Not Updating
**Problem**: Streamlit interface not refreshing
**Solution**:
- Refresh the browser page
- Check browser console for errors
- Restart Streamlit application

### Network Connectivity Issues
**Problem**: Can't connect from other machines
**Solution**:
- Check firewall settings
- Ensure server is bound to 0.0.0.0 (all interfaces)
- Verify network connectivity between machines
- Use correct IP address for connection

## 📊 Performance Notes

### UDP Version
- **Pros**: Lower latency, faster for real-time applications
- **Cons**: No guaranteed delivery, packet loss possible
- **Best for**: Local network with good connectivity

### TCP Version
- **Pros**: Reliable delivery, ordered messages
- **Cons**: Higher latency, more overhead
- **Best for**: Unreliable networks, critical applications

### Streamlit GUI
- **Pros**: User-friendly interface, real-time updates
- **Cons**: Requires web browser, more resource intensive
- **Best for**: Interactive gameplay, multiple users

## 🔍 Debugging

### Enable Debug Logging
Add this to server files for more detailed logging:
```python
logging.basicConfig(level=logging.DEBUG)
```

### Check Server Logs
- UDP server: `udp_server.log`
- TCP server: `tcp_server.log`
- Streamlit: Check terminal output

### Network Testing
```bash
# Test port connectivity
telnet localhost 8888

# Check if port is listening
netstat -an | findstr 8888
```

## 📝 Additional Notes

- All communication uses UTF-8 encoding
- Questions are loaded from `questions.txt` at server startup
- Server automatically restarts games when clients are available
- Client disconnections are handled gracefully
- Score updates are broadcast to all connected clients
- Timer countdown is displayed in real-time

## 🎓 Educational Value

This project demonstrates:
- Socket programming with both UDP and TCP
- Multithreaded server architecture
- Real-time client-server communication
- Web application development with Streamlit
- Error handling and graceful disconnections
- Network protocol differences and trade-offs
