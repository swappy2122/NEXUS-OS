using System;
using UnityEngine;

namespace Nexus.VR.Window
{
    // ── Protocol Constants ───────────────────────────────────────────────

    /// <summary>
    /// Constants and standard topics/types for the NEXUS OS IPC wire protocol.
    /// </summary>
    public static class NexusProtocol
    {
        public const string Version = "1.0";

        // Topics
        public const string TopicWindow = "window";
        public const string TopicAI = "ai";
        public const string TopicSecurity = "security";
        public const string TopicSession = "session";
        public const string TopicSystem = "system";

        // Message Types: Window
        public const string TypeWindowCreate = "window.create";
        public const string TypeWindowClose = "window.close";
        public const string TypeWindowMove = "window.move";
        public const string TypeWindowResize = "window.resize";
        public const string TypeWindowRotate = "window.rotate";
        public const string TypeWindowFocus = "window.focus";
        public const string TypeWindowSetState = "window.set_state";
        public const string TypeWindowSetAnchor = "window.set_anchor";
        public const string TypeWindowSetTitle = "window.set_title";
        public const string TypeWindowBatch = "window.batch";

        public const string TypeWindowCreated = "window.created";
        public const string TypeWindowClosed = "window.closed";
        public const string TypeWindowMoved = "window.moved";
        public const string TypeWindowResized = "window.resized";
        public const string TypeWindowRotated = "window.rotated";
        public const string TypeWindowFocused = "window.focused";
        public const string TypeWindowStateChanged = "window.state_changed";
        public const string TypeWindowGrabStarted = "window.grab_started";
        public const string TypeWindowGrabEnded = "window.grab_ended";
        public const string TypeWindowError = "window.error";

        // Message Types: AI
        public const string TypeAIRequest = "ai.request";
        public const string TypeAIToken = "ai.token";
        public const string TypeAIState = "ai.state";
        public const string TypeAIError = "ai.error";

        // Message Types: Security
        public const string TypeSecurityConfirmRequest = "security.confirm_request";
        public const string TypeSecurityConfirmResponse = "security.confirm_response";

        // Message Types: Session
        public const string TypeSessionStarted = "session.started";
        public const string TypeSessionEnded = "session.ended";
        public const string TypeSessionHeartbeat = "session.heartbeat";
    }

    // ── Enums ───────────────────────────────────────────────────────────

    /// <summary>
    /// Lifecycle state of a VR window.
    /// Mirrors Python's <c>WindowState</c> enum for consistent serialization.
    /// </summary>
    public enum VRWindowState
    {
        Creating,
        Open,
        Minimized,
        Maximized,
        Closing,
        Closed
    }

    /// <summary>
    /// Spatial anchor mode for window positioning.
    /// Mirrors Python's <c>WindowAnchor</c> enum.
    /// </summary>
    public enum VRWindowAnchor
    {
        WorldFixed,
        HeadRelative,
        HandAttached,
        WorkspaceSlot
    }

    // ── Serializable Wire Primitives ────────────────────────────────────

    /// <summary>
    /// JSON-serializable 3D vector matching Python's Vec3.
    /// </summary>
    [Serializable]
    public struct SerializableVec3
    {
        public float x;
        public float y;
        public float z;

        public SerializableVec3(float x, float y, float z)
        {
            this.x = x;
            this.y = y;
            this.z = z;
        }

        public Vector3 ToVector3() => new(x, y, z);

        public static SerializableVec3 FromVector3(Vector3 v)
            => new(v.x, v.y, v.z);
    }

    /// <summary>
    /// JSON-serializable quaternion matching Python's Quat.
    /// </summary>
    [Serializable]
    public struct SerializableQuat
    {
        public float x;
        public float y;
        public float z;
        public float w;

        public SerializableQuat(float x, float y, float z, float w)
        {
            this.x = x;
            this.y = y;
            this.z = z;
            this.w = w;
        }

        public Quaternion ToQuaternion() => new(x, y, z, w);

        public static SerializableQuat FromQuaternion(Quaternion q)
            => new(q.x, q.y, q.z, q.w);
    }

    /// <summary>
    /// JSON-serializable window size in meters.
    /// </summary>
    [Serializable]
    public struct SerializableSize
    {
        public float width;
        public float height;

        public SerializableSize(float width, float height)
        {
            this.width = width;
            this.height = height;
        }
    }

