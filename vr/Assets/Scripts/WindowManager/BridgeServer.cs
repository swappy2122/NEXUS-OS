using System;
using System.Collections.Generic;
using System.Net;
using System.Net.Sockets;
using System.Text;
using System.Threading;
using UnityEngine;

namespace Nexus.VR.WindowManager
{
    /// <summary>
    /// TCP bridge server that listens for connections from the Python
    /// <c>VRBridgeClient</c> and provides bidirectional communication.
    ///
    /// Protocol: 4-byte big-endian length prefix + UTF-8 JSON body.
    ///
    /// Runs a background listener thread and marshals received commands
    /// onto the Unity main thread via a concurrent queue.
    /// </summary>
    public class BridgeServer : MonoBehaviour, IBridgeServer
    {
        // ── state ───────────────────────────────────────────────────────

        private TcpListener listener;
        private TcpClient connectedClient;
        private NetworkStream clientStream;
        private Thread listenerThread;
        private Thread readThread;
        private volatile bool isRunning;
        private volatile bool isConnected;

        // Thread-safe queue for dispatching commands to the main thread
        private readonly Queue<WindowCommandData> pendingCommands = new();
        private readonly object commandLock = new();

        // ── IBridgeServer properties ────────────────────────────────────

        public bool IsConnected => isConnected;

        // ── events ──────────────────────────────────────────────────────

        public event Action<WindowCommandData> OnCommandReceived;
        public event Action OnClientConnected;
        public event Action OnClientDisconnected;

        // ── lifecycle ───────────────────────────────────────────────────

        public void StartListening(int port)
        {
            if (isRunning)
            {
                Debug.LogWarning("[NEXUS Bridge] Server already running");
                return;
            }

            isRunning = true;

            listenerThread = new Thread(() => ListenerLoop(port))
            {
                IsBackground = true,
                Name = "NexusBridgeListener",
            };
            listenerThread.Start();

            Debug.Log($"[NEXUS Bridge] Server started on port {port}");
        }

        public void Stop()
        {
            isRunning = false;

            try { connectedClient?.Close(); } catch { }
            try { listener?.Stop(); } catch { }

            connectedClient = null;
            clientStream = null;
            isConnected = false;

            Debug.Log("[NEXUS Bridge] Server stopped");
        }

        private void OnDestroy()
        {
            Stop();
        }

        // ── main thread dispatch ────────────────────────────────────────

        private void Update()
        {
            // Dispatch queued commands on the main thread
            lock (commandLock)
            {
                while (pendingCommands.Count > 0)
                {
                    var command = pendingCommands.Dequeue();
                    try
                    {
                        OnCommandReceived?.Invoke(command);
                    }
                    catch (Exception ex)
                    {
                        Debug.LogError($"[NEXUS Bridge] Error handling command: {ex.Message}");
                    }
                }
            }
        }

        // ── sending events ──────────────────────────────────────────────

        public void SendEvent(WindowEventData windowEvent)
        {
            if (!isConnected || clientStream == null || !clientStream.CanWrite)
            {
                Debug.LogWarning("[NEXUS Bridge] Cannot send — no connected client");
                return;
            }

            try
            {
                string json = JsonUtility.ToJson(windowEvent);
                byte[] body = Encoding.UTF8.GetBytes(json);
                byte[] lengthPrefix = BitConverter.GetBytes(IPAddress.HostToNetworkOrder(body.Length));

                clientStream.Write(lengthPrefix, 0, 4);
                clientStream.Write(body, 0, body.Length);
                clientStream.Flush();
            }
            catch (Exception ex)
            {
                Debug.LogError($"[NEXUS Bridge] Send failed: {ex.Message}");
                HandleDisconnect();
            }
        }

        // ── background threads ──────────────────────────────────────────

