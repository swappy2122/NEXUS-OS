using System;
using System.Collections.Generic;
using UnityEngine;

namespace Nexus.VR.WindowManager
{
    /// <summary>
    /// Interface for the VR Window Manager singleton.
    ///
    /// Manages the full lifecycle of spatial windows: creation, destruction,
    /// spatial transforms, focus state, and workspace filtering.
    ///
    /// The implementation (<see cref="VRWindowManager"/>) owns the mapping
    /// from <c>window_id → VRWindowRenderer</c> and is the single point of
    /// contact for the <see cref="BridgeServer"/> when processing
    /// <see cref="WindowCommandData"/> messages from the Python agent layer.
    /// </summary>
    public interface IVRWindowManager
    {
        // ── window lifecycle ────────────────────────────────────────────

        /// <summary>
        /// Instantiate a new spatial window from the given state data.
        /// </summary>
        VRWindowRenderer CreateWindow(WindowStateData state);

        /// <summary>
        /// Destroy the window with the given ID.  Returns false if no such window exists.
        /// </summary>
        bool CloseWindow(string windowId);

        // ── spatial transforms ──────────────────────────────────────────

        /// <summary>
        /// Move a window to a new world-space position, optionally with animation.
        /// </summary>
        void MoveWindow(string windowId, Vector3 position, bool animate = true);

        /// <summary>
        /// Resize a window.  <paramref name="anchor"/> determines which
        /// corner / edge stays fixed during the resize.
        /// </summary>
        void ResizeWindow(string windowId, Vector2 size, string anchor = "center");

        /// <summary>
        /// Rotate a window to a new orientation, optionally with animation.
        /// </summary>
        void RotateWindow(string windowId, Quaternion rotation, bool animate = true);

        // ── focus management ────────────────────────────────────────────

        /// <summary>
        /// Focus the specified window (unfocuses any previously focused window).
        /// </summary>
        void FocusWindow(string windowId);

        /// <summary>
        /// Remove focus from all windows.
        /// </summary>
        void UnfocusAll();

        // ── queries ─────────────────────────────────────────────────────

        /// <summary>
        /// Look up a window renderer by ID.  Returns null if not found.
        /// </summary>
        VRWindowRenderer GetWindow(string windowId);

        /// <summary>
        /// Get all active window renderers.
        /// </summary>
        IReadOnlyList<VRWindowRenderer> GetAllWindows();

        /// <summary>
        /// Total number of active windows.
        /// </summary>
        int WindowCount { get; }

        // ── events ──────────────────────────────────────────────────────

        /// <summary>Fired after a window has been successfully created.</summary>
        event Action<string> OnWindowCreated;

        /// <summary>Fired after a window has been destroyed.</summary>
        event Action<string> OnWindowClosed;

        /// <summary>Fired when a window gains focus.</summary>
        event Action<string> OnWindowFocused;
    }
}