    /// <summary>
    /// JSON-serializable spatial transform (position + rotation + scale).
    /// </summary>
    [Serializable]
    public struct SerializableTransform
    {
        public SerializableVec3 position;
        public SerializableQuat rotation;
        public SerializableVec3 scale;

        public Vector3 ToPosition() => position.ToVector3();
        public Quaternion ToRotation() => rotation.ToQuaternion();
        public Vector3 ToScale() => scale.ToVector3();

        public static SerializableTransform FromUnity(Transform t)
        {
            return new SerializableTransform
            {
                position = SerializableVec3.FromVector3(t.position),
                rotation = SerializableQuat.FromQuaternion(t.rotation),
                scale = SerializableVec3.FromVector3(t.localScale)
            };
        }
    }

    // ── Unified Wire Protocol Envelopes ─────────────────────────────────

    /// <summary>
    /// Inspection envelope for first-pass deserialization.
    /// Used to inspect message_type and topic before selecting the concrete payload type.
    /// </summary>
    [Serializable]
    public class NexusEnvelope
    {
        public string protocol_version = NexusProtocol.Version;
        public string message_id;
        public string message_type;
        public string topic;
        public string timestamp;
        public string session_id;
        public string correlation_id;
    }

    /// <summary>
    /// Generic unified message envelope matching Python's NexusMessage[T].
    /// </summary>
    [Serializable]
    public class NexusMessage<T>
    {
        public string protocol_version = NexusProtocol.Version;
        public string message_id;
        public string message_type;
        public string topic;
        public string timestamp;
        public string session_id;
        public string correlation_id;
        public T payload;

        public string ToJson() => JsonUtility.ToJson(this);
    }

    // ── Concrete Envelope Wrappers for Unity JsonUtility ────────────────
    // Unity's JsonUtility works most reliably with non-generic concrete types.

    [Serializable] public class NexusWindowCreateMessage : NexusMessage<CreateCommandPayload> { }
    [Serializable] public class NexusWindowCloseMessage : NexusMessage<WindowClosePayload> { }
    [Serializable] public class NexusWindowMoveMessage : NexusMessage<MoveCommandPayload> { }
    [Serializable] public class NexusWindowResizeMessage : NexusMessage<ResizeCommandPayload> { }
    [Serializable] public class NexusWindowRotateMessage : NexusMessage<RotateCommandPayload> { }
    [Serializable] public class NexusWindowFocusMessage : NexusMessage<FocusCommandPayload> { }
    [Serializable] public class NexusWindowSetStateMessage : NexusMessage<SetStateCommandPayload> { }
    [Serializable] public class NexusWindowSetAnchorMessage : NexusMessage<SetAnchorCommandPayload> { }
    [Serializable] public class NexusWindowSetTitleMessage : NexusMessage<SetTitleCommandPayload> { }

    [Serializable] public class NexusAITokenMessage : NexusMessage<AITokenPayload> { }
    [Serializable] public class NexusAIStateMessage : NexusMessage<AIStatePayload> { }
    [Serializable] public class NexusAIRequestMessage : NexusMessage<AIRequestPayload> { }
    [Serializable] public class NexusAIErrorMessage : NexusMessage<AIErrorPayload> { }

    [Serializable] public class NexusSecurityConfirmRequestMessage : NexusMessage<SecurityConfirmRequestPayload> { }
    [Serializable] public class NexusSecurityConfirmResponseMessage : NexusMessage<SecurityConfirmResponsePayload> { }

    [Serializable] public class NexusSessionStartedMessage : NexusMessage<SessionStartedPayload> { }
    [Serializable] public class NexusSessionEndedMessage : NexusMessage<SessionEndedPayload> { }
    [Serializable] public class NexusSessionHeartbeatMessage : NexusMessage<SessionHeartbeatPayload> { }

    [Serializable] public class NexusWindowCreatedEventMessage : NexusMessage<WindowCreatedPayload> { }
    [Serializable] public class NexusWindowMovedEventMessage : NexusMessage<WindowMovedPayload> { }
    [Serializable] public class NexusWindowClosedEventMessage : NexusMessage<WindowClosedPayload> { }
    [Serializable] public class NexusWindowResizedEventMessage : NexusMessage<WindowResizedPayload> { }
    [Serializable] public class NexusWindowRotatedEventMessage : NexusMessage<WindowRotatedPayload> { }
    [Serializable] public class NexusWindowFocusedEventMessage : NexusMessage<WindowFocusedPayload> { }
    [Serializable] public class NexusWindowStateChangedEventMessage : NexusMessage<WindowStateChangedPayload> { }
    [Serializable] public class NexusWindowGrabStartedEventMessage : NexusMessage<WindowGrabPayload> { }
    [Serializable] public class NexusWindowGrabEndedEventMessage : NexusMessage<WindowGrabPayload> { }
    [Serializable] public class NexusWindowErrorEventMessage : NexusMessage<WindowErrorPayload> { }

