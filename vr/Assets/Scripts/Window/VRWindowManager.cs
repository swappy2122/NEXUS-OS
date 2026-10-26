using System;
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.UI;

namespace Nexus.VR.Window
{
    /// <summary>
    /// Central coordinator for all VR windows in the Unity scene.
    ///
    /// Responsibilities:
    ///   - Receives WindowCommands from <see cref="VRBridgeClient"/>
    ///   - Instantiates / destroys <see cref="VRWindowHandle"/> GameObjects
    ///   - Dispatches move / resize / rotate / focus to the correct handle
    ///   - Sends acknowledgement WindowEvents back through <see cref="VRBridgeClient"/>
    ///   - Coordinates with WorkspaceArea for layout management
    ///
    /// Does NOT:
    ///   - Decide *when* to create or close windows (Python does that)
    ///   - Know about the agent framework, EventBus, or LLM
    /// </summary>
    public class VRWindowManager : MonoBehaviour
    {
        [Header("Configuration")]
        [SerializeField] private Transform windowContainer;
        [SerializeField] private GameObject windowPrefab;

        // ── State ───────────────────────────────────────────────────────

        private readonly Dictionary<string, VRWindowHandle> _windows = new();
        private string _focusedWindowId = "";

        // ── Events (for VRBridgeClient to subscribe) ────────────────────

        /// <summary>
        /// Raised whenever an event should be sent back to the Python bridge.
        /// Payload is a serialized JSON string.
        /// </summary>
        public event Action<string> OnWindowEventJson;

        /// <summary>
        /// Raised whenever the window count changes (for HUD / WorkspaceArea).
        /// </summary>
        public event Action<int> OnWindowCountChanged;

        // ── Public Queries ──────────────────────────────────────────────

        /// <summary>Total number of tracked windows.</summary>
        public int WindowCount => _windows.Count;

        /// <summary>Get a window handle by its unique ID.</summary>
        public VRWindowHandle GetWindow(string windowId)
        {
            _windows.TryGetValue(windowId, out var handle);
            return handle;
        }

        /// <summary>Get all tracked window handles.</summary>
        public List<VRWindowHandle> GetAllWindows()
        {
            return new List<VRWindowHandle>(_windows.Values);
        }

        /// <summary>Get windows belonging to a specific workspace.</summary>
        public List<VRWindowHandle> GetWindowsByWorkspace(int workspaceIndex)
        {
            var result = new List<VRWindowHandle>();
            foreach (var handle in _windows.Values)
            {
                if (handle.WorkspaceIndex == workspaceIndex)
                {
                    result.Add(handle);
                }
            }
            return result;
        }

        /// <summary>Get the currently focused window, if any.</summary>
        public VRWindowHandle GetFocusedWindow()
        {
            if (!string.IsNullOrEmpty(_focusedWindowId) && _windows.TryGetValue(_focusedWindowId, out var handle))
            {
                return handle;
            }
            return null;
        }

        /// <summary>
        /// Apply an authoritative backend snapshot on Unity's main thread.
        /// Existing IDs are updated, missing IDs are created once, and stale
        /// backend-managed windows are removed without sending user events.
        /// </summary>
        public void ApplyStateSnapshot(VRStateSnapshot snapshot)
        {
            if (snapshot == null || snapshot.windows == null) return;

            var authoritativeIds = new HashSet<string>();
            foreach (VRWindowSnapshot data in snapshot.windows)
            {
                if (data == null || string.IsNullOrEmpty(data.window_id)) continue;
                authoritativeIds.Add(data.window_id);

                if (_windows.TryGetValue(data.window_id, out var existing))
                {
                    existing.ApplySnapshot(data);
                    continue;
                }

                CreateCommandPayload createData = new CreateCommandPayload
                {
                    window_id = data.window_id,
                    title = data.title ?? "Untitled",
                    app_id = data.app_id ?? "",
                    workspace_index = data.workspace_index,
                    anchor = data.anchor ?? "world_fixed",
                    transform = data.transform,
                    size = data.size
                };
                VRWindowHandle handle = CreateWindowObject(createData, data.window_id);
                if (handle == null) continue;
                _windows[data.window_id] = handle;
                WireHandleEvents(handle);
                handle.ApplySnapshot(data);
                OnWindowCountChanged?.Invoke(_windows.Count);
            }

            // The backend currently has no per-session ownership metadata.
            // Do not delete locally tracked windows that are absent from a
            // snapshot: absence cannot safely prove ownership or staleness.

            if (!string.IsNullOrEmpty(snapshot.focused_window_id)
                && _windows.ContainsKey(snapshot.focused_window_id))
            {
                FocusWindow(snapshot.focused_window_id);
            }
        }

