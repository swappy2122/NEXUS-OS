using System;
using System.Collections;
using UnityEngine;
using UnityEngine.UI;
using Nexus.VR.UI;

namespace Nexus.VR.Window
{
    /// <summary>
    /// Runtime representation of a single VR window in the Unity scene.
    ///
    /// Extends <see cref="SpatialUIPanel"/> with window-specific state
    /// (ID, app link, grab interaction, animated transforms).
    ///
    /// This component is the Unity-side mirror of Python's <c>VRWindow</c>.
    /// It does NOT own the canonical state — it reacts to commands
    /// dispatched by <see cref="VRWindowManager"/>.
    /// </summary>
    public class VRWindowHandle : SpatialUIPanel
    {
        // ── Identity (set once at creation, immutable) ──────────────────

        public string WindowId { get; private set; }
        public string AppId { get; private set; }

        // ── State ───────────────────────────────────────────────────────

        public VRWindowState State { get; private set; } = VRWindowState.Creating;
        public VRWindowAnchor Anchor { get; private set; } = VRWindowAnchor.WorldFixed;
        public int WorkspaceIndex { get; private set; }
        public bool IsFocusedWindow { get; private set; }
        public float PanelWidth { get; private set; } = 0.8f;
        public float PanelHeight { get; private set; } = 0.5f;

        // ── Visual references ───────────────────────────────────────────

        [Header("Window Chrome")]
        [SerializeField] private Text windowTitleText;
        [SerializeField] private Image focusHighlight;
        [SerializeField] private Image windowBackground;
        [SerializeField] private SpatialButton closeButton;

        [Header("Animation")]
        [SerializeField] private float defaultAnimDuration = 0.3f;
        [SerializeField] private AnimationCurve easeCurve = AnimationCurve.EaseInOut(0f, 0f, 1f, 1f);

        // ── Focus / Highlight Colors ────────────────────────────────────

        private static readonly Color FocusedColor = new(0f, 0.69f, 0.85f, 0.4f);   // #00B0D9
        private static readonly Color UnfocusedColor = new(0.04f, 0.05f, 0.07f, 0.2f);  // #0B0E13

        // ── Running coroutines (for cancellation) ───────────────────────

        private Coroutine _moveCoroutine;
        private Coroutine _resizeCoroutine;
        private Coroutine _rotateCoroutine;

        // ── Events ─────────────────────────────────────────────────────

        /// <summary>Raised when this window is closed (before destruction).</summary>
        public event Action<VRWindowHandle> OnWindowClosed;

        /// <summary>Raised when this window gains or loses focus.</summary>
        public event Action<VRWindowHandle, bool> OnWindowFocusChanged;

        /// <summary>Raised when a user-initiated grab move completes, with final position.</summary>
        public event Action<VRWindowHandle, Vector3> OnWindowUserMoved;

        /// <summary>Raised when a user-initiated grab rotation completes.</summary>
        public event Action<VRWindowHandle, Quaternion> OnWindowUserRotated;

        // ── Lifecycle ───────────────────────────────────────────────────

        /// <summary>
        /// Initialize this handle from a create command payload.
        /// Called once by <see cref="VRWindowManager"/> immediately after instantiation.
        /// </summary>
        public void Initialize(CreateCommandPayload data, string windowId)
        {
            WindowId = windowId;
            AppId = data.app_id;
            WorkspaceIndex = data.workspace_index;
            Anchor = WindowEnumParser.ParseAnchor(data.anchor);
            PanelWidth = data.size.width;
            PanelHeight = data.size.height;

            // Apply spatial transform
            transform.position = data.transform.ToPosition();
            transform.rotation = data.transform.ToRotation();
            Vector3 scale = data.transform.ToScale();
            if (scale.sqrMagnitude < 0.01f) scale = Vector3.one;
            transform.localScale = scale;

            // Apply panel size to RectTransform
            RectTransform rt = GetComponent<RectTransform>();
            if (rt != null)
            {
                // Convert meters to Unity UI units (assuming 1000 pixels/meter canvas scale)
                float pixelsPerMeter = 1000f;
                rt.sizeDelta = new Vector2(
                    PanelWidth * pixelsPerMeter,
                    PanelHeight * pixelsPerMeter
                );
            }

            // Set title
            SetTitle(data.title);
            if (windowTitleText != null)
            {
                windowTitleText.text = data.title;
            }

            // Wire close button
            if (closeButton != null)
            {
                closeButton.onClick.AddListener(RequestClose);
            }

            // Transition to Open
            State = VRWindowState.Open;
            Open();

            Debug.Log($"[NEXUS Window] Initialized: {WindowId} ({data.title})");
        }

