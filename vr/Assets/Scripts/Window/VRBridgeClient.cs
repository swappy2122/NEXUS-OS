using System;
using System.Collections.Concurrent;
using System.Net.WebSockets;
using System.Net.Http;
using System.Net.Http.Headers;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using UnityEngine;

namespace Nexus.VR.Window
{
    /// <summary>
    /// Unity-side WebSocket client that connects to the Python VRBridge server.
    ///
    /// Translates:
    ///   Incoming JSON → <see cref="VRWindowManager.HandleCommand"/>
    ///   Outgoing events from VRWindowManager → WebSocket send
    ///
    /// I/O runs on a background thread; incoming messages are dispatched
    /// to the Unity main thread via a concurrent queue processed in Update().
    /// </summary>
    public class VRBridgeClient : MonoBehaviour
    {
        [Header("Connection")]
        [SerializeField] private string serverUri = "ws://127.0.0.1:8000/ws/v1/vr";
        [SerializeField] private float reconnectInitialDelaySeconds = 1.0f;
        [SerializeField] private float reconnectMaxDelaySeconds = 30.0f;
        [SerializeField] private float reconnectJitterSeconds = 0.25f;
        [SerializeField] private int maxReconnectAttempts = 8;
        [SerializeField] private float heartbeatIntervalSeconds = 15.0f;
        [SerializeField] private float heartbeatTimeoutSeconds = 45.0f;
        [SerializeField] private bool autoConnect = true;
        [SerializeField] private string stateEndpointUri = "";
        [SerializeField] private string workspaceEndpointUri = "";

        [Header("References")]
        [SerializeField] private VRWindowManager windowManager;

        // ── State ───────────────────────────────────────────────────────

        private ClientWebSocket _ws;
        private CancellationTokenSource _cts;
        private readonly ConcurrentQueue<string> _incomingQueue = new();
        private readonly ConcurrentQueue<ConnectionState> _stateEvents = new();
        private readonly ConcurrentQueue<bool> _establishedEvents = new();
        private readonly object _stateLock = new();
        private Task _connectTask;
        private Task _receiveTask;
        private Task _snapshotTask;
        private HttpClient _httpClient;
        private CancellationTokenSource _snapshotCts;
        private readonly ConcurrentQueue<SnapshotResult> _snapshotResults = new();
        private bool _snapshotInFlight;
        private long _connectionEpoch;
        private string _sessionToken;
        private bool _shutdownRequested;
        private int _reconnectAttempt;
        private float _heartbeatTimer;
        private DateTime _lastHeartbeatActivityUtc = DateTime.UtcNow;
        private float _reconnectTimer;
        private ConnectionState _state = ConnectionState.Disconnected;

        private sealed class SnapshotResult
        {
            public long epoch;
            public VRStateSnapshot state;
            public VRWorkspaceSnapshot workspace;
            public string error;
        }

        public enum ConnectionState
        {
            Disconnected,
            Connecting,
            Connected,
            Reconnecting,
            AuthenticationFailed,
            Stopped
        }

        public event Action<ConnectionState> OnConnectionStateChanged;
        public event Action<bool> OnConnectionEstablished;
        public event Action<string> OnProtocolMessage;

        /// <summary>Whether the client is currently connected to the Python bridge.</summary>
        public bool IsConnected => State == ConnectionState.Connected;
        public ConnectionState State => _state;
        public bool HasSessionToken => !string.IsNullOrEmpty(_sessionToken);

        /// <summary>
        /// Supply a short-lived token obtained by the application's trusted bootstrap flow.
        /// The token is retained only in memory and is never logged.
        /// </summary>
        public void SetSessionToken(string token)
        {
            _sessionToken = string.IsNullOrWhiteSpace(token) ? null : token.Trim();
            if (_state == ConnectionState.AuthenticationFailed && HasSessionToken)
            {
                _reconnectAttempt = 0;
                _reconnectTimer = 0f;
                SetState(ConnectionState.Disconnected);
            }
        }

        // ── Unity Lifecycle ─────────────────────────────────────────────

        private void Start()
        {
            if (windowManager == null)
            {
                windowManager = FindObjectOfType<VRWindowManager>();
            }

            // Subscribe to outgoing events from VRWindowManager
            if (windowManager != null)
            {
                windowManager.OnWindowEventJson += SendEvent;
            }

            if (autoConnect)
            {
                Connect();
            }
        }