        // ── Command Dispatch ────────────────────────────────────────────

        /// <summary>
        /// Parse and dispatch a raw JSON command from the Python bridge.
        /// This is the primary entry point called by <see cref="VRBridgeClient"/>.
        /// </summary>
        public void HandleCommand(string commandJson)
        {
            if (string.IsNullOrEmpty(commandJson))
            {
                Debug.LogWarning("[NEXUS WM] Received empty command");
                return;
            }

            try
            {
                // Parse the envelope to determine command type
                var envelope = JsonUtility.FromJson<WindowCommandEnvelope>(commandJson);

                switch (envelope.type)
                {
                    case "window.create":
                        HandleCreateCommand(commandJson, envelope);
                        break;

                    case "window.close":
                        HandleCloseCommand(envelope);
                        break;

                    case "window.move":
                        HandleMoveCommand(commandJson, envelope);
                        break;

                    case "window.resize":
                        HandleResizeCommand(commandJson, envelope);
                        break;

                    case "window.rotate":
                        HandleRotateCommand(commandJson, envelope);
                        break;

                    case "window.focus":
                        HandleFocusCommand(commandJson, envelope);
                        break;

                    case "window.set_state":
                        HandleSetStateCommand(commandJson, envelope);
                        break;

                    default:
                        Debug.LogWarning($"[NEXUS WM] Unknown command type: {envelope.type}");
                        SendErrorEvent(envelope.window_id, envelope.request_id,
                            $"Unknown command type: {envelope.type}");
                        break;
                }
            }
            catch (Exception ex)
            {
                Debug.LogError($"[NEXUS WM] Failed to parse command: {ex.Message}\nJSON: {commandJson}");
            }
        }

        // ── Individual Command Handlers ─────────────────────────────────

        private void HandleCreateCommand(string json, WindowCommandEnvelope envelope)
        {
            if (_windows.ContainsKey(envelope.window_id))
            {
                Debug.LogWarning($"[NEXUS WM] Window already exists: {envelope.window_id}");
                SendErrorEvent(envelope.window_id, envelope.request_id, "Window already exists");
                return;
            }

            // Parse full payload
            var wrapper = JsonUtility.FromJson<CreateCommandWrapper>(json);

            // Instantiate
            VRWindowHandle handle = CreateWindowObject(wrapper.payload, envelope.window_id);

            if (handle != null)
            {
                _windows[envelope.window_id] = handle;

                // Wire events from handle back to manager
                WireHandleEvents(handle);

                // Auto-focus new window
                FocusWindow(envelope.window_id);

                OnWindowCountChanged?.Invoke(_windows.Count);

                // Send ack
                SendEvent("window.created", envelope.window_id, envelope.request_id);

                Debug.Log($"[NEXUS WM] Created window: {envelope.window_id} ({wrapper.payload.title})");
            }
            else
            {
                SendErrorEvent(envelope.window_id, envelope.request_id, "Failed to instantiate window");
            }
        }

        private void HandleCloseCommand(WindowCommandEnvelope envelope)
        {
            if (!_windows.TryGetValue(envelope.window_id, out var handle))
            {
                SendErrorEvent(envelope.window_id, envelope.request_id, "Window not found");
                return;
            }

            // Unwire events before destruction
            _windows.Remove(envelope.window_id);

            if (_focusedWindowId == envelope.window_id)
            {
                _focusedWindowId = "";
            }

            handle.DestroyWindow();
            OnWindowCountChanged?.Invoke(_windows.Count);

            SendEvent("window.closed", envelope.window_id, envelope.request_id);
            Debug.Log($"[NEXUS WM] Closed window: {envelope.window_id}");
        }