    // ── Legacy Command / Event Wire Types ───────────────────────────────
    // Kept intact for backwards compatibility with existing VRWindowManager implementations.

    /// <summary>
    /// Top-level command envelope received from the Python VRBridge (legacy).
    /// </summary>
    [Serializable]
    public struct WindowCommandEnvelope
    {
        public string type;
        public string window_id;
        public string request_id;
    }

    /// <summary>
    /// Top-level event envelope sent back to the Python VRBridge (legacy).
    /// </summary>
    [Serializable]
    public struct WindowEventEnvelope
    {
        public string type;
        public string window_id;
        public string request_id;
        public double timestamp;

        public string ToJson()
        {
            timestamp = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds() / 1000.0;
            return JsonUtility.ToJson(this);
        }
    }

    // ── Typed Payload Models: Window Namespace ──────────────────────────

    /// <summary>
    /// Data carried by a <c>window.create</c> command.
    /// </summary>
    [Serializable]
    public struct CreateCommandPayload
    {
        public string window_id;
        public string title;
        public string app_id;
        public int workspace_index;
        public SerializableTransform transform;
        public SerializableSize size;
        public string anchor;
    }

    /// <summary>
    /// Data carried by a typed <c>window.close</c> command.
    /// </summary>
    [Serializable]
    public struct WindowClosePayload
    {
        public string window_id;
    }

    /// <summary>
    /// Data carried by a <c>window.move</c> command.
    /// </summary>
    [Serializable]
    public struct MoveCommandPayload
    {
        public string window_id;
        public SerializableVec3 target_position;
        public bool animate;
        public float duration_seconds;
    }

    /// <summary>
    /// Data carried by a <c>window.resize</c> command.
    /// </summary>
    [Serializable]
    public struct ResizeCommandPayload
    {
        public string window_id;
        public SerializableSize target_size;
        public bool animate;
        public float duration_seconds;
    }

    /// <summary>
    /// Data carried by a <c>window.rotate</c> command.
    /// </summary>
    [Serializable]
    public struct RotateCommandPayload
    {
        public string window_id;
        public SerializableQuat target_rotation;
        public bool animate;
        public float duration_seconds;
    }

    /// <summary>
    /// Data carried by a <c>window.focus</c> command.
    /// </summary>
    [Serializable]
    public struct FocusCommandPayload
    {
        public string window_id;
        public bool focused;
    }

    /// <summary>
    /// Data carried by a <c>window.set_state</c> command.
    /// </summary>
    [Serializable]
    public struct SetStateCommandPayload
    {
        public string window_id;
        public string target_state;
    }

    /// <summary>
    /// Data carried by a <c>window.set_anchor</c> command.
    /// </summary>
    [Serializable]
    public struct SetAnchorCommandPayload
    {
        public string anchor;
    }

    /// <summary>
    /// Data carried by a <c>window.set_title</c> command.
    /// </summary>
    [Serializable]
    public struct SetTitleCommandPayload
    {
        public string title;
    }

    // Window Events (Unity → Python)

    [Serializable]
    public struct WindowCreatedPayload
    {
        public string window_id;
        public string title;
        public int workspace_index;
        public string app_id;
    }

    [Serializable]
    public struct WindowClosedPayload
    {
        public string window_id;
    }

    [Serializable]
    public struct WindowMovedPayload
    {
        public string window_id;
        public SerializableVec3 position;
        public string reason;
    }

    [Serializable]
    public struct WindowResizedPayload
    {
        public string window_id;
        public SerializableSize size;
    }

    [Serializable]
    public struct WindowRotatedPayload
    {
        public string window_id;
        public SerializableQuat rotation;
    }

    [Serializable]
    public struct WindowFocusedPayload
    {
        public string window_id;
        public bool focused;
    }

    [Serializable]
    public struct WindowStateChangedPayload
    {
        public string window_id;
        public string state;
    }