        private void Update()
        {
            while (_stateEvents.TryDequeue(out ConnectionState stateEvent))
            {
                OnConnectionStateChanged?.Invoke(stateEvent);
            }
            while (_establishedEvents.TryDequeue(out bool established))
            {
                OnConnectionEstablished?.Invoke(established);
                if (established)
                {
                    RequestStateResynchronization();
                }
            }

            while (_snapshotResults.TryDequeue(out SnapshotResult result))
            {
                if (result.epoch != _connectionEpoch || !IsConnected)
                {
                    continue;
                }
                _snapshotInFlight = false;
                if (result.state == null || result.state.windows == null || result.workspace == null)
                {
                    Debug.LogWarning("[NEXUS Bridge] Ignored malformed VR snapshot; preserving current state");
                    continue;
                }
                if (!string.IsNullOrEmpty(result.error))
                {
                    Debug.LogWarning($"[NEXUS Bridge] VR snapshot unavailable: {result.error}");
                    continue;
                }
                if (windowManager != null)
                {
                    windowManager.ApplyStateSnapshot(result.state);
                }
            }

            // Dispatch incoming messages on the main thread
            while (_incomingQueue.TryDequeue(out string message))
            {
                HandleIncomingMessage(message);
            }

            if (IsConnected)
            {
                _heartbeatTimer += Time.deltaTime;
                if (_heartbeatTimer >= heartbeatIntervalSeconds)
                {
                    _heartbeatTimer = 0f;
                    _ = SendHeartbeatAsync();
                }

                if ((float)(DateTime.UtcNow - _lastHeartbeatActivityUtc).TotalSeconds > heartbeatTimeoutSeconds)
                {
                    Debug.LogWarning("[NEXUS Bridge] Heartbeat timeout");
                    HandleDisconnect(true, "Heartbeat timeout");
                }
            }
            else if (autoConnect && State == ConnectionState.Reconnecting)
            {
                _reconnectTimer += Time.deltaTime;
                if (_reconnectTimer >= NextReconnectDelay())
                {
                    _reconnectTimer = 0f;
                    Connect();
                }
            }
        }

        private void OnDestroy()
        {
            _shutdownRequested = true;
            Disconnect();
            _snapshotCts?.Cancel();
            _snapshotCts?.Dispose();
            _httpClient?.Dispose();

            if (windowManager != null)
            {
                windowManager.OnWindowEventJson -= SendEvent;
            }
        }

        // ── Public API ──────────────────────────────────────────────────

        /// <summary>Initiate connection to the Python VRBridge WebSocket server.</summary>
        public void Connect()
        {
            if (_shutdownRequested || IsConnected || State == ConnectionState.Connecting)
            {
                return;
            }

            if (!HasSessionToken)
            {
                SetState(ConnectionState.AuthenticationFailed);
                Debug.LogWarning("[NEXUS Bridge] No session token configured; connection stopped");
                return;
            }

            _connectTask = ConnectAsync();
        }

        private async Task ConnectAsync()
        {
            SetState(_reconnectAttempt == 0 ? ConnectionState.Connecting : ConnectionState.Reconnecting);
            _cts?.Cancel();
            _cts?.Dispose();
            _cts = new CancellationTokenSource();
            var socket = new ClientWebSocket();
            socket.Options.SetRequestHeader("Authorization", "Bearer " + _sessionToken);

            try
            {
                await socket.ConnectAsync(new Uri(serverUri), _cts.Token);
                _ws = socket;
                _connectionEpoch++;
                _reconnectAttempt = 0;
                _reconnectTimer = 0f;
                _heartbeatTimer = 0f;
                _lastHeartbeatActivityUtc = DateTime.UtcNow;
                SetState(ConnectionState.Connected);
                NotifyEstablished(true);
                _receiveTask = ReceiveLoop(socket, _cts.Token);
            }
            catch (OperationCanceledException)
            {
                socket.Dispose();
            }
            catch (WebSocketException ex)
            {
                bool authenticationFailure = socket.CloseStatus == WebSocketCloseStatus.PolicyViolation;
                socket.Dispose();
                HandleConnectFailure(authenticationFailure,
                    "WebSocket connection failed");
            }
            catch (Exception)
            {
                socket.Dispose();
                HandleConnectFailure(false, "WebSocket connection failed");
            }
        }