        private void HandleMoveCommand(string json, WindowCommandEnvelope envelope)
        {
            if (!_windows.TryGetValue(envelope.window_id, out var handle))
            {
                SendErrorEvent(envelope.window_id, envelope.request_id, "Window not found");
                return;
            }

            var wrapper = JsonUtility.FromJson<MoveCommandWrapper>(json);
            handle.MoveTo(
                wrapper.payload.target_position.ToVector3(),
                wrapper.payload.animate,
                wrapper.payload.duration_seconds
            );

            SendEvent("window.moved", envelope.window_id, envelope.request_id);
        }

        private void HandleResizeCommand(string json, WindowCommandEnvelope envelope)
        {
            if (!_windows.TryGetValue(envelope.window_id, out var handle))
            {
                SendErrorEvent(envelope.window_id, envelope.request_id, "Window not found");
                return;
            }

            var wrapper = JsonUtility.FromJson<ResizeCommandWrapper>(json);
            handle.ResizeTo(
                wrapper.payload.target_size.width,
                wrapper.payload.target_size.height,
                wrapper.payload.animate,
                wrapper.payload.duration_seconds
            );

            SendEvent("window.resized", envelope.window_id, envelope.request_id);
        }

        private void HandleRotateCommand(string json, WindowCommandEnvelope envelope)
        {
            if (!_windows.TryGetValue(envelope.window_id, out var handle))
            {
                SendErrorEvent(envelope.window_id, envelope.request_id, "Window not found");
                return;
            }

            var wrapper = JsonUtility.FromJson<RotateCommandWrapper>(json);
            handle.RotateTo(
                wrapper.payload.target_rotation.ToQuaternion(),
                wrapper.payload.animate,
                wrapper.payload.duration_seconds
            );

            SendEvent("window.rotated", envelope.window_id, envelope.request_id);
        }

        private void HandleFocusCommand(string json, WindowCommandEnvelope envelope)
        {
            var wrapper = JsonUtility.FromJson<FocusCommandWrapper>(json);

            if (wrapper.payload.focused)
            {
                FocusWindow(envelope.window_id);
            }
            else
            {
                UnfocusWindow(envelope.window_id);
            }

            SendEvent("window.focused", envelope.window_id, envelope.request_id);
        }

        private void HandleSetStateCommand(string json, WindowCommandEnvelope envelope)
        {
            if (!_windows.TryGetValue(envelope.window_id, out var handle))
            {
                SendErrorEvent(envelope.window_id, envelope.request_id, "Window not found");
                return;
            }

            var wrapper = JsonUtility.FromJson<SetStateCommandWrapper>(json);
            var newState = WindowEnumParser.ParseState(wrapper.payload.target_state);
            handle.SetState(newState);

            // If closing, remove from tracking
            if (newState == VRWindowState.Closing || newState == VRWindowState.Closed)
            {
                _windows.Remove(envelope.window_id);
                if (_focusedWindowId == envelope.window_id)
                {
                    _focusedWindowId = "";
                }
                OnWindowCountChanged?.Invoke(_windows.Count);
            }

            SendEvent("window.state_changed", envelope.window_id, envelope.request_id);
        }

        // ── Focus Management ────────────────────────────────────────────

        /// <summary>Focus a window by ID, unfocusing the current one.</summary>
        public void FocusWindow(string windowId)
        {
            // Unfocus current
            if (!string.IsNullOrEmpty(_focusedWindowId) && _windows.TryGetValue(_focusedWindowId, out var current))
            {
                current.SetFocused(false);
            }

            // Focus new
            if (_windows.TryGetValue(windowId, out var target))
            {
                target.SetFocused(true);
                _focusedWindowId = windowId;
            }
        }

        private void UnfocusWindow(string windowId)
        {
            if (_windows.TryGetValue(windowId, out var handle))
            {
                handle.SetFocused(false);
                if (_focusedWindowId == windowId)
                {
                    _focusedWindowId = "";
                }
            }
        }

        // ── Window Instantiation ────────────────────────────────────────