    [Serializable]
    public struct WindowGrabPayload
    {
        public string window_id;
        public string hand;
        public bool is_grabbing;
    }

    [Serializable]
    public struct WindowErrorPayload
    {
        public string window_id;
        public string error_message;
        public string request_id;
    }

    // ── Typed Payload Models: AI Namespace ──────────────────────────────

    [Serializable]
    public struct AIRequestPayload
    {
        public string user_message_id;
        public string prompt;
        public string agent_role;
        public string session_id;
    }

    [Serializable]
    public struct AITokenPayload
    {
        public string response_id;
        public string token;
        public bool is_final;
        public string agent_role;
    }

    [Serializable]
    public struct AIStatePayload
    {
        public string agent_role;
        public string state;
        public string active_tool;
        public string user_message_id;
    }

    [Serializable]
    public struct AIErrorPayload
    {
        public string response_id;
        public string error;
        public string agent_role;
    }

    // ── Typed Payload Models: Security Namespace ────────────────────────

    [Serializable]
    public struct SecurityConfirmRequestPayload
    {
        public string confirmation_request_id;
        public string agent_role;
        public string tool_name;
        public string action_category;
        public string risk_level;
        public string description;
        public double expires_at;
    }

    [Serializable]
    public struct SecurityConfirmResponsePayload
    {
        public string confirmation_request_id;
        public string decision;
        public string reason;
        public string user_gesture;
    }

    // ── Typed Payload Models: Session Namespace ─────────────────────────

    [Serializable]
    public struct SessionStartedPayload
    {
        public string session_id;
        public string client_id;
        public string client_version;
        public string hmd_model;
        public string[] capabilities;
    }

    [Serializable]
    public struct SessionEndedPayload
    {
        public string session_id;
        public string reason;
    }

    [Serializable]
    public struct SessionHeartbeatPayload
    {
        public long timestamp_epoch_ms;
        public int sequence_number;
    }

    // ── REST Snapshot Models ────────────────────────────────────────────

    [Serializable]
    public class VRStateSnapshot
    {
        public string protocol_version;
        public VRWindowSnapshot[] windows;
        public string focused_window_id;
        public int window_count;
    }

    [Serializable]
    public class VRWorkspaceSnapshot
    {
        public string protocol_version;
        public int? active_workspace_index;
        public WorkspaceSnapshot[] workspaces;
    }

    [Serializable]
    public class WorkspaceSnapshot
    {
        public int index;
        public string name;
        public bool is_active;
        public VRWindowSnapshot[] windows;
    }

    [Serializable]
    public class VRWindowSnapshot
    {
        public string window_id;
        public string title;
        public string app_id;
        public int workspace_index;
        public string state;
        public string anchor;
        public SerializableTransform transform;
        public SerializableSize size;
        public int z_order;
        public bool is_focused;
    }

    // ── Serialization & Parsing Utilities ───────────────────────────────

    /// <summary>
    /// Helper utilities for creating and parsing unified NexusMessage envelopes.
    /// </summary>
    public static class NexusMessageParser
    {
        /// <summary>
        /// Inspect the message_type and envelope metadata of any raw JSON string.
        /// </summary>
        public static NexusEnvelope ParseEnvelope(string json)
        {
            if (string.IsNullOrEmpty(json)) return null;
            try
            {
                return JsonUtility.FromJson<NexusEnvelope>(json);
            }
            catch (Exception)
            {
                return null;
            }
        }

        /// <summary>
        /// Create a new strongly typed message with auto-generated id, UTC timestamp, and version.
        /// </summary>
        public static NexusMessage<T> CreateMessage<T>(
            string messageType,
            string topic,
            T payload,
            string correlationId = null,
            string sessionId = null)
        {
            return new NexusMessage<T>
            {
                protocol_version = NexusProtocol.Version,
                message_id = "msg_" + Guid.NewGuid().ToString("N").Substring(0, 12),
                message_type = messageType,
                topic = topic,
                timestamp = DateTime.UtcNow.ToString("yyyy-MM-ddTHH:mm:ssZ"),
                session_id = sessionId,
                correlation_id = correlationId,
                payload = payload
            };
        }

