using System;

namespace Nexus.VR.WindowManager
{
    /// <summary>
    /// Interface for the WebSocket bridge server running inside Unity.
    ///
    /// The bridge server listens for incoming connections from the Python
    /// <c>VRBridgeClient</c> and provides bidirectional communication:
    ///
    /// <list type="bullet">
    ///   <item>
    ///     <term>Inbound</term>
    ///     <description>
    ///       <see cref="WindowCommandData"/> messages from Python,
    ///       dispatched via <see cref="OnCommandReceived"/>.
    ///     </description>
    ///   </item>
    ///   <item>
    ///     <term>Outbound</term>
    ///     <description>
    ///       <see cref="WindowEventData"/> messages toward Python,
    ///       sent via <see cref="SendEvent"/>.
    ///     </description>
    ///   </item>
    /// </list>
    ///
    /// The framing protocol uses 4-byte big-endian length prefix followed
    /// by a UTF-8 JSON body, matching the Python <c>VRBridgeClient</c>.
    /// </summary>
    public interface IBridgeServer
    {
        // ── lifecycle ───────────────────────────────────────────────────

        /// <summary>
        /// Start listening for connections on the specified TCP port.
        /// </summary>
        void StartListening(int port);

        /// <summary>
        /// Stop the server, close all connections, and release resources.
        /// </summary>
        void Stop();

        // ── messaging ───────────────────────────────────────────────────

        /// <summary>
        /// Serialize and send a <see cref="WindowEventData"/> to the connected Python client.
        /// </summary>
        void SendEvent(WindowEventData windowEvent);

        // ── status ──────────────────────────────────────────────────────

        /// <summary>
        /// Whether a Python client is currently connected.
        /// </summary>
        bool IsConnected { get; }

        // ── events ──────────────────────────────────────────────────────

        /// <summary>Fired when a valid <see cref="WindowCommandData"/> is received and deserialized.</summary>
        event Action<WindowCommandData> OnCommandReceived;

        /// <summary>Fired when a Python client establishes a connection.</summary>
        event Action OnClientConnected;

        /// <summary>Fired when the Python client disconnects.</summary>
        event Action OnClientDisconnected;
    }
}