        /// <summary>Apply an authoritative REST snapshot without emitting bridge events.</summary>
        public void ApplySnapshot(VRWindowSnapshot data)
        {
            if (data == null || data.window_id != WindowId) return;

            AppId = data.app_id ?? AppId;
            WorkspaceIndex = data.workspace_index;
            Anchor = WindowEnumParser.ParseAnchor(data.anchor);
            SetTitle(data.title ?? "");
            if (windowTitleText != null) windowTitleText.text = data.title ?? "";

            transform.position = data.transform.ToPosition();
            transform.rotation = data.transform.ToRotation();
            Vector3 scale = data.transform.ToScale();
            transform.localScale = scale.sqrMagnitude < 0.01f ? Vector3.one : scale;
            ResizeTo(data.size.width, data.size.height, animate: false);
            SetStateWithoutDestroy(WindowEnumParser.ParseState(data.state));
        }

        private void SetStateWithoutDestroy(VRWindowState newState)
        {
            State = newState;
            switch (newState)
            {
                case VRWindowState.Open:
                case VRWindowState.Maximized:
                    Open();
                    break;
                case VRWindowState.Minimized:
                    Close();
                    break;
            }
        }

        /// <summary>
        /// Tear down this window handle.
        /// Called by <see cref="VRWindowManager"/> when a close command is received.
        /// </summary>
        public void DestroyWindow(bool notify = true)
        {
            State = VRWindowState.Closing;
            if (notify) OnWindowClosed?.Invoke(this);

            // Cancel running animations
            CancelAnimations();

            Close();
            State = VRWindowState.Closed;

            // Schedule actual GameObject destruction
            Destroy(gameObject, 0.1f);
        }

        // ── Command Handlers (called by VRWindowManager) ────────────────

        /// <summary>
        /// Animate movement to a new world position.
        /// </summary>
        public void MoveTo(Vector3 targetPosition, bool animate = true, float duration = -1f)
        {
            if (duration < 0f) duration = defaultAnimDuration;

            if (_moveCoroutine != null) StopCoroutine(_moveCoroutine);

            if (animate && duration > 0f)
            {
                _moveCoroutine = StartCoroutine(AnimatePosition(targetPosition, duration));
            }
            else
            {
                transform.position = targetPosition;
            }
        }

        /// <summary>
        /// Animate resize to new dimensions (in meters).
        /// </summary>
        public void ResizeTo(float width, float height, bool animate = true, float duration = -1f)
        {
            if (duration < 0f) duration = defaultAnimDuration;

            PanelWidth = width;
            PanelHeight = height;

            RectTransform rt = GetComponent<RectTransform>();
            if (rt == null) return;

            float pixelsPerMeter = 1000f;
            Vector2 targetSizeDelta = new(width * pixelsPerMeter, height * pixelsPerMeter);

            if (_resizeCoroutine != null) StopCoroutine(_resizeCoroutine);

            if (animate && duration > 0f)
            {
                _resizeCoroutine = StartCoroutine(AnimateSize(rt, targetSizeDelta, duration));
            }
            else
            {
                rt.sizeDelta = targetSizeDelta;
            }
        }

        /// <summary>
        /// Animate rotation to a new orientation.
        /// </summary>
        public void RotateTo(Quaternion targetRotation, bool animate = true, float duration = -1f)
        {
            if (duration < 0f) duration = defaultAnimDuration;

            if (_rotateCoroutine != null) StopCoroutine(_rotateCoroutine);

            if (animate && duration > 0f)
            {
                _rotateCoroutine = StartCoroutine(AnimateRotation(targetRotation, duration));
            }
            else
            {
                transform.rotation = targetRotation;
            }
        }

