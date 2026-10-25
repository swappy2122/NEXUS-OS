using System;
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.UI;

namespace Nexus.VR.WindowManager
{
    /// <summary>
    /// MonoBehaviour attached to each spatial VR window.
    ///
    /// Owns the Canvas, visual frame, title bar, content area,
    /// focus highlight, and spatial interaction hooks.
    ///
    /// The renderer is created and initialized by <see cref="VRWindowManager"/>
    /// and communicates user interactions back via events.
    /// </summary>
    [RequireComponent(typeof(Canvas))]
    [RequireComponent(typeof(BoxCollider))]
    public class VRWindowRenderer : MonoBehaviour, IVRWindowRenderer
    {
        // ── identity ────────────────────────────────────────────────────

        private string windowId;
        private string windowTitle;
        private WindowContentType contentType;
        private bool isFocused;
        private bool isVisible = true;

        // ── spatial animation ───────────────────────────────────────────

        private float animDuration = 0.3f;
        private Vector3 targetPosition;
        private Quaternion targetRotation;
        private Vector3 targetScale;
        private bool isAnimatingPosition;
        private bool isAnimatingRotation;
        private bool isAnimatingScale;
        private float animProgress;

        // ── references ──────────────────────────────────────────────────

        private Canvas canvas;
        private CanvasGroup canvasGroup;
        private BoxCollider interactionCollider;
        private Text titleText;
        private RectTransform contentContainer;

        // ── IVRWindowRenderer properties ────────────────────────────────

        public string WindowId => windowId;
        public string Title => windowTitle;
        public bool IsFocused => isFocused;
        public bool IsVisible => isVisible;

        // ── events ──────────────────────────────────────────────────────

        public event Action<string, Vector3> OnGrabStart;
        public event Action<string, Vector3> OnGrabEnd;
        public event Action<string, Vector3> OnPositionChanged;
        public event Action<string, Quaternion> OnRotationChanged;
        public event Action<string, Vector2> OnSizeChanged;
        public event Action<string> OnCloseRequested;
        public event Action<string> OnFocusRequested;

        // ── initialization ──────────────────────────────────────────────

        /// <summary>
        /// Called by <see cref="VRWindowManager.CreateWindow"/> to initialize
        /// the renderer with state data from the Python agent.
        /// </summary>
        public void Initialize(WindowStateData state, float animationDuration = 0.3f)
        {
            windowId = state.window_id;
            windowTitle = state.title;
            contentType = state.ContentType;
            isFocused = state.is_focused;
            isVisible = state.is_visible;
            animDuration = animationDuration;

            // Cache components
            canvas = GetComponent<Canvas>();
            canvas.renderMode = RenderMode.WorldSpace;

            canvasGroup = GetComponent<CanvasGroup>();
            if (canvasGroup == null)
            {
                canvasGroup = gameObject.AddComponent<CanvasGroup>();
            }

            interactionCollider = GetComponent<BoxCollider>();

            // Set initial transform
            transform.position = state.Position;
            transform.rotation = state.Rotation;
            targetPosition = state.Position;
            targetRotation = state.Rotation;
            targetScale = Vector3.one;

            // Apply window size to the RectTransform
            var rectTransform = GetComponent<RectTransform>();
            if (rectTransform != null)
            {
                rectTransform.sizeDelta = new Vector2(
                    state.Size.x * 1000f,  // meters to UI units (rough)
                    state.Size.y * 1000f
                );
            }

            // Update collider to match window size
            UpdateColliderSize(state.Size);

            // Set title if we have a title text element
            titleText = GetComponentInChildren<Text>();
            if (titleText != null)
            {
                titleText.text = windowTitle;
            }

            Debug.Log($"[NEXUS WR] Initialized window '{windowTitle}' (id={windowId}, type={contentType})");
        }

        // ── MonoBehaviour ───────────────────────────────────────────────

        private void LateUpdate()
        {
            if (!isVisible) return;

            // Animate position
            if (isAnimatingPosition)
            {
                animProgress += Time.deltaTime / animDuration;
                if (animProgress >= 1f)
                {
                    transform.position = targetPosition;
                    isAnimatingPosition = false;
                }
                else
                {
                    transform.position = Vector3.Lerp(
                        transform.position, targetPosition,
                        EaseOutCubic(animProgress)
                    );
                }
            }

            // Animate rotation
            if (isAnimatingRotation)
            {
                transform.rotation = Quaternion.Slerp(
                    transform.rotation, targetRotation,
                    Time.deltaTime / animDuration * 5f
                );

                if (Quaternion.Angle(transform.rotation, targetRotation) < 0.1f)
                {
                    transform.rotation = targetRotation;
                    isAnimatingRotation = false;
                }
            }

            // Animate scale
            if (isAnimatingScale)
            {
                transform.localScale = Vector3.Lerp(
                    transform.localScale, targetScale,
                    Time.deltaTime / animDuration * 5f
                );

                if (Vector3.Distance(transform.localScale, targetScale) < 0.001f)
                {
                    transform.localScale = targetScale;
                    isAnimatingScale = false;
                }
            }
        }

        // ── IVRWindowRenderer — spatial setters ─────────────────────────

