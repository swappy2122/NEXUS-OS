using System;
using System.Collections.Generic;
using UnityEngine;

namespace Nexus.VR.WindowManager
{
    /// <summary>
    /// Singleton orchestrator for all spatial VR windows.
    ///
    /// Responsibilities:
    /// <list type="bullet">
    ///   <item>Maintains the <c>window_id → VRWindowRenderer</c> mapping.</item>
    ///   <item>Processes <see cref="WindowCommandData"/> from the bridge.</item>
    ///   <item>Sends <see cref="WindowEventData"/> acknowledgements back.</item>
    ///   <item>Manages focus: only one window is focused at a time.</item>
    /// </list>
    /// </summary>
    public class VRWindowManager : MonoBehaviour, IVRWindowManager
    {
        // ── singleton ───────────────────────────────────────────────────

        private static VRWindowManager instance;
        public static VRWindowManager Instance => instance;

        // ── inspector ───────────────────────────────────────────────────

        [Header("Window Prefab")]
        [SerializeField] private GameObject windowPrefab;

        [Header("Bridge")]
        [SerializeField] private BridgeServer bridgeServer;

        [Header("Settings")]
        [SerializeField] private int bridgePort = 8769;
        [SerializeField] private float animationDuration = 0.3f;

        // ── internal state ──────────────────────────────────────────────

        private readonly Dictionary<string, VRWindowRenderer> windows = new();
        private string focusedWindowId;

        // ── events ──────────────────────────────────────────────────────

        public event Action<string> OnWindowCreated;
        public event Action<string> OnWindowClosed;
        public event Action<string> OnWindowFocused;

        // ── properties ──────────────────────────────────────────────────

        public int WindowCount => windows.Count;

        // ── lifecycle ───────────────────────────────────────────────────

        private void Awake()
        {
            if (instance != null && instance != this)
            {
                Destroy(gameObject);
                return;
            }
            instance = this;
        }

        private void Start()
        {
            // Wire bridge events
            if (bridgeServer != null)
            {
                bridgeServer.OnCommandReceived += HandleCommand;
                bridgeServer.StartListening(bridgePort);
                Debug.Log($"[NEXUS WM] VRWindowManager started, bridge on port {bridgePort}");
            }
            else
            {
                Debug.LogWarning("[NEXUS WM] No BridgeServer assigned — running in offline mode");
            }
        }

        private void OnDestroy()
        {
            if (bridgeServer != null)
            {
                bridgeServer.OnCommandReceived -= HandleCommand;
                bridgeServer.Stop();
            }
        }

        // ── command dispatch ────────────────────────────────────────────

        private void HandleCommand(WindowCommandData command)
        {
            Debug.Log($"[NEXUS WM] Received command: {command.command_type} for window '{command.window_id}'");

            switch (command.CommandType)
            {
                case WindowCommandType.Create:
                    HandleCreateCommand(command);
                    break;
                case WindowCommandType.Close:
                    CloseWindow(command.window_id);
                    break;
                case WindowCommandType.Move:
                    HandleMoveCommand(command);
                    break;
                case WindowCommandType.Resize:
                    HandleResizeCommand(command);
                    break;
                case WindowCommandType.Rotate:
                    HandleRotateCommand(command);
                    break;
                case WindowCommandType.Focus:
                    FocusWindow(command.window_id);
                    break;
                case WindowCommandType.Unfocus:
                    UnfocusAll();
                    break;
                case WindowCommandType.SetVisibility:
                    HandleSetVisibilityCommand(command);
                    break;
                case WindowCommandType.SetTitle:
                    HandleSetTitleCommand(command);
                    break;
                case WindowCommandType.Batch:
                    HandleBatchCommand(command);
                    break;
                default:
                    Debug.LogWarning($"[NEXUS WM] Unhandled command type: {command.command_type}");
                    break;
            }
        }

        // ── IVRWindowManager — window lifecycle ─────────────────────────