        private VRWindowHandle CreateWindowObject(CreateCommandPayload data, string windowId)
        {
            Transform parent = windowContainer != null ? windowContainer : transform;

            GameObject windowGO;
            if (windowPrefab != null)
            {
                windowGO = Instantiate(windowPrefab, parent);
            }
            else
            {
                // Programmatic fallback: build a minimal window
                windowGO = BuildDefaultWindow(parent);
            }

            windowGO.name = $"Window_{windowId}";

            VRWindowHandle handle = windowGO.GetComponent<VRWindowHandle>();
            if (handle == null)
            {
                handle = windowGO.AddComponent<VRWindowHandle>();
            }

            handle.Initialize(data, windowId);
            return handle;
        }

        /// <summary>
        /// Build a minimal window GameObject when no prefab is assigned.
        /// Creates a world-space Canvas with a background panel and title text.
        /// </summary>
        private GameObject BuildDefaultWindow(Transform parent)
        {
            GameObject windowGO = new GameObject("VRWindow");
            windowGO.transform.SetParent(parent, false);

            // Canvas (world-space)
            Canvas canvas = windowGO.AddComponent<Canvas>();
            canvas.renderMode = RenderMode.WorldSpace;

            CanvasScaler scaler = windowGO.AddComponent<CanvasScaler>();
            scaler.dynamicPixelsPerUnit = 100f;

            windowGO.AddComponent<GraphicRaycaster>();
            windowGO.AddComponent<CanvasGroup>();

            // RectTransform sizing
            RectTransform rt = windowGO.GetComponent<RectTransform>();
            rt.sizeDelta = new Vector2(800f, 500f);
            rt.localScale = Vector3.one * 0.001f;  // 1000 pixels/meter

            // Background panel
            GameObject bgGO = new GameObject("Background");
            bgGO.transform.SetParent(windowGO.transform, false);
            Image bg = bgGO.AddComponent<Image>();
            bg.color = new Color(0.04f, 0.05f, 0.07f, 0.92f);  // NEXUS dark slate
            RectTransform bgRT = bgGO.GetComponent<RectTransform>();
            bgRT.anchorMin = Vector2.zero;
            bgRT.anchorMax = Vector2.one;
            bgRT.offsetMin = Vector2.zero;
            bgRT.offsetMax = Vector2.zero;

            // Title bar
            GameObject titleGO = new GameObject("Title");
            titleGO.transform.SetParent(windowGO.transform, false);
            Text titleText = titleGO.AddComponent<Text>();
            titleText.font = Resources.GetBuiltinResource<Font>("LegacyRuntime.ttf");
            titleText.fontSize = 24;
            titleText.color = new Color(0f, 0.69f, 0.85f, 1f);  // NEXUS cyan
            titleText.alignment = TextAnchor.UpperLeft;
            RectTransform titleRT = titleGO.GetComponent<RectTransform>();
            titleRT.anchorMin = new Vector2(0f, 1f);
            titleRT.anchorMax = new Vector2(1f, 1f);
            titleRT.pivot = new Vector2(0.5f, 1f);
            titleRT.sizeDelta = new Vector2(0f, 40f);
            titleRT.offsetMin = new Vector2(12f, titleRT.offsetMin.y);
            titleRT.offsetMax = new Vector2(-12f, titleRT.offsetMax.y);

            // Focus highlight border
            GameObject highlightGO = new GameObject("FocusHighlight");
            highlightGO.transform.SetParent(windowGO.transform, false);
            Image highlight = highlightGO.AddComponent<Image>();
            highlight.color = new Color(0f, 0f, 0f, 0f);  // invisible by default
            RectTransform hlRT = highlightGO.GetComponent<RectTransform>();
            hlRT.anchorMin = Vector2.zero;
            hlRT.anchorMax = Vector2.one;
            hlRT.offsetMin = new Vector2(-2f, -2f);
            hlRT.offsetMax = new Vector2(2f, 2f);

            return windowGO;
        }

        // ── Handle Event Wiring ─────────────────────────────────────────

