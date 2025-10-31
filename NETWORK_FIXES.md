# TCP Quiz - Connection Fixes

## Summary of Issues Fixed

### Main Issue: TCP Message Boundary Problem

**Problem:** TCP is a stream protocol, not a message protocol. This means that when you send two messages quickly, they might arrive as one combined message, or a single message might arrive split across multiple `recv()` calls. The original code was not handling this correctly.

**Solution:** Implemented proper message framing using newline delimiters (`\n`):

- All messages now end with a newline character
- Both server and client use message buffers to accumulate partial messages
- Messages are only processed when a complete line (ending with `\n`) is received

### Changes Made

#### Server (`server_tcp.py`):

1. Added message buffer in `handle_client()` method to accumulate partial messages
2. Modified message receiving to split on `\n` delimiter
3. Updated `send_message_to_client()` to append `\n` to all outgoing messages

#### Client (`client_tcp.py`):

1. Added `message_buffer` attribute to store partial messages
2. Modified `receive_loop()` to buffer incoming data and process only complete messages
3. Updated `send_message()` to append `\n` to all outgoing messages
4. Improved response handling in `connect_to_server()` and `register_username()` to strip whitespace

## Other Network Considerations

### Firewall Issues

If connections still fail between different machines, check:

1. **Windows Firewall:**

   - The server needs to allow incoming connections on port 8888
   - Client needs to allow outgoing connections to port 8888
   - Add Python or the specific script to firewall exceptions

2. **To open Windows Firewall for the server:**

   ```powershell
   New-NetFirewallRule -DisplayName "TCP Quiz Server" -Direction Inbound -LocalPort 8888 -Protocol TCP -Action Allow
   ```

3. **Antivirus Software:**
   - Some antivirus software may block socket connections
   - Consider adding exceptions for Python scripts

### Network Configuration

1. **Server IP Address:**

   - When connecting from another machine, use the server's actual IP address, not `localhost`
   - Find your server's IP with: `ipconfig` (Windows) or `ifconfig` (Linux/Mac)
   - Use that IP when running the client

2. **Same Network:**

   - Ensure both machines are on the same network (local network or same WiFi)
   - If not on same network, you'll need port forwarding or VPN

3. **Testing Locally First:**
   - Test on the same machine first (use `localhost` or `127.0.0.1`)
   - Then test between machines on the same network

## How to Test

### Step 1: Start the Server

```bash
cd quiznet-tcp-udp/tcp_quiz
python server_tcp.py
```

### Step 2: Start the Client (on another machine)

```bash
cd quiznet-tcp-udp/tcp_quiz
python client_tcp.py
```

When prompted:

- Server host: Enter the server's IP address (e.g., `192.168.1.100`)
- Server port: `8888` (or press Enter for default)

### Step 3: Troubleshooting

If connection still fails:

1. **Check if server is listening:**

   ```powershell
   netstat -an | findstr 8888
   ```

   Should show: `TCP 0.0.0.0:8888 LISTENING`

2. **Test with telnet:**

   ```bash
   telnet <server-ip> 8888
   ```

   If telnet connects, the port is open

3. **Check Windows Firewall:**

   - Go to Windows Security → Firewall & network protection
   - Check if inbound rules are blocking port 8888

4. **Try disabling firewall temporarily** (for testing only)

## Common Error Messages

- **"Connection refused"**: Server is not running or firewall is blocking
- **"Connection timeout"**: Network issue or wrong IP address
- **"Address already in use"**: Port 8888 is already in use (close other instances)

## Additional Notes

The code now properly handles:

- ✅ Multiple messages arriving together
- ✅ Single message split across multiple recv() calls
- ✅ Partial message buffering
- ✅ Multi-client connections
- ✅ Thread-safe operations

The server binds to `0.0.0.0` which allows connections from any interface, which is correct for network connections.