        public VRWindowRenderer CreateWindow(WindowStateData state)
        {
            if (windows.ContainsKey(state.window_id))
            {
                Debug.LogWarning($"[NEXUS WM] Window '{state.window_id}' already exists");
                return windows[state.window_id];
            }

            // Instantiate from prefab
            GameObject windowGO;
            if (windowPrefab != null)
            {
                windowGO = Instantiate(windowPrefab, state.Position, state.Rotation);
            }
            else
            {
                // Fallback: create a minimal empty GameObject
                windowGO = new GameObject($"VRWindow_{state.window_id}");
                windowGO.transform.position = state.Position;
                windowGO.transform.rotation = state.Rotation;
            }

            windowGO.name = $"VRWindow_{state.window_id}";

            // Attach or get VRWindowRenderer
            var renderer = windowGO.GetComponent<VRWindowRenderer>();
            if (renderer == null)
            {
                renderer = windowGO.AddComponent<VRWindowRenderer>();
            }

            renderer.Initialize(state, animationDuration);
            RegisterRendererEvents(renderer);

            windows[state.window_id] = renderer;

            // Auto-focus new windows
            if (state.is_focused)
            {
                FocusWindow(state.window_id);
            }

            renderer.AnimateOpen();

            Debug.Log($"[NEXUS WM] Created window '{state.title}' (id={state.window_id})");
            OnWindowCreated?.Invoke(state.window_id);

            // Send acknowledgement to Python
            SendEvent(WindowEventData.Create(
                WindowEventType.WindowCreatedAck,
                state.window_id
            ));

            return renderer;
        }

        public bool CloseWindow(string windowId)
        {
            if (!windows.TryGetValue(windowId, out var renderer))
            {
                Debug.LogWarning($"[NEXUS WM] Cannot close — window '{windowId}' not found");
                return false;
            }

            UnregisterRendererEvents(renderer);

            if (focusedWindowId == windowId)
            {
                focusedWindowId = null;
            }

            renderer.AnimateClose(() =>
            {
                windows.Remove(windowId);
                if (renderer != null && renderer.gameObject != null)
                {
                    Destroy(renderer.gameObject);
                }

                Debug.Log($"[NEXUS WM] Closed window '{windowId}'");
                OnWindowClosed?.Invoke(windowId);

                // Send acknowledgement to Python
                SendEvent(WindowEventData.Create(
                    WindowEventType.WindowClosedAck,
                    windowId
                ));
            });

            return true;
        }

        // ── IVRWindowManager — spatial transforms ───────────────────────

        public void MoveWindow(string windowId, Vector3 position, bool animate = true)
        {
            if (windows.TryGetValue(windowId, out var renderer))
            {
                renderer.SetPosition(position, animate);
            }
        }

        public void ResizeWindow(string windowId, Vector2 size, string anchor = "center")
        {
            if (windows.TryGetValue(windowId, out var renderer))
            {
                renderer.SetSize(size, anchor);
            }
        }

        public void RotateWindow(string windowId, Quaternion rotation, bool animate = true)
        {
            if (windows.TryGetValue(windowId, out var renderer))
            {
                renderer.SetRotation(rotation, animate);
            }
        }

        // ── IVRWindowManager — focus management ─────────────────────────

        public void FocusWindow(string windowId)
        {
            if (!windows.ContainsKey(windowId)) return;

            // Unfocus previous
            if (focusedWindowId != null && focusedWindowId != windowId
                && windows.TryGetValue(focusedWindowId, out var prevRenderer))
            {
                prevRenderer.SetFocused(false);
            }

            focusedWindowId = windowId;
            windows[windowId].SetFocused(true);

            OnWindowFocused?.Invoke(windowId);
        }

        public void UnfocusAll()
        {
            foreach (var kvp in windows)
            {
                kvp.Value.SetFocused(false);
            }
            focusedWindowId = null;
        }

        // ── IVRWindowManager — queries ──────────────────────────────────

        public VRWindowRenderer GetWindow(string windowId)
        {
            windows.TryGetValue(windowId, out var renderer);
            return renderer;
        }

        public IReadOnlyList<VRWindowRenderer> GetAllWindows()
        {
            return new List<VRWindowRenderer>(windows.Values);
        }

        // ── command handlers ────────────────────────────────────────────

