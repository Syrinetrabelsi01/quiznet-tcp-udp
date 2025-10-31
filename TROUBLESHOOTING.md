# TCP Quiz Troubleshooting Guide

## Quick Fix Summary

The main issue with your code was **TCP message boundary handling**. I've fixed it by implementing proper message framing. However, if you're still having connection issues between different machines, here's what to check:

## Step-by-Step Connection Guide

### 1. Find Your Server's IP Address

On the server machine, open PowerShell and run:

```powershell
ipconfig
```

Look for your active network adapter (usually Wi-Fi or Ethernet) and note the IPv4 Address. For example: `192.168.1.100`

### 2. Configure Windows Firewall

#### Option A: Use PowerShell (Recommended)

On the **server machine**, run as Administrator:

```powershell
New-NetFirewallRule -DisplayName "TCP Quiz Server" -Direction Inbound -LocalPort 8888 -Protocol TCP -Action Allow
```

#### Option B: Use Windows GUI

1. Open Windows Defender Firewall
2. Click "Advanced settings"
3. Click "Inbound Rules"
4. Click "New Rule..."
5. Select "Port" → Next
6. Select "TCP", enter port "8888" → Next
7. Select "Allow the connection" → Next
8. Check all profiles → Next
9. Name it "TCP Quiz Server" → Finish

### 3. Start the Server

```bash
cd quiznet-tcp-udp\tcp_quiz
python server_tcp.py
```

You should see:

```
TCP Quiz Server started on 0.0.0.0:8888
Waiting for clients to connect...
```

### 4. Start the Client (on another machine)

```bash
cd quiznet-tcp-udp\tcp_quiz
python client_tcp.py
```

When prompted:

- **Server host:** Enter the server's IP address (e.g., `192.168.1.100`)
- **Server port:** Press Enter (default is 8888)

## Common Issues & Solutions

### Issue 1: "Connection refused"

**Cause:** Server is not running or firewall is blocking

**Solution:**

1. Verify server is running on the server machine
2. Check firewall rules (see Step 2 above)
3. Run `netstat -an | findstr 8888` on server - should show `LISTENING`

### Issue 2: "Connection timeout"

**Cause:** Wrong IP address or machines not on same network

**Solution:**

1. Verify you're using the correct IP address
2. Both machines must be on the same network (WiFi or LAN)
3. Try pinging the server: `ping <server-ip>`

### Issue 3: "Address already in use"

**Cause:** Port 8888 is already in use

**Solution:**

1. Close other instances of the server
2. Or change the port in both server and client

### Issue 4: Connection works locally but not from another machine

**Cause:** Firewall is blocking

**Solution:**

1. Check Windows Firewall inbound rules for port 8888
2. Temporarily disable firewall to test (not recommended for production)
3. Check if antivirus is blocking the connection

## Testing Connection

### Test 1: Check if server is listening

On the **server machine**, run:

```powershell
netstat -an | findstr 8888
```

Expected output:

```
TCP    0.0.0.0:8888           0.0.0.0:0              LISTENING
```

### Test 2: Test with telnet

On the **client machine**, run:

```bash
telnet <server-ip> 8888
```

If it connects, the port is open. Type anything and press Enter. The server should respond (or disconnect if it doesn't understand the message).

### Test 3: Ping test

On the **client machine**, run:

```powershell
ping <server-ip>
```

Should get replies from the server.

## Network Requirements

- Both machines must be on the same local network
- Server firewall must allow incoming connections on port 8888
- Router should allow local communication (most routers do by default)

## Alternative: Use Same Machine for Testing

To verify the code works first, test locally:

1. Start server: `python server_tcp.py`
2. Start client in another terminal: `python client_tcp.py`
3. When prompted for server host, use: `localhost`
4. When prompted for port, press Enter (default 8888)

If this works but remote connection doesn't, it's a firewall/network issue, not a code issue.

## What Was Fixed

The code had a critical bug with TCP message handling:

### Before (Broken):

- Messages could arrive combined or split
- No message boundaries
- `recv()` might read multiple messages or partial messages

### After (Fixed):

- All messages end with newline character
- Both server and client buffer partial messages
- Messages only processed when complete
- Handles multiple clients correctly

## Still Having Issues?

1. Check server logs in `tcp_server.log`
2. Verify both machines can ping each other
3. Try disabling Windows Firewall temporarily (just for testing)
4. Check antivirus settings
5. Make sure you're using the correct IP address

The code is now correct and should work as long as the network and firewall are configured properly.
