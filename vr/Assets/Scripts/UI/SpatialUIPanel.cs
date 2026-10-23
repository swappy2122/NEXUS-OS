using System;
using UnityEngine;
using UnityEngine.UI;

namespace Nexus.VR.UI
{
    /// <summary>
    /// Base component for floating spatial UI panels in the NEXUS VR environment.
    /// Manages world-space positioning, facing orientation, focus states, and transitions.
    /// </summary>
    [RequireComponent(typeof(Canvas))]
    public class SpatialUIPanel : MonoBehaviour
    {
        [Header("Panel Configuration")]
        [SerializeField] private UIPanelType panelType = UIPanelType.Custom;
        [SerializeField] private string panelTitle = "Spatial Panel";
        [SerializeField] private PanelOrientationMode orientationMode = PanelOrientationMode.BillboardToUser;
        [SerializeField] private bool autoOpenOnStart = true;
        [SerializeField] private float targetDistance = 2.0f;

        [Header("Components")]
        [SerializeField] private Canvas canvas;
        [SerializeField] private CanvasGroup canvasGroup;
        [SerializeField] private Text titleText;
        [SerializeField] private RectTransform containerRect;

        [Header("Motion & Smoothing")]
        [SerializeField] private float rotationSmoothSpeed = 5.0f;
        [SerializeField] private float positionSmoothSpeed = 4.0f;
        [SerializeField] private bool lockPitch = true;

        private Transform targetCamera;
        private bool isOpen = false;
        private bool isFocused = false;
        private Vector3 targetScale = Vector3.one;

        public UIPanelType PanelType => panelType;
        public string PanelTitle => panelTitle;
        public bool IsOpen => isOpen;
        public bool IsFocused => isFocused;

        public event Action<SpatialUIPanel> OnPanelOpened;
        public event Action<SpatialUIPanel> OnPanelClosed;
        public event Action<SpatialUIPanel> OnPanelFocused;

        private void Awake()
        {
            if (canvas == null)
            {
                canvas = GetComponent<Canvas>();
            }

            if (canvasGroup == null)
            {
                canvasGroup = GetComponent<CanvasGroup>();
                if (canvasGroup == null)
                {
                    canvasGroup = gameObject.AddComponent<CanvasGroup>();
                }
            }

            if (containerRect == null)
            {
                containerRect = GetComponent<RectTransform>();
            }

            EnsureWorldSpaceCanvas();
        }

        private void Start()
        {
            FindMainCamera();
            UpdateTitleDisplay();

            if (autoOpenOnStart)
            {
                Open();
            }
            else
            {
                CloseImmediate();
            }
        }

        private void LateUpdate()
        {
            if (!isOpen) return;

            UpdateOrientation();
        }

        private void EnsureWorldSpaceCanvas()
        {
            if (canvas != null)
            {
                canvas.renderMode = RenderMode.WorldSpace;
            }
        }

        private void FindMainCamera()
        {
            if (Camera.main != null)
            {
                targetCamera = Camera.main.transform;
            }
        }

        private void UpdateOrientation()
        {
            if (targetCamera == null)
            {
                FindMainCamera();
                if (targetCamera == null) return;
            }

            switch (orientationMode)
            {
                case PanelOrientationMode.BillboardToUser:
                    Vector3 lookDir = transform.position - targetCamera.position;
                    if (lockPitch)
                    {
                        lookDir.y = 0.0f;
                    }
                    if (lookDir.sqrMagnitude > 0.001f)
                    {
                        Quaternion targetRot = Quaternion.LookRotation(lookDir.normalized, Vector3.up);
                        transform.rotation = Quaternion.Slerp(transform.rotation, targetRot, Time.deltaTime * rotationSmoothSpeed);
                    }
                    break;

                case PanelOrientationMode.LazyFollowHMD:
                    Vector3 forwardInFront = targetCamera.position + (targetCamera.forward * targetDistance);
                    if (lockPitch)
                    {
                        forwardInFront.y = transform.position.y;
                    }
                    transform.position = Vector3.Lerp(transform.position, forwardInFront, Time.deltaTime * positionSmoothSpeed);

                    Vector3 lazyLook = transform.position - targetCamera.position;
                    if (lockPitch) lazyLook.y = 0.0f;
                    if (lazyLook.sqrMagnitude > 0.001f)
                    {
                        Quaternion lazyRot = Quaternion.LookRotation(lazyLook.normalized, Vector3.up);
                        transform.rotation = Quaternion.Slerp(transform.rotation, lazyRot, Time.deltaTime * rotationSmoothSpeed);
                    }
                    break;

                case PanelOrientationMode.FixedWorld:
                default:
                    // Maintain current fixed world transform
                    break;
            }
        }

        public void SetTitle(string title)
        {
            panelTitle = title;
            UpdateTitleDisplay();
        }

        private void UpdateTitleDisplay()
        {
            if (titleText != null)
            {
                titleText.text = panelTitle;
            }
        }

        public virtual void Open()
        {
            isOpen = true;
            gameObject.SetActive(true);
            if (canvasGroup != null)
            {
                canvasGroup.alpha = 1.0f;
                canvasGroup.interactable = true;
                canvasGroup.blocksRaycasts = true;
            }
            transform.localScale = targetScale;
            OnPanelOpened?.Invoke(this);
        }

        public virtual void Close()
        {
            isOpen = false;
            if (canvasGroup != null)
            {
                canvasGroup.alpha = 0.0f;
                canvasGroup.interactable = false;
                canvasGroup.blocksRaycasts = false;
            }
            gameObject.SetActive(false);
            OnPanelClosed?.Invoke(this);
        }

        public void CloseImmediate()
        {
            isOpen = false;
            if (canvasGroup != null)
            {
                canvasGroup.alpha = 0.0f;
                canvasGroup.interactable = false;
                canvasGroup.blocksRaycasts = false;
            }
            gameObject.SetActive(false);
        }

        public virtual void Toggle()
        {
            if (isOpen)
            {
                Close();
            }
            else
            {
                Open();
            }
        }

        public void SetFocused(bool focused)
        {
            isFocused = focused;
            if (focused)
            {
                targetScale = Vector3.one * 1.02f;
                OnPanelFocused?.Invoke(this);
            }
            else
            {
                targetScale = Vector3.one;
            }
        }
    }
}