        /// <summary>Gracefully disconnect from the Python VRBridge.</summary>
        public void Disconnect()
        {
            _shutdownRequested = true;
            SetState(ConnectionState.Stopped);
            _cts?.Cancel();
            _snapshotCts?.Cancel();
            _snapshotCts = null;
            _snapshotInFlight = false;

            if (_ws != null)
            {
                try
                {
                    if (_ws.State == WebSocketState.Open || _ws.State == WebSocketState.CloseReceived)
                    {
                        _ = _ws.CloseAsync(
                            WebSocketCloseStatus.NormalClosure,
                            "Client shutting down",
                            CancellationToken.None
                        );
                    }
                }
                catch (Exception)
                {
                    // Suppress — we're shutting down
                }

                _ws.Dispose();
                _ws = null;
            }
        }

        /// <summary>Send an authenticated AI prompt through the existing VR socket.</summary>
        public async void SendAIRequest(string prompt)
        {
            if (!IsConnected || _ws == null || _ws.State != WebSocketState.Open
                || string.IsNullOrWhiteSpace(prompt)) return;
            AIRequestPayload payload = new AIRequestPayload
            {
                prompt = prompt,
                agent_role = "supervisor",
                user_message_id = "usr_" + Guid.NewGuid().ToString("N").Substring(0, 8)
            };
            NexusMessage<AIRequestPayload> message = NexusMessageParser.CreateMessage(
                NexusProtocol.TypeAIRequest,
                NexusProtocol.TopicAI,
                payload);
            try
            {
                byte[] bytes = Encoding.UTF8.GetBytes(message.ToJson());
                await _ws.SendAsync(new ArraySegment<byte>(bytes), WebSocketMessageType.Text, true, _cts.Token);
            }
            catch (Exception)
            {
                HandleDisconnect(true, "AI request send failed");
            }
        }

        /// <summary>
        /// Send a serialized WindowEvent JSON string to the Python bridge.
        /// Called by VRWindowManager via the <see cref="VRWindowManager.OnWindowEventJson"/> event.
        /// </summary>
        public async void SendEvent(string eventJson)
        {
            if (!IsConnected || _ws == null || _ws.State != WebSocketState.Open)
            {
                return;
            }

            try
            {
                if (!NexusMessageParser.TryConvertWindowEvent(eventJson, out string protocolJson))
                {
                    Debug.LogWarning("[NEXUS Bridge] Ignored unsupported legacy window event");
                    return;
                }
                byte[] bytes = Encoding.UTF8.GetBytes(protocolJson);
                var segment = new ArraySegment<byte>(bytes);

                await _ws.SendAsync(segment, WebSocketMessageType.Text, true, _cts.Token);
            }
            catch (Exception)
            {
                HandleDisconnect(true, "WebSocket send failed");
            }
        }

        // ── Receive Loop ────────────────────────────────────────────────

        private async Task ReceiveLoop(ClientWebSocket socket, CancellationToken token)
        {
            byte[] buffer = new byte[8192];
            StringBuilder messageBuilder = new();

            try
            {
                while (!token.IsCancellationRequested && socket.State == WebSocketState.Open)
                {
                    var segment = new ArraySegment<byte>(buffer);
                    WebSocketReceiveResult result = await socket.ReceiveAsync(segment, token);

                    if (result.MessageType == WebSocketMessageType.Close)
                    {
                        bool policyViolation = result.CloseStatus == WebSocketCloseStatus.PolicyViolation;
                        HandleDisconnect(!policyViolation, policyViolation
                            ? "WebSocket authentication or policy rejected"
                            : "WebSocket server requested close");
                        break;
                    }

                    string chunk = Encoding.UTF8.GetString(buffer, 0, result.Count);
                    messageBuilder.Append(chunk);

                    if (result.EndOfMessage)
                    {
                        string fullMessage = messageBuilder.ToString().Trim();
                        messageBuilder.Clear();

                        if (!string.IsNullOrEmpty(fullMessage))
                        {
                            _incomingQueue.Enqueue(fullMessage);
                        }
                    }
                }
            }
            catch (OperationCanceledException)
            {
                // Expected on shutdown
            }
            catch (Exception)
            {
                if (!token.IsCancellationRequested)
                {
                    HandleDisconnect(true, "WebSocket receive failed");
                }
            }
            finally
            {
                if (!token.IsCancellationRequested)
                {
                    HandleDisconnect(true, "WebSocket closed");
                }
            }
        }