        /// <summary>
        /// Convert a typed backend window command to the legacy command shape
        /// consumed by VRWindowManager. This keeps the manager API stable while
        /// the transport uses NexusMessage envelopes.
        /// </summary>
        public static bool TryConvertWindowCommand(string json, out string legacyJson)
        {
            legacyJson = null;
            NexusEnvelope envelope = ParseEnvelope(json);
            if (envelope == null) return false;

            string requestId = envelope.correlation_id ?? "";
            switch (envelope.message_type)
            {
                case NexusProtocol.TypeWindowCreate:
                    var create = JsonUtility.FromJson<NexusWindowCreateMessage>(json);
                    legacyJson = JsonUtility.ToJson(new LegacyCreateCommand
                    {
                        type = envelope.message_type,
                        window_id = create.payload.window_id,
                        request_id = requestId,
                        payload = create.payload
                    });
                    return true;
                case NexusProtocol.TypeWindowClose:
                    var close = JsonUtility.FromJson<NexusWindowCloseMessage>(json);
                    legacyJson = JsonUtility.ToJson(new WindowCommandEnvelope
                    {
                        type = envelope.message_type,
                        window_id = close.payload.window_id,
                        request_id = requestId
                    });
                    return true;
                case NexusProtocol.TypeWindowMove:
                    var move = JsonUtility.FromJson<NexusWindowMoveMessage>(json);
                    legacyJson = JsonUtility.ToJson(new LegacyMoveCommand
                    {
                        type = envelope.message_type,
                        window_id = move.payload.window_id,
                        request_id = requestId,
                        payload = move.payload
                    });
                    return true;
                case NexusProtocol.TypeWindowResize:
                    var resize = JsonUtility.FromJson<NexusWindowResizeMessage>(json);
                    legacyJson = JsonUtility.ToJson(new LegacyResizeCommand
                    {
                        type = envelope.message_type,
                        window_id = resize.payload.window_id,
                        request_id = requestId,
                        payload = resize.payload
                    });
                    return true;
                case NexusProtocol.TypeWindowRotate:
                    var rotate = JsonUtility.FromJson<NexusWindowRotateMessage>(json);
                    legacyJson = JsonUtility.ToJson(new LegacyRotateCommand
                    {
                        type = envelope.message_type,
                        window_id = rotate.payload.window_id,
                        request_id = requestId,
                        payload = rotate.payload
                    });
                    return true;
                case NexusProtocol.TypeWindowFocus:
                    var focus = JsonUtility.FromJson<NexusWindowFocusMessage>(json);
                    legacyJson = JsonUtility.ToJson(new LegacyFocusCommand
                    {
                        type = envelope.message_type,
                        window_id = focus.payload.window_id,
                        request_id = requestId,
                        payload = focus.payload
                    });
                    return true;
                case NexusProtocol.TypeWindowSetState:
                    var state = JsonUtility.FromJson<NexusWindowSetStateMessage>(json);
                    legacyJson = JsonUtility.ToJson(new LegacySetStateCommand
                    {
                        type = envelope.message_type,
                        window_id = state.payload.window_id,
                        request_id = requestId,
                        payload = state.payload
                    });
                    return true;
                default:
                    return false;
            }
        }

        /// <summary>Convert a legacy VRWindowManager event to a typed protocol envelope.</summary>
        public static bool TryConvertWindowEvent(string json, out string protocolJson)
        {
            protocolJson = null;
            LegacyEventEnvelope envelope;
            try
            {
                envelope = JsonUtility.FromJson<LegacyEventEnvelope>(json);
            }
            catch (Exception)
            {
                return false;
            }
            if (envelope == null || string.IsNullOrEmpty(envelope.type)) return false;

            string correlationId = string.IsNullOrEmpty(envelope.request_id) ? null : envelope.request_id;
            switch (envelope.type)
            {
                case NexusProtocol.TypeWindowCreated:
                    protocolJson = CreateMessage(
                        envelope.type, NexusProtocol.TopicWindow,
                        new WindowCreatedPayload { window_id = envelope.window_id },
                        correlationId).ToJson();
                    return true;
                case NexusProtocol.TypeWindowClosed:
                    protocolJson = CreateMessage(
                        envelope.type, NexusProtocol.TopicWindow,
                        new WindowClosedPayload { window_id = envelope.window_id },
                        correlationId).ToJson();
                    return true;
                case NexusProtocol.TypeWindowMoved:
                    var moved = JsonUtility.FromJson<LegacyMovedEvent>(json);
                    protocolJson = CreateMessage(
                        envelope.type, NexusProtocol.TopicWindow,
                        new WindowMovedPayload
                        {
                            window_id = envelope.window_id,
                            position = moved.payload.position
                        }, correlationId).ToJson();
                    return true;
                case NexusProtocol.TypeWindowRotated:
                    var rotated = JsonUtility.FromJson<LegacyRotatedEvent>(json);
                    protocolJson = CreateMessage(
                        envelope.type, NexusProtocol.TopicWindow,
                        new WindowRotatedPayload
                        {
                            window_id = envelope.window_id,
                            rotation = rotated.payload.rotation
                        }, correlationId).ToJson();
                    return true;
                case NexusProtocol.TypeWindowFocused:
                    protocolJson = CreateMessage(
                        envelope.type, NexusProtocol.TopicWindow,
                        new WindowFocusedPayload
                        {
                            window_id = envelope.window_id,
                            focused = true
                        }, correlationId).ToJson();
                    return true;
                case NexusProtocol.TypeWindowStateChanged:
                    var state = JsonUtility.FromJson<LegacyStateChangedEvent>(json);
                    protocolJson = CreateMessage(
                        envelope.type, NexusProtocol.TopicWindow,
                        new WindowStateChangedPayload
                        {
                            window_id = envelope.window_id,
                            state = state.payload.state
                        }, correlationId).ToJson();
                    return true;
                default:
                    return false;
            }
        }