        private void WireHandleEvents(VRWindowHandle handle)
        {
            // When user closes via window chrome button
            handle.OnWindowClosed += OnHandleClose;

            // When user grabs and moves a window
            handle.OnWindowUserMoved += OnHandleUserMoved;

            // When user grabs and rotates a window
            handle.OnWindowUserRotated += OnHandleUserRotated;

            // When focus changes via direct interaction
            handle.OnWindowFocusChanged += OnHandleFocusChanged;
        }

        private void OnHandleClose(VRWindowHandle handle)
        {
            // User requested close via window chrome — notify bridge
            SendEvent("window.closed", handle.WindowId, "");
            _windows.Remove(handle.WindowId);
            if (_focusedWindowId == handle.WindowId)
            {
                _focusedWindowId = "";
            }
            OnWindowCountChanged?.Invoke(_windows.Count);
        }

        private void OnHandleUserMoved(VRWindowHandle handle, Vector3 position)
        {
            var pos = SerializableVec3.FromVector3(position);
            string payload = JsonUtility.ToJson(pos);
            // Build a manual JSON event with position payload
            string eventJson = $"{{\"type\":\"window.moved\",\"window_id\":\"{handle.WindowId}\","
                + $"\"payload\":{{\"position\":{payload}}},"
                + $"\"request_id\":\"\","
                + $"\"timestamp\":{DateTimeOffset.UtcNow.ToUnixTimeMilliseconds() / 1000.0}}}";
            OnWindowEventJson?.Invoke(eventJson);
        }

        private void OnHandleUserRotated(VRWindowHandle handle, Quaternion rotation)
        {
            var rot = SerializableQuat.FromQuaternion(rotation);
            string payload = JsonUtility.ToJson(rot);
            string eventJson = $"{{\"type\":\"window.rotated\",\"window_id\":\"{handle.WindowId}\","
                + $"\"payload\":{{\"rotation\":{payload}}},"
                + $"\"request_id\":\"\","
                + $"\"timestamp\":{DateTimeOffset.UtcNow.ToUnixTimeMilliseconds() / 1000.0}}}";
            OnWindowEventJson?.Invoke(eventJson);
        }

        private void OnHandleFocusChanged(VRWindowHandle handle, bool focused)
        {
            if (focused)
            {
                FocusWindow(handle.WindowId);
                SendEvent("window.focused", handle.WindowId, "");
            }
        }

        // ── Event Helpers ──────────────────────────────────────────────

        private void SendEvent(string type, string windowId, string requestId)
        {
            var evt = new WindowEventEnvelope
            {
                type = type,
                window_id = windowId,
                request_id = requestId
            };
            OnWindowEventJson?.Invoke(evt.ToJson());
        }

        private void SendErrorEvent(string windowId, string requestId, string errorMessage)
        {
            string eventJson = $"{{\"type\":\"window.error\",\"window_id\":\"{windowId}\","
                + $"\"request_id\":\"{requestId}\","
                + $"\"payload\":{{\"error\":\"{errorMessage}\"}},"
                + $"\"timestamp\":{DateTimeOffset.UtcNow.ToUnixTimeMilliseconds() / 1000.0}}}";
            OnWindowEventJson?.Invoke(eventJson);
        }

        // ── Internal: JSON wrapper structs for nested payload parsing ───
        // Unity's JsonUtility requires concrete types for nested objects.

        [Serializable]
        private struct CreateCommandWrapper
        {
            public string type;
            public string window_id;
            public string request_id;
            public CreateCommandPayload payload;
        }

        [Serializable]
        private struct MoveCommandWrapper
        {
            public string type;
            public string window_id;
            public string request_id;
            public MoveCommandPayload payload;
        }

        [Serializable]
        private struct ResizeCommandWrapper
        {
            public string type;
            public string window_id;
            public string request_id;
            public ResizeCommandPayload payload;
        }

        [Serializable]
        private struct RotateCommandWrapper
        {
            public string type;
            public string window_id;
            public string request_id;
            public RotateCommandPayload payload;
        }

        [Serializable]
        private struct FocusCommandWrapper
        {
            public string type;
            public string window_id;
            public string request_id;
            public FocusCommandPayload payload;
        }

        [Serializable]
        private struct SetStateCommandWrapper
        {
            public string type;
            public string window_id;
            public string request_id;
            public SetStateCommandPayload payload;
        }
    }
}
