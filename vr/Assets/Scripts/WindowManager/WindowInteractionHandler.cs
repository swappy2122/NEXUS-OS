using UnityEngine;
using UnityEngine.XR.Interaction.Toolkit;

namespace Nexus.VR.WindowManager
{
    /// <summary>
    /// Translates XR Interaction Toolkit events on a VR window into
    /// <see cref="VRWindowRenderer"/> notification calls.
    ///
    /// Attach this component alongside <see cref="VRWindowRenderer"/> on
    /// each window GameObject.  It listens for grab, hover, and select
    /// events from the XR Interaction Toolkit and routes them to the
    /// renderer's notification methods.
    ///
    /// For the desktop simulator fallback (no XR hardware), this also
    /// responds to standard mouse events via the gaze pointer.
    /// </summary>
    [RequireComponent(typeof(VRWindowRenderer))]
    public class WindowInteractionHandler : MonoBehaviour
    {
        // ── references ──────────────────────────────────────────────────

        private VRWindowRenderer windowRenderer;

        [Header("Grab Settings")]
        [SerializeField] private bool allowGrab = true;
        [SerializeField] private bool allowResize = true;
        [SerializeField] private float resizeHandleSize = 0.05f;

        [Header("Focus Settings")]
        [SerializeField] private float gazeFocusDwellTime = 0.5f;

        // ── state ───────────────────────────────────────────────────────

        private bool isGrabbing;
        private bool isHovering;
        private float hoverTime;
        private Vector3 grabOffset;
        private Transform grabController;

        // ── lifecycle ───────────────────────────────────────────────────

        private void Awake()
        {
            windowRenderer = GetComponent<VRWindowRenderer>();
        }

        private void Update()
        {
            // Track gaze dwell for focus
            if (isHovering && !isGrabbing)
            {
                hoverTime += Time.deltaTime;
                if (hoverTime >= gazeFocusDwellTime)
                {
                    windowRenderer.NotifyFocusRequested();
                    hoverTime = 0f; // Reset to avoid repeated focus calls
                }
            }

            // Update position during grab
            if (isGrabbing && grabController != null)
            {
                transform.position = grabController.position + grabOffset;
            }
        }

        // ── XR Interaction Toolkit hooks ────────────────────────────────

        // These methods are designed to be called by XR Interactable events
        // configured in the Unity Inspector, or wired programmatically.

        /// <summary>
        /// Called when an XR controller hovers over this window.
        /// Wire to <c>XRBaseInteractable.hoverEntered</c>.
        /// </summary>
        public void OnHoverEnter(HoverEnterEventArgs args)
        {
            isHovering = true;
            hoverTime = 0f;
        }

        /// <summary>
        /// Called when an XR controller stops hovering over this window.
        /// Wire to <c>XRBaseInteractable.hoverExited</c>.
        /// </summary>
        public void OnHoverExit(HoverExitEventArgs args)
        {
            isHovering = false;
            hoverTime = 0f;
        }

        /// <summary>
        /// Called when the user grabs this window.
        /// Wire to <c>XRGrabInteractable.selectEntered</c>.
        /// </summary>
        public void OnSelectEnter(SelectEnterEventArgs args)
        {
            if (!allowGrab) return;

            isGrabbing = true;
            grabController = args.interactorObject.transform;
            grabOffset = transform.position - grabController.position;

            windowRenderer.NotifyGrabStart();
        }

        /// <summary>
        /// Called when the user releases the grab.
        /// Wire to <c>XRGrabInteractable.selectExited</c>.
        /// </summary>
        public void OnSelectExit(SelectExitEventArgs args)
        {
            if (!isGrabbing) return;

            isGrabbing = false;
            grabController = null;

            windowRenderer.NotifyGrabEnd();
        }

        /// <summary>
        /// Called when the user activates (e.g. trigger press) while
        /// hovering over this window — treated as a focus click.
        /// Wire to <c>XRBaseInteractable.activated</c>.
        /// </summary>
        public void OnActivate(ActivateEventArgs args)
        {
            windowRenderer.NotifyFocusRequested();
        }

        // ── desktop simulator fallback ──────────────────────────────────

        /// <summary>
        /// Mouse-based interaction for the desktop simulator.
        /// </summary>
        private void OnMouseDown()
        {
            windowRenderer.NotifyFocusRequested();
        }

        /// <summary>
        /// Desktop close button fallback (right-click).
        /// </summary>
        private void OnMouseOver()
        {
            if (Input.GetMouseButtonDown(1))
            {
                windowRenderer.NotifyCloseRequested();
            }
        }
    }
}