        // ── Helpers ─────────────────────────────────────────────────────

        private async Task SendHeartbeatAsync()
        {
            if (!IsConnected || _ws == null)
            {
                return;
            }

            SessionHeartbeatPayload payload = new SessionHeartbeatPayload
            {
                timestamp_epoch_ms = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds(),
                sequence_number = Mathf.Max(0, _reconnectAttempt)
            };
            NexusMessage<SessionHeartbeatPayload> message = NexusMessageParser.CreateMessage(
                NexusProtocol.TypeSessionHeartbeat,
                NexusProtocol.TopicSession,
                payload,
                sessionId: null);
            try
            {
                byte[] bytes = Encoding.UTF8.GetBytes(message.ToJson());
                await _ws.SendAsync(new ArraySegment<byte>(bytes), WebSocketMessageType.Text, true, _cts.Token);
            }
            catch (Exception)
            {
                HandleDisconnect(true, "Heartbeat send failed");
            }
        }

        private void HandleConnectFailure(bool permanent, string reason)
        {
            if (permanent || !autoConnect || _shutdownRequested)
            {
                SetState(ConnectionState.AuthenticationFailed);
                NotifyEstablished(false);
                return;
            }

            _reconnectAttempt++;
            if (maxReconnectAttempts > 0 && _reconnectAttempt > maxReconnectAttempts)
            {
                SetState(ConnectionState.AuthenticationFailed);
                NotifyEstablished(false);
                return;
            }
            _reconnectTimer = 0f;
            SetState(ConnectionState.Reconnecting);
            NotifyEstablished(false);
            Debug.LogWarning($"[NEXUS Bridge] {reason}; retry scheduled");
        }

        private void HandleDisconnect(bool shouldReconnect, string reason)
        {
            bool wasConnected = IsConnected;
            _connectionEpoch++;
            _snapshotCts?.Cancel();
            _snapshotCts = null;
            _snapshotInFlight = false;
            _ws = null;
            if (wasConnected)
            {
                SetState(shouldReconnect && autoConnect
                    ? ConnectionState.Reconnecting
                    : ConnectionState.Disconnected);
                NotifyEstablished(false);
            }
            if (shouldReconnect && autoConnect && !_shutdownRequested && HasSessionToken)
            {
                _reconnectAttempt = Mathf.Max(1, _reconnectAttempt + 1);
                _reconnectTimer = 0f;
                if (maxReconnectAttempts > 0 && _reconnectAttempt > maxReconnectAttempts)
                {
                    SetState(ConnectionState.AuthenticationFailed);
                    NotifyEstablished(false);
                }
            }
            if (wasConnected)
            {
                Debug.LogWarning($"[NEXUS Bridge] {reason}");
            }
        }

        private float NextReconnectDelay()
        {
            float exponential = reconnectInitialDelaySeconds * Mathf.Pow(2f, Mathf.Min(_reconnectAttempt - 1, 10));
            float bounded = Mathf.Min(Mathf.Max(reconnectInitialDelaySeconds, exponential), reconnectMaxDelaySeconds);
            return bounded + UnityEngine.Random.Range(0f, Mathf.Max(0f, reconnectJitterSeconds));
        }

        private void SetState(ConnectionState next)
        {
            lock (_stateLock)
            {
                if (_state == next)
                {
                    return;
                }
                _state = next;
            }
            _stateEvents.Enqueue(next);
        }

        private void NotifyEstablished(bool established)
        {
            _establishedEvents.Enqueue(established);
        }

        private void HandleIncomingMessage(string message)
        {
            NexusEnvelope envelope = NexusMessageParser.ParseEnvelope(message);
            if (envelope == null || envelope.protocol_version != NexusProtocol.Version)
            {
                Debug.LogWarning("[NEXUS Bridge] Ignored malformed or unsupported protocol message");
                return;
            }

            if (envelope.message_type == NexusProtocol.TypeSessionHeartbeat)
            {
                _lastHeartbeatActivityUtc = DateTime.UtcNow;
            }
            OnProtocolMessage?.Invoke(message);
            if (envelope.message_type.StartsWith("window.", StringComparison.Ordinal))
            {
                if (NexusMessageParser.TryConvertWindowCommand(message, out string legacyJson)
                    && windowManager != null)
                {
                    windowManager.HandleCommand(legacyJson);
                }
            }
        }