        public void SetPosition(Vector3 position, bool animate = true)
        {
            targetPosition = position;

            if (animate)
            {
                isAnimatingPosition = true;
                animProgress = 0f;
            }
            else
            {
                transform.position = position;
                isAnimatingPosition = false;
            }
        }

        public void SetRotation(Quaternion rotation, bool animate = true)
        {
            targetRotation = rotation;

            if (animate)
            {
                isAnimatingRotation = true;
            }
            else
            {
                transform.rotation = rotation;
                isAnimatingRotation = false;
            }
        }

        public void SetSize(Vector2 size, string anchor = "center")
        {
            var rectTransform = GetComponent<RectTransform>();
            if (rectTransform != null)
            {
                // Adjust pivot based on anchor
                rectTransform.pivot = anchor switch
                {
                    "top-left" => new Vector2(0f, 1f),
                    "top-right" => new Vector2(1f, 1f),
                    "bottom-left" => new Vector2(0f, 0f),
                    "bottom-right" => new Vector2(1f, 0f),
                    _ => new Vector2(0.5f, 0.5f),  // center
                };

                rectTransform.sizeDelta = new Vector2(
                    size.x * 1000f,
                    size.y * 1000f
                );
            }

            UpdateColliderSize(size);
            OnSizeChanged?.Invoke(windowId, size);
        }

        // ── IVRWindowRenderer — display setters ─────────────────────────

        public void SetTitle(string title)
        {
            windowTitle = title;
            if (titleText != null)
            {
                titleText.text = title;
            }
        }

        public void SetFocused(bool focused)
        {
            isFocused = focused;

            // Visual feedback: slight scale bump on focus
            if (focused)
            {
                targetScale = Vector3.one * 1.02f;
            }
            else
            {
                targetScale = Vector3.one;
            }
            isAnimatingScale = true;

            // TODO: Apply glow / border highlight material on focus
        }

        public void SetVisible(bool visible)
        {
            isVisible = visible;
            gameObject.SetActive(visible);

            if (canvasGroup != null)
            {
                canvasGroup.alpha = visible ? 1f : 0f;
                canvasGroup.interactable = visible;
                canvasGroup.blocksRaycasts = visible;
            }
        }

        public void SetContent(WindowContentType type, Dictionary<string, object> data)
        {
            contentType = type;
            // Content rendering will be handled by content-type-specific
            // sub-components mounted inside the contentContainer.
            Debug.Log($"[NEXUS WR] Window '{windowId}' content set to {type}");
        }

        // ── IVRWindowRenderer — animation lifecycle ─────────────────────

        public void AnimateOpen()
        {
            transform.localScale = Vector3.zero;
            targetScale = Vector3.one;
            isAnimatingScale = true;

            if (canvasGroup != null)
            {
                canvasGroup.alpha = 1f;
                canvasGroup.interactable = true;
                canvasGroup.blocksRaycasts = true;
            }
        }

        public void AnimateClose(Action onComplete)
        {
            targetScale = Vector3.zero;
            isAnimatingScale = true;

            if (canvasGroup != null)
            {
                canvasGroup.interactable = false;
                canvasGroup.blocksRaycasts = false;
            }

            // Invoke callback after animation duration
            StartCoroutine(InvokeDelayed(animDuration, () =>
            {
                onComplete?.Invoke();
            }));
        }

        // ── interaction hooks (called by WindowInteractionHandler) ──────

        /// <summary>Called when the user starts grabbing this window.</summary>
        public void NotifyGrabStart()
        {
            OnGrabStart?.Invoke(windowId, transform.position);
            OnFocusRequested?.Invoke(windowId);
        }

        /// <summary>Called when the user releases the grab.</summary>
        public void NotifyGrabEnd()
        {
            targetPosition = transform.position;
            OnGrabEnd?.Invoke(windowId, transform.position);
            OnPositionChanged?.Invoke(windowId, transform.position);
        }

        /// <summary>Called when the user clicks the close button.</summary>
        public void NotifyCloseRequested()
        {
            OnCloseRequested?.Invoke(windowId);
        }

        /// <summary>Called when the user gazes at or clicks this window.</summary>
        public void NotifyFocusRequested()
        {
            OnFocusRequested?.Invoke(windowId);
        }

        /// <summary>Called when the user changes the rotation via gesture.</summary>
        public void NotifyRotationChanged(Quaternion newRotation)
        {
            targetRotation = newRotation;
            transform.rotation = newRotation;
            OnRotationChanged?.Invoke(windowId, newRotation);
        }

        // ── helpers ─────────────────────────────────────────────────────

        private void UpdateColliderSize(Vector2 size)
        {
            if (interactionCollider != null)
            {
                interactionCollider.size = new Vector3(size.x, size.y, 0.02f);
                interactionCollider.center = Vector3.zero;
            }
        }

        private static float EaseOutCubic(float t)
        {
            return 1f - Mathf.Pow(1f - t, 3f);
        }

        private System.Collections.IEnumerator InvokeDelayed(float delay, Action action)
        {
            yield return new WaitForSeconds(delay);
            action?.Invoke();
        }
    }
}