        private void HandleCreateCommand(WindowCommandData command)
        {
            // Deserialize WindowStateData from the payload
            string json = JsonUtility.ToJson(command.payload);
            // In practice, we'd use a proper JSON deserializer.
            // For now, construct from the payload dictionary.
            var state = new WindowStateData
            {
                window_id = command.window_id,
                title = GetPayloadString(command.payload, "title", "New Window"),
                app_id = GetPayloadString(command.payload, "app_id", null),
                workspace_id = GetPayloadString(command.payload, "workspace_id", "workspace_1"),
                content_type = GetPayloadString(command.payload, "content_type", "custom"),
                is_focused = GetPayloadBool(command.payload, "is_focused", true),
                is_visible = GetPayloadBool(command.payload, "is_visible", true),
                is_pinned = GetPayloadBool(command.payload, "is_pinned", false),
                z_order = GetPayloadInt(command.payload, "z_order", 0),
                position = GetPayloadVector3(command.payload, "position"),
                rotation = GetPayloadQuaternion(command.payload, "rotation"),
                size = GetPayloadSize(command.payload, "size"),
                metadata = new Dictionary<string, object>(),
            };

            CreateWindow(state);
        }

        private void HandleMoveCommand(WindowCommandData command)
        {
            var position = GetPayloadVector3(command.payload, "position");
            bool animate = GetPayloadBool(command.payload, "animate", true);
            MoveWindow(command.window_id, position.ToVector3(), animate);
        }

        private void HandleResizeCommand(WindowCommandData command)
        {
            var size = GetPayloadSize(command.payload, "size");
            string anchor = GetPayloadString(command.payload, "anchor", "center");
            ResizeWindow(command.window_id, size.ToVector2(), anchor);
        }

        private void HandleRotateCommand(WindowCommandData command)
        {
            var rotation = GetPayloadQuaternion(command.payload, "rotation");
            bool animate = GetPayloadBool(command.payload, "animate", true);
            RotateWindow(command.window_id, rotation.ToQuaternion(), animate);
        }

        private void HandleSetVisibilityCommand(WindowCommandData command)
        {
            bool visible = GetPayloadBool(command.payload, "visible", true);
            if (windows.TryGetValue(command.window_id, out var renderer))
            {
                renderer.SetVisible(visible);
            }
        }

        private void HandleSetTitleCommand(WindowCommandData command)
        {
            string title = GetPayloadString(command.payload, "title", "");
            if (windows.TryGetValue(command.window_id, out var renderer))
            {
                renderer.SetTitle(title);
            }
        }

        private void HandleBatchCommand(WindowCommandData batchCommand)
        {
            // Batch commands contain a list of sub-commands in the payload
            // Iterate and dispatch each one
            if (batchCommand.payload != null
                && batchCommand.payload.TryGetValue("commands", out var commandsObj)
                && commandsObj is List<object> commandList)
            {
                Debug.Log($"[NEXUS WM] Processing batch of {commandList.Count} commands");
                // Each sub-command would need to be deserialized and dispatched
                // Full implementation would parse each JSON command object
            }
        }

        // ── renderer event wiring ───────────────────────────────────────

        private void RegisterRendererEvents(VRWindowRenderer renderer)
        {
            renderer.OnGrabEnd += HandleRendererGrabEnd;
            renderer.OnPositionChanged += HandleRendererPositionChanged;
            renderer.OnRotationChanged += HandleRendererRotationChanged;
            renderer.OnSizeChanged += HandleRendererSizeChanged;
            renderer.OnCloseRequested += HandleRendererCloseRequested;
            renderer.OnFocusRequested += HandleRendererFocusRequested;
        }

        private void UnregisterRendererEvents(VRWindowRenderer renderer)
        {
            renderer.OnGrabEnd -= HandleRendererGrabEnd;
            renderer.OnPositionChanged -= HandleRendererPositionChanged;
            renderer.OnRotationChanged -= HandleRendererRotationChanged;
            renderer.OnSizeChanged -= HandleRendererSizeChanged;
            renderer.OnCloseRequested -= HandleRendererCloseRequested;
            renderer.OnFocusRequested -= HandleRendererFocusRequested;
        }

        private void HandleRendererGrabEnd(string windowId, Vector3 position)
        {
            SendEvent(WindowEventData.Create(
                WindowEventType.PositionChanged,
                windowId,
                new Dictionary<string, object>
                {
                    ["position"] = new Dictionary<string, object>
                    {
                        ["x"] = position.x,
                        ["y"] = position.y,
                        ["z"] = position.z,
                    }
                }
            ));
        }

        private void HandleRendererPositionChanged(string windowId, Vector3 position)
        {
            // Continuous position updates during grab — throttled in renderer
        }

