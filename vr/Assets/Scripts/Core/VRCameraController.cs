using System;
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.XR;

namespace Nexus.VR.Core
{
    /// <summary>
    /// OpenXR-compatible VR camera controller.
    /// Manages HMD head tracking, recentering, eye-level offsets,
    /// and provides desktop simulator controls (WASD + Mouse Look) when no HMD is connected.
    /// </summary>
    [RequireComponent(typeof(Camera))]
    public class VRCameraController : MonoBehaviour
    {
        [Header("VR Tracking")]
        [SerializeField] private TrackingOriginModeFlags trackingOriginMode = TrackingOriginModeFlags.Floor;
        [SerializeField] private float defaultEyeHeight = 1.65f;
        [SerializeField] private Transform cameraOffset;

        [Header("Desktop Simulator Fallback")]
        [SerializeField] private bool enableDesktopFallback = true;
        [SerializeField] private float moveSpeed = 3.0f;
        [SerializeField] private float mouseSensitivity = 2.0f;

        private Camera targetCamera;
        private bool isHmdActive = false;
        private float rotationX = 0f;
        private float rotationY = 0f;
        private Vector3 initialPosition;
        private Quaternion initialRotation;

        public bool IsHmdActive => isHmdActive;

        public event Action OnRecentered;

        private void Awake()
        {
            targetCamera = GetComponent<Camera>();
            initialPosition = transform.localPosition;
            initialRotation = transform.localRotation;
        }

        private void Start()
        {
            ConfigureXRTracking();
            CheckHmdPresence();
        }

        private void Update()
        {
            CheckHmdPresence();

            // When running on desktop without active HMD movement, provide simulator controls
            if (enableDesktopFallback && !isHmdActive)
            {
                HandleDesktopMovement();
                HandleDesktopLook();
            }

            if (Input.GetKeyDown(KeyCode.R))
            {
                Recenter();
            }
        }

        private void ConfigureXRTracking()
        {
            var inputSubsystems = new List<XRInputSubsystem>();
            SubsystemManager.GetInstances(inputSubsystems);

            for (int i = 0; i < inputSubsystems.Count; i++)
            {
                if (inputSubsystems[i].running)
                {
                    inputSubsystems[i].TrySetTrackingOriginMode(trackingOriginMode);
                }
            }

            if (cameraOffset != null)
            {
                if (trackingOriginMode == TrackingOriginModeFlags.Device)
                {
                    cameraOffset.localPosition = new Vector3(0, defaultEyeHeight, 0);
                }
            }
        }

        private void CheckHmdPresence()
        {
            var xrDisplays = new List<XRDisplaySubsystem>();
            SubsystemManager.GetInstances(xrDisplays);
            bool displayRunning = false;

            for (int i = 0; i < xrDisplays.Count; i++)
            {
                if (xrDisplays[i].running)
                {
                    displayRunning = true;
                    break;
                }
            }

            isHmdActive = displayRunning || XRSettings.isDeviceActive;
        }

        private void HandleDesktopLook()
        {
            // Right-click drag to rotate camera
            if (Input.GetMouseButton(1))
            {
                float mouseX = Input.GetAxis("Mouse X") * mouseSensitivity;
                float mouseY = Input.GetAxis("Mouse Y") * mouseSensitivity;

                rotationY += mouseX;
                rotationX -= mouseY;
                rotationX = Mathf.Clamp(rotationX, -85f, 85f);

                transform.localRotation = Quaternion.Euler(rotationX, rotationY, 0f);
            }
        }

        private void HandleDesktopMovement()
        {
            float horizontal = Input.GetAxis("Horizontal"); // A/D
            float vertical = Input.GetAxis("Vertical");     // W/S
            float elevation = 0f;

            if (Input.GetKey(KeyCode.E)) elevation += 1f;
            if (Input.GetKey(KeyCode.Q)) elevation -= 1f;

            Vector3 moveDirection = (transform.forward * vertical + transform.right * horizontal + Vector3.up * elevation).normalized;
            transform.position += moveDirection * (moveSpeed * Time.deltaTime);
        }

        public void Recenter()
        {
            var inputSubsystems = new List<XRInputSubsystem>();
            SubsystemManager.GetInstances(inputSubsystems);
            for (int i = 0; i < inputSubsystems.Count; i++)
            {
                if (inputSubsystems[i].running)
                {
                    inputSubsystems[i].TryRecenter();
                }
            }

            if (!isHmdActive)
            {
                transform.localPosition = initialPosition;
                transform.localRotation = initialRotation;
                rotationX = 0f;
                rotationY = 0f;
            }

            OnRecentered?.Invoke();
            Debug.Log("[NEXUS VR] Camera recentered.");
        }
    }
}