        private void ListenerLoop(int port)
        {
            try
            {
                listener = new TcpListener(IPAddress.Loopback, port);
                listener.Start();

                Debug.Log($"[NEXUS Bridge] Listening on 127.0.0.1:{port}");

                while (isRunning)
                {
                    if (!listener.Pending())
                    {
                        Thread.Sleep(100);
                        continue;
                    }

                    // Accept one client at a time
                    if (connectedClient != null)
                    {
                        try { connectedClient.Close(); } catch { }
                    }

                    connectedClient = listener.AcceptTcpClient();
                    connectedClient.NoDelay = true;
                    clientStream = connectedClient.GetStream();
                    isConnected = true;

                    Debug.Log("[NEXUS Bridge] Python client connected");

                    // Notify on main thread (via pending commands mechanism)
                    // We'll use a simple flag check in Update() instead
                    MainThreadDispatch(() => OnClientConnected?.Invoke());

                    // Start reading from this client
                    readThread = new Thread(ReadLoop)
                    {
                        IsBackground = true,
                        Name = "NexusBridgeReader",
                    };
                    readThread.Start();

                    // Wait for read thread to finish (client disconnected)
                    readThread.Join();
                }
            }
            catch (SocketException ex)
            {
                if (isRunning)
                {
                    Debug.LogError($"[NEXUS Bridge] Listener error: {ex.Message}");
                }
            }
            finally
            {
                try { listener?.Stop(); } catch { }
            }
        }

        private void ReadLoop()
        {
            byte[] lengthBuffer = new byte[4];

            try
            {
                while (isRunning && isConnected && clientStream != null && clientStream.CanRead)
                {
                    // Read 4-byte length prefix
                    int bytesRead = ReadExact(clientStream, lengthBuffer, 0, 4);
                    if (bytesRead < 4)
                    {
                        break; // Connection closed
                    }

                    int bodyLength = IPAddress.NetworkToHostOrder(BitConverter.ToInt32(lengthBuffer, 0));
                    if (bodyLength <= 0 || bodyLength > 1_048_576) // 1 MB sanity limit
                    {
                        Debug.LogWarning($"[NEXUS Bridge] Invalid message length: {bodyLength}");
                        break;
                    }

                    // Read JSON body
                    byte[] bodyBuffer = new byte[bodyLength];
                    bytesRead = ReadExact(clientStream, bodyBuffer, 0, bodyLength);
                    if (bytesRead < bodyLength)
                    {
                        break;
                    }

                    string json = Encoding.UTF8.GetString(bodyBuffer);

                    try
                    {
                        var command = JsonUtility.FromJson<WindowCommandData>(json);
                        if (command != null)
                        {
                            lock (commandLock)
                            {
                                pendingCommands.Enqueue(command);
                            }
                        }
                    }
                    catch (Exception ex)
                    {
                        Debug.LogWarning($"[NEXUS Bridge] Failed to parse command: {ex.Message}");
                    }
                }
            }
            catch (Exception ex)
            {
                if (isRunning)
                {
                    Debug.LogWarning($"[NEXUS Bridge] Read error: {ex.Message}");
                }
            }
            finally
            {
                HandleDisconnect();
            }
        }

        // ── helpers ─────────────────────────────────────────────────────

        private static int ReadExact(NetworkStream stream, byte[] buffer, int offset, int count)
        {
            int totalRead = 0;
            while (totalRead < count)
            {
                int read = stream.Read(buffer, offset + totalRead, count - totalRead);
                if (read == 0)
                {
                    return totalRead; // Connection closed
                }
                totalRead += read;
            }
            return totalRead;
        }

        private void HandleDisconnect()
        {
            if (!isConnected) return;

            isConnected = false;
            try { connectedClient?.Close(); } catch { }
            connectedClient = null;
            clientStream = null;

            Debug.Log("[NEXUS Bridge] Python client disconnected");
            MainThreadDispatch(() => OnClientDisconnected?.Invoke());
        }

        // Simple main-thread dispatch helper using a secondary queue
        private readonly Queue<Action> mainThreadActions = new();
        private readonly object mainThreadLock = new();

        private void MainThreadDispatch(Action action)
        {
            lock (mainThreadLock)
            {
                mainThreadActions.Enqueue(action);
            }
        }

        private void LateUpdate()
        {
            lock (mainThreadLock)
            {
                while (mainThreadActions.Count > 0)
                {
                    try
                    {
                        mainThreadActions.Dequeue()?.Invoke();
                    }
                    catch (Exception ex)
                    {
                        Debug.LogError($"[NEXUS Bridge] Main thread action error: {ex.Message}");
                    }
                }
            }
        }
    }
}
