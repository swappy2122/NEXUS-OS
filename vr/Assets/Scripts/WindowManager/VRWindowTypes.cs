using System;
using System.Collections.Generic;
using UnityEngine;

namespace Nexus.VR.WindowManager
{
    // ======================================================================
    // Enums
    // ======================================================================

    /// <summary>
    /// What a VR window renders inside its frame.
    /// Must stay in sync with Python <c>core.vr_types.WindowContentType</c>.
    /// </summary>
    public enum WindowContentType
    {
        Terminal,
        WebBrowser,
        FileBrowser,
        TextEditor,
        SystemMonitor,
        MediaPlayer,
        AIChat,
        Custom
    }

    /// <summary>
    /// Operation types received from Python via the bridge.
    /// Must stay in sync with Python <c>core.vr_types.WindowCommandType</c>.
    /// </summary>
    public enum WindowCommandType
    {
        Create,
        Close,
        Move,
        Resize,
        Rotate,
        Focus,
        Unfocus,
        SetVisibility,
        SetTitle,
        SetContent,
        Pin,
        Unpin,
        SnapToLayout,
        Batch
    }

    /// <summary>
    /// Interaction and acknowledgement events sent toward Python.
    /// Must stay in sync with Python <c>core.vr_types.WindowEventType</c>.
    /// </summary>
    public enum WindowEventType
    {
        InteractionGrabStart,
        InteractionGrabEnd,
        InteractionResizeStart,
        InteractionResizeEnd,
        InteractionFocusRequest,
        InteractionCloseRequest,
        PositionChanged,
        RotationChanged,
        SizeChanged,
        WindowCreatedAck,
        WindowClosedAck,
        Error
    }

    /// <summary>
    /// Spatial arrangement algorithm for tiling windows.
    /// </summary>
    public enum WindowLayoutMode
    {
        CurvedArc,
        FlatGrid,
        FreeFloating
    }

    // ======================================================================
    // Data structures  (JSON-serializable, matching Python Pydantic models)
    // ======================================================================

    /// <summary>
    /// Canonical state of a single VR window.
    /// Deserialized from the Python <c>WindowState</c> model.
    /// </summary>
    [Serializable]
    public class WindowStateData
    {
        public string window_id;
        public string app_id;
        public string title;
        public string workspace_id;

        // Spatial transform (raw floats for JSON compat — convert to Unity types via helpers)
        public SerializableVector3 position;
        public SerializableQuaternion rotation;
        public SerializableVector2 size;

        // Display state
        public int z_order;
        public bool is_focused;
        public bool is_visible;
        public bool is_pinned;

        // Content
        public string content_type;
        public Dictionary<string, object> metadata;

        // Timestamps (ISO-8601 strings)
        public string created_at;
        public string updated_at;

        // ── Unity conversions ───────────────────────────────────────────

        public Vector3 Position => position.ToVector3();
        public Quaternion Rotation => rotation.ToQuaternion();
        public Vector2 Size => size.ToVector2();

        public WindowContentType ContentType
        {
            get
            {
                return content_type switch
                {
                    "terminal" => WindowContentType.Terminal,
                    "web_browser" => WindowContentType.WebBrowser,
                    "file_browser" => WindowContentType.FileBrowser,
                    "text_editor" => WindowContentType.TextEditor,
                    "system_monitor" => WindowContentType.SystemMonitor,
                    "media_player" => WindowContentType.MediaPlayer,
                    "ai_chat" => WindowContentType.AIChat,
                    _ => WindowContentType.Custom,
                };
            }
        }
    }

    /// <summary>
    /// Command received from Python to mutate window state in VR.
    /// </summary>
    [Serializable]
    public class WindowCommandData
    {
        public string command_id;
        public string command_type;
        public string window_id;
        public Dictionary<string, object> payload;
        public string timestamp;

        public WindowCommandType CommandType
        {
            get
            {
                return command_type switch
                {
                    "create" => WindowCommandType.Create,
                    "close" => WindowCommandType.Close,
                    "move" => WindowCommandType.Move,
                    "resize" => WindowCommandType.Resize,
                    "rotate" => WindowCommandType.Rotate,
                    "focus" => WindowCommandType.Focus,
                    "unfocus" => WindowCommandType.Unfocus,
                    "set_visibility" => WindowCommandType.SetVisibility,
                    "set_title" => WindowCommandType.SetTitle,
                    "set_content" => WindowCommandType.SetContent,
                    "pin" => WindowCommandType.Pin,
                    "unpin" => WindowCommandType.Unpin,
                    "snap_to_layout" => WindowCommandType.SnapToLayout,
                    "batch" => WindowCommandType.Batch,
                    _ => throw new ArgumentException($"Unknown command type: {command_type}"),
                };
            }
        }
    }

