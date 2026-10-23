using System;
using UnityEngine;
using UnityEngine.Events;
using UnityEngine.EventSystems;
using UnityEngine.UI;

namespace Nexus.VR.UI
{
    /// <summary>
    /// Minimal functional spatial button supporting VR gaze and pointer interactions.
    /// Provides visual hover feedback, sound/haptic hook, and UnityEvents.
    /// </summary>
    [RequireComponent(typeof(RectTransform))]
    public class SpatialButton : MonoBehaviour, IPointerEnterHandler, IPointerExitHandler, IPointerDownHandler, IPointerUpHandler, IPointerClickHandler
    {
        [Header("Button Text & State")]
        [SerializeField] private Text buttonLabel;
        [SerializeField] private Image buttonBackground;
        [SerializeField] private bool interactable = true;

        [Header("Colors (Minimal Dark Modern)")]
        [SerializeField] private Color normalColor = new Color(0.12f, 0.16f, 0.22f, 0.90f);
        [SerializeField] private Color hoverColor = new Color(0.18f, 0.28f, 0.40f, 0.95f);
        [SerializeField] private Color pressedColor = new Color(0.0f, 0.70f, 0.85f, 1.0f); // Cyan accent
        [SerializeField] private Color disabledColor = new Color(0.10f, 0.10f, 0.12f, 0.50f);

        [Header("Events")]
        public UnityEvent onClick = new UnityEvent();

        private bool isHovered = false;
        private bool isPressed = false;
        private Vector3 originalScale;

        public bool Interactable
        {
            get => interactable;
            set
            {
                interactable = value;
                UpdateVisualState();
            }
        }

        private void Awake()
        {
            originalScale = transform.localScale;
            if (buttonBackground == null)
            {
                buttonBackground = GetComponent<Image>();
            }
            if (buttonLabel == null)
            {
                buttonLabel = GetComponentInChildren<Text>();
            }
            UpdateVisualState();
        }

        public void SetLabel(string text)
        {
            if (buttonLabel != null)
            {
                buttonLabel.text = text;
            }
        }

        public void OnPointerEnter(PointerEventData eventData)
        {
            if (!interactable) return;
            isHovered = true;
            transform.localScale = originalScale * 1.05f;
            UpdateVisualState();
        }

        public void OnPointerExit(PointerEventData eventData)
        {
            if (!interactable) return;
            isHovered = false;
            isPressed = false;
            transform.localScale = originalScale;
            UpdateVisualState();
        }

        public void OnPointerDown(PointerEventData eventData)
        {
            if (!interactable) return;
            isPressed = true;
            transform.localScale = originalScale * 0.96f;
            UpdateVisualState();
        }

        public void OnPointerUp(PointerEventData eventData)
        {
            if (!interactable) return;
            isPressed = false;
            transform.localScale = isHovered ? originalScale * 1.05f : originalScale;
            UpdateVisualState();
        }

        public void OnPointerClick(PointerEventData eventData)
        {
            if (!interactable) return;
            TriggerClick();
        }

        public void TriggerClick()
        {
            if (!interactable) return;
            onClick?.Invoke();
        }

        private void UpdateVisualState()
        {
            if (buttonBackground == null) return;

            if (!interactable)
            {
                buttonBackground.color = disabledColor;
            }
            else if (isPressed)
            {
                buttonBackground.color = pressedColor;
            }
            else if (isHovered)
            {
                buttonBackground.color = hoverColor;
            }
            else
            {
                buttonBackground.color = normalColor;
            }
        }
    }
}