        private void HandleRendererRotationChanged(string windowId, Quaternion rotation)
        {
            SendEvent(WindowEventData.Create(
                WindowEventType.RotationChanged,
                windowId,
                new Dictionary<string, object>
                {
                    ["rotation"] = new Dictionary<string, object>
                    {
                        ["x"] = rotation.x,
                        ["y"] = rotation.y,
                        ["z"] = rotation.z,
                        ["w"] = rotation.w,
                    }
                }
            ));
        }

        private void HandleRendererSizeChanged(string windowId, Vector2 size)
        {
            SendEvent(WindowEventData.Create(
                WindowEventType.SizeChanged,
                windowId,
                new Dictionary<string, object>
                {
                    ["size"] = new Dictionary<string, object>
                    {
                        ["width"] = size.x,
                        ["height"] = size.y,
                    }
                }
            ));
        }

        private void HandleRendererCloseRequested(string windowId)
        {
            SendEvent(WindowEventData.Create(
                WindowEventType.InteractionCloseRequest,
                windowId
            ));
        }

        private void HandleRendererFocusRequested(string windowId)
        {
            FocusWindow(windowId);
            SendEvent(WindowEventData.Create(
                WindowEventType.InteractionFocusRequest,
                windowId
            ));
        }

        // ── bridge helpers ──────────────────────────────────────────────

        private void SendEvent(WindowEventData eventData)
        {
            if (bridgeServer != null && bridgeServer.IsConnected)
            {
                bridgeServer.SendEvent(eventData);
            }
        }

        // ── payload extraction helpers ──────────────────────────────────

        private static string GetPayloadString(Dictionary<string, object> payload, string key, string fallback)
        {
            if (payload != null && payload.TryGetValue(key, out var val) && val is string s)
                return s;
            return fallback;
        }

        private static bool GetPayloadBool(Dictionary<string, object> payload, string key, bool fallback)
        {
            if (payload != null && payload.TryGetValue(key, out var val))
            {
                if (val is bool b) return b;
                if (val is string s && bool.TryParse(s, out bool parsed)) return parsed;
            }
            return fallback;
        }

        private static int GetPayloadInt(Dictionary<string, object> payload, string key, int fallback)
        {
            if (payload != null && payload.TryGetValue(key, out var val))
            {
                if (val is int i) return i;
                if (val is long l) return (int)l;
                if (val is double d) return (int)d;
                if (val is string s && int.TryParse(s, out int parsed)) return parsed;
            }
            return fallback;
        }

        private static float GetPayloadFloat(Dictionary<string, object> payload, string key, float fallback)
        {
            if (payload != null && payload.TryGetValue(key, out var val))
            {
                if (val is float f) return f;
                if (val is double d) return (float)d;
                if (val is int i) return i;
                if (val is string s && float.TryParse(s, out float parsed)) return parsed;
            }
            return fallback;
        }

        private static SerializableVector3 GetPayloadVector3(Dictionary<string, object> payload, string key)
        {
            if (payload != null && payload.TryGetValue(key, out var val) && val is Dictionary<string, object> dict)
            {
                return new SerializableVector3(
                    GetPayloadFloat(dict, "x", 0f),
                    GetPayloadFloat(dict, "y", 1.5f),
                    GetPayloadFloat(dict, "z", 2.5f)
                );
            }
            return new SerializableVector3(0f, 1.5f, 2.5f);
        }

        private static SerializableQuaternion GetPayloadQuaternion(Dictionary<string, object> payload, string key)
        {
            if (payload != null && payload.TryGetValue(key, out var val) && val is Dictionary<string, object> dict)
            {
                return new SerializableQuaternion(
                    GetPayloadFloat(dict, "x", 0f),
                    GetPayloadFloat(dict, "y", 0f),
                    GetPayloadFloat(dict, "z", 0f),
                    GetPayloadFloat(dict, "w", 1f)
                );
            }
            return SerializableQuaternion.Identity;
        }

        private static SerializableVector2 GetPayloadSize(Dictionary<string, object> payload, string key)
        {
            if (payload != null && payload.TryGetValue(key, out var val) && val is Dictionary<string, object> dict)
            {
                return new SerializableVector2(
                    GetPayloadFloat(dict, "width", 0.8f),
                    GetPayloadFloat(dict, "height", 0.5f)
                );
            }
            return new SerializableVector2(0.8f, 0.5f);
        }
    }
}