    /// <summary>
    /// Event sent from Unity toward Python to report interaction or state changes.
    /// </summary>
    [Serializable]
    public class WindowEventData
    {
        public string event_id;
        public string event_type;
        public string window_id;
        public Dictionary<string, object> payload;
        public string timestamp;

        /// <summary>
        /// Create a new event data instance ready for serialization.
        /// </summary>
        public static WindowEventData Create(
            WindowEventType type,
            string windowId,
            Dictionary<string, object> payload = null)
        {
            return new WindowEventData
            {
                event_id = Guid.NewGuid().ToString("N").Substring(0, 12),
                event_type = EventTypeToString(type),
                window_id = windowId,
                payload = payload ?? new Dictionary<string, object>(),
                timestamp = DateTime.UtcNow.ToString("o"),
            };
        }

        private static string EventTypeToString(WindowEventType type)
        {
            return type switch
            {
                WindowEventType.InteractionGrabStart => "interaction_grab_start",
                WindowEventType.InteractionGrabEnd => "interaction_grab_end",
                WindowEventType.InteractionResizeStart => "interaction_resize_start",
                WindowEventType.InteractionResizeEnd => "interaction_resize_end",
                WindowEventType.InteractionFocusRequest => "interaction_focus_request",
                WindowEventType.InteractionCloseRequest => "interaction_close_request",
                WindowEventType.PositionChanged => "position_changed",
                WindowEventType.RotationChanged => "rotation_changed",
                WindowEventType.SizeChanged => "size_changed",
                WindowEventType.WindowCreatedAck => "window_created_ack",
                WindowEventType.WindowClosedAck => "window_closed_ack",
                WindowEventType.Error => "error",
                _ => "error",
            };
        }
    }

    // ======================================================================
    // Serializable spatial primitives (JSON-safe wrappers for Unity types)
    // ======================================================================

    /// <summary>
    /// JSON-safe Vector3 matching Python <c>Vector3D</c>.
    /// </summary>
    [Serializable]
    public struct SerializableVector3
    {
        public float x;
        public float y;
        public float z;

        public SerializableVector3(float x, float y, float z)
        {
            this.x = x;
            this.y = y;
            this.z = z;
        }

        public Vector3 ToVector3() => new Vector3(x, y, z);

        public static SerializableVector3 FromVector3(Vector3 v) =>
            new SerializableVector3(v.x, v.y, v.z);

        public override string ToString() => $"({x:F3}, {y:F3}, {z:F3})";
    }

    /// <summary>
    /// JSON-safe Quaternion matching Python <c>Quaternion3D</c>.
    /// </summary>
    [Serializable]
    public struct SerializableQuaternion
    {
        public float x;
        public float y;
        public float z;
        public float w;

        public SerializableQuaternion(float x, float y, float z, float w)
        {
            this.x = x;
            this.y = y;
            this.z = z;
            this.w = w;
        }

        public Quaternion ToQuaternion() => new Quaternion(x, y, z, w);

        public static SerializableQuaternion FromQuaternion(Quaternion q) =>
            new SerializableQuaternion(q.x, q.y, q.z, q.w);

        public static SerializableQuaternion Identity =>
            new SerializableQuaternion(0f, 0f, 0f, 1f);

        public override string ToString() => $"({x:F3}, {y:F3}, {z:F3}, {w:F3})";
    }

    /// <summary>
    /// JSON-safe Vector2 matching Python <c>WindowSize</c>.
    /// </summary>
    [Serializable]
    public struct SerializableVector2
    {
        public float width;
        public float height;

        public SerializableVector2(float width, float height)
        {
            this.width = width;
            this.height = height;
        }

        public Vector2 ToVector2() => new Vector2(width, height);

        public static SerializableVector2 FromVector2(Vector2 v) =>
            new SerializableVector2(v.x, v.y);

        public override string ToString() => $"({width:F2}m × {height:F2}m)";
    }
}