        /// <summary>
        /// Set or clear focus on this window.
        /// </summary>
        public new void SetFocused(bool focused)
        {
            bool changed = IsFocusedWindow != focused;
            IsFocusedWindow = focused;

            // Update visual highlight
            if (focusHighlight != null)
            {
                focusHighlight.color = focused ? FocusedColor : UnfocusedColor;
            }

            // Slight scale emphasis
            base.SetFocused(focused);

            if (changed)
            {
                OnWindowFocusChanged?.Invoke(this, focused);
            }
        }

        /// <summary>
        /// Set lifecycle state (minimize, maximize, restore).
        /// </summary>
        public void SetState(VRWindowState newState)
        {
            VRWindowState oldState = State;
            State = newState;

            switch (newState)
            {
                case VRWindowState.Open:
                    Open();
                    break;

                case VRWindowState.Minimized:
                    Close();
                    break;

                case VRWindowState.Maximized:
                    Open();
                    // Expand to comfortable FOV size
                    ResizeTo(1.6f, 1.0f, animate: true);
                    break;

                case VRWindowState.Closing:
                case VRWindowState.Closed:
                    DestroyWindow();
                    break;
            }

            Debug.Log($"[NEXUS Window] {WindowId}: {oldState} → {newState}");
        }

        // ── User-Initiated Actions ─────────────────────────────────────

        /// <summary>
        /// Called when the user clicks the close button on the window chrome.
        /// Raises an event so VRWindowManager can notify the Python bridge.
        /// </summary>
        private void RequestClose()
        {
            OnWindowClosed?.Invoke(this);
        }

        /// <summary>
        /// Call this when a grab interaction ends to notify the bridge
        /// of the final position (so Python can reconcile state).
        /// </summary>
        public void NotifyUserMoveComplete()
        {
            OnWindowUserMoved?.Invoke(this, transform.position);
        }

        /// <summary>
        /// Call this when a grab rotation ends to notify the bridge.
        /// </summary>
        public void NotifyUserRotateComplete()
        {
            OnWindowUserRotated?.Invoke(this, transform.rotation);
        }

        // ── Animation Coroutines ───────────────────────────────────────

        private IEnumerator AnimatePosition(Vector3 target, float duration)
        {
            Vector3 start = transform.position;
            float elapsed = 0f;

            while (elapsed < duration)
            {
                elapsed += Time.deltaTime;
                float t = easeCurve.Evaluate(Mathf.Clamp01(elapsed / duration));
                transform.position = Vector3.Lerp(start, target, t);
                yield return null;
            }

            transform.position = target;
            _moveCoroutine = null;
        }

        private IEnumerator AnimateSize(RectTransform rt, Vector2 targetSize, float duration)
        {
            Vector2 startSize = rt.sizeDelta;
            float elapsed = 0f;

            while (elapsed < duration)
            {
                elapsed += Time.deltaTime;
                float t = easeCurve.Evaluate(Mathf.Clamp01(elapsed / duration));
                rt.sizeDelta = Vector2.Lerp(startSize, targetSize, t);
                yield return null;
            }

            rt.sizeDelta = targetSize;
            _resizeCoroutine = null;
        }

        private IEnumerator AnimateRotation(Quaternion target, float duration)
        {
            Quaternion start = transform.rotation;
            float elapsed = 0f;

            while (elapsed < duration)
            {
                elapsed += Time.deltaTime;
                float t = easeCurve.Evaluate(Mathf.Clamp01(elapsed / duration));
                transform.rotation = Quaternion.Slerp(start, target, t);
                yield return null;
            }

            transform.rotation = target;
            _rotateCoroutine = null;
        }

        private void CancelAnimations()
        {
            if (_moveCoroutine != null)
            {
                StopCoroutine(_moveCoroutine);
                _moveCoroutine = null;
            }
            if (_resizeCoroutine != null)
            {
                StopCoroutine(_resizeCoroutine);
                _resizeCoroutine = null;
            }
            if (_rotateCoroutine != null)
            {
                StopCoroutine(_rotateCoroutine);
                _rotateCoroutine = null;
            }
        }

        // ── Introspection ──────────────────────────────────────────────

        /// <summary>
        /// Build a serializable snapshot of this window's current state
        /// for sending back to the Python bridge.
        /// </summary>
        public SerializableTransform GetCurrentTransform()
        {
            return SerializableTransform.FromUnity(transform);
        }
    }
}