        [Serializable] private class LegacyCreateCommand
        {
            public string type;
            public string window_id;
            public string request_id;
            public CreateCommandPayload payload;
        }
        [Serializable] private class LegacyMoveCommand
        {
            public string type;
            public string window_id;
            public string request_id;
            public MoveCommandPayload payload;
        }
        [Serializable] private class LegacyResizeCommand
        {
            public string type;
            public string window_id;
            public string request_id;
            public ResizeCommandPayload payload;
        }
        [Serializable] private class LegacyRotateCommand
        {
            public string type;
            public string window_id;
            public string request_id;
            public RotateCommandPayload payload;
        }
        [Serializable] private class LegacyFocusCommand
        {
            public string type;
            public string window_id;
            public string request_id;
            public FocusCommandPayload payload;
        }
        [Serializable] private class LegacySetStateCommand
        {
            public string type;
            public string window_id;
            public string request_id;
            public SetStateCommandPayload payload;
        }
        [Serializable] private class LegacyEventEnvelope
        {
            public string type;
            public string window_id;
            public string request_id;
        }
        [Serializable] private class LegacyMovedEvent
        {
            public LegacyEventEnvelope envelope;
            public LegacyPositionPayload payload;
        }
        [Serializable] private class LegacyRotatedEvent
        {
            public LegacyEventEnvelope envelope;
            public LegacyRotationPayload payload;
        }
        [Serializable] private class LegacyStateChangedEvent
        {
            public LegacyEventEnvelope envelope;
            public LegacyStatePayload payload;
        }
        [Serializable] private struct LegacyPositionPayload { public SerializableVec3 position; }
        [Serializable] private struct LegacyRotationPayload { public SerializableQuat rotation; }
        [Serializable] private struct LegacyStatePayload { public string state; }
    }

    // ── Helpers ─────────────────────────────────────────────────────────

    /// <summary>
    /// Conversion utilities between wire enum strings and C# enums.
    /// </summary>
    public static class WindowEnumParser
    {
        public static VRWindowState ParseState(string value)
        {
            return value switch
            {
                "creating" => VRWindowState.Creating,
                "open" => VRWindowState.Open,
                "minimized" => VRWindowState.Minimized,
                "maximized" => VRWindowState.Maximized,
                "closing" => VRWindowState.Closing,
                "closed" => VRWindowState.Closed,
                _ => VRWindowState.Open
            };
        }

        public static string StateToString(VRWindowState state)
        {
            return state switch
            {
                VRWindowState.Creating => "creating",
                VRWindowState.Open => "open",
                VRWindowState.Minimized => "minimized",
                VRWindowState.Maximized => "maximized",
                VRWindowState.Closing => "closing",
                VRWindowState.Closed => "closed",
                _ => "open"
            };
        }

        public static VRWindowAnchor ParseAnchor(string value)
        {
            return value switch
            {
                "world_fixed" => VRWindowAnchor.WorldFixed,
                "head_relative" => VRWindowAnchor.HeadRelative,
                "hand_attached" => VRWindowAnchor.HandAttached,
                "workspace_slot" => VRWindowAnchor.WorkspaceSlot,
                _ => VRWindowAnchor.WorldFixed
            };
        }
    }
}