        private void RequestStateResynchronization()
        {
            if (_shutdownRequested || !IsConnected || !HasSessionToken || _snapshotInFlight)
            {
                return;
            }

            _snapshotInFlight = true;
            _snapshotCts?.Cancel();
            _snapshotCts?.Dispose();
            _snapshotCts = new CancellationTokenSource(TimeSpan.FromSeconds(10));
            long epoch = _connectionEpoch;
            _snapshotTask = FetchSnapshotsAsync(epoch, _snapshotCts.Token);
        }

        private async Task FetchSnapshotsAsync(long epoch, CancellationToken token)
        {
            try
            {
                if (_httpClient == null)
                {
                    _httpClient = new HttpClient { Timeout = TimeSpan.FromSeconds(10) };
                }

                string stateUri = string.IsNullOrEmpty(stateEndpointUri)
                    ? BuildHttpEndpoint("/api/v1/vr/state")
                    : stateEndpointUri;
                string workspaceUri = string.IsNullOrEmpty(workspaceEndpointUri)
                    ? BuildHttpEndpoint("/api/v1/vr/workspace")
                    : workspaceEndpointUri;

                using (var stateRequest = CreateSnapshotRequest(stateUri))
                using (HttpResponseMessage stateResponse = await _httpClient.SendAsync(stateRequest, token))
                {
                    if (!stateResponse.IsSuccessStatusCode)
                    {
                        _snapshotResults.Enqueue(new SnapshotResult { epoch = epoch, error = "state request failed" });
                        return;
                    }
                    string stateJson = await stateResponse.Content.ReadAsStringAsync();
                    VRStateSnapshot state = JsonUtility.FromJson<VRStateSnapshot>(stateJson);
                    if (state == null || state.protocol_version != NexusProtocol.Version || state.windows == null)
                    {
                        _snapshotResults.Enqueue(new SnapshotResult { epoch = epoch, error = "invalid state response" });
                        return;
                    }

                    using (var workspaceRequest = CreateSnapshotRequest(workspaceUri))
                    using (HttpResponseMessage workspaceResponse = await _httpClient.SendAsync(workspaceRequest, token))
                    {
                        if (!workspaceResponse.IsSuccessStatusCode)
                        {
                            _snapshotResults.Enqueue(new SnapshotResult { epoch = epoch, error = "workspace request failed" });
                            return;
                        }
                        string workspaceJson = await workspaceResponse.Content.ReadAsStringAsync();
                        VRWorkspaceSnapshot workspace = JsonUtility.FromJson<VRWorkspaceSnapshot>(workspaceJson);
                        if (workspace == null
                            || workspace.protocol_version != NexusProtocol.Version
                            || workspace.workspaces == null)
                        {
                            _snapshotResults.Enqueue(new SnapshotResult { epoch = epoch, error = "invalid workspace response" });
                            return;
                        }
                        _snapshotResults.Enqueue(new SnapshotResult
                        {
                            epoch = epoch,
                            state = state,
                            workspace = workspace
                        });
                    }
                }
            }
            catch (OperationCanceledException)
            {
                _snapshotResults.Enqueue(new SnapshotResult { epoch = epoch, error = "snapshot cancelled" });
            }
            catch (Exception)
            {
                _snapshotResults.Enqueue(new SnapshotResult { epoch = epoch, error = "snapshot request failed" });
            }
        }

        private HttpRequestMessage CreateSnapshotRequest(string uri)
        {
            var request = new HttpRequestMessage(HttpMethod.Get, uri);
            request.Headers.Authorization = new AuthenticationHeaderValue("Bearer", _sessionToken);
            return request;
        }

        private string BuildHttpEndpoint(string path)
        {
            Uri websocket = new Uri(serverUri);
            string scheme = websocket.Scheme == "wss" ? "https" : "http";
            return new UriBuilder(scheme, websocket.Host, websocket.Port, path).Uri.ToString();
        }
    }
}
