using System;
using System.Collections.Generic;
using UnityEngine;

namespace Nexus.VR.WindowManager
{
    /// <summary>
    /// Interface for an individual spatial window's visual representation.
    ///
    /// Each VR window is a <see cref="MonoBehaviour"/> that owns its Canvas,
    /// collider, animations, and interaction hooks.  The
    /// <see cref="IVRWindowManager"/> creates and holds references to renderers.
    ///
    /// Renderers emit events when the user physically interacts with the window
    /// (grab, resize, gaze-focus, close button).  These events flow back through
    /// the <see cref="IBridgeServer"/> to the Python <c>WindowAgent</c> for
    /// state reconciliation.
    /// </summary>
    public interface IVRWindowRenderer
    {
        // ── identity ────────────────────────────────────────────────────

        /// <summary>Unique identifier matching the Python WindowState.window_id.</summary>
        string WindowId { get; }

        /// <summary>Display title shown on the window frame.</summary>
        string Title { get; }

        /// <summary>Whether this window currently has focus.</summary>
        bool IsFocused { get; }

        /// <summary>Whether this window is visible (rendered and interactive).</summary>
        bool IsVisible { get; }

        // ── spatial setters ─────────────────────────────────────────────

        /// <summary>Set the world-space position, optionally animating the transition.</summary>
        void SetPosition(Vector3 position, bool animate = true);

        /// <summary>Set the world-space rotation, optionally animating the transition.</summary>
        void SetRotation(Quaternion rotation, bool animate = true);

        /// <summary>
        /// Set the window dimensions.  <paramref name="anchor"/> determines
        /// which edge/corner stays fixed (<c>"center"</c>, <c>"top-left"</c>, etc.).
        /// </summary>
        void SetSize(Vector2 size, string anchor = "center");

        // ── display setters ─────────────────────────────────────────────

        /// <summary>Update the title bar text.</summary>
        void SetTitle(string title);

        /// <summary>Set focus highlight state.</summary>
        void SetFocused(bool focused);

        /// <summary>Toggle visibility (hides canvas and disables interaction).</summary>
        void SetVisible(bool visible);

        /// <summary>
        /// Switch the content rendered inside the window frame.
        /// </summary>
        void SetContent(WindowContentType contentType, Dictionary<string, object> data);

        // ── animation lifecycle ─────────────────────────────────────────

        /// <summary>Play the window-open entrance animation.</summary>
        void AnimateOpen();

        /// <summary>
        /// Play the window-close exit animation, then invoke <paramref name="onComplete"/>.
        /// </summary>
        void AnimateClose(Action onComplete);

        // ── interaction events (emitted by the renderer) ────────────────

        /// <summary>User started grabbing this window. Payload: (windowId, currentPosition).</summary>
        event Action<string, Vector3> OnGrabStart;

        /// <summary>User released the grab. Payload: (windowId, finalPosition).</summary>
        event Action<string, Vector3> OnGrabEnd;

        /// <summary>Window position changed (during or after a grab). Payload: (windowId, newPosition).</summary>
        event Action<string, Vector3> OnPositionChanged;

        /// <summary>Window rotation changed. Payload: (windowId, newRotation).</summary>
        event Action<string, Quaternion> OnRotationChanged;

        /// <summary>Window was resized. Payload: (windowId, newSize).</summary>
        event Action<string, Vector2> OnSizeChanged;

        /// <summary>User requested to close this window (e.g. close button, gesture).</summary>
        event Action<string> OnCloseRequested;

        /// <summary>User wants to focus this window (gaze dwell, click, etc.).</summary>
        event Action<string> OnFocusRequested;
    }
}
