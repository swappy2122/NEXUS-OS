using System;
using UnityEngine;
using Nexus.VR.Areas;
using Nexus.VR.UI;
using Nexus.VR.WindowManager;

namespace Nexus.VR.Core
{
    /// <summary>
    /// Master coordinator for the NEXUS VR Shell.
    /// Manages startup lifecycle, spatial areas, user presence, and shell state.
    /// </summary>
    public class NexusVRManager : MonoBehaviour
    {
        private static NexusVRManager instance;
        public static NexusVRManager Instance => instance;

        [Header("VR Rig & Camera")]
        [SerializeField] private VRCameraController cameraController;
        [SerializeField] private Transform userHead;

        [Header("Spatial Areas")]
        [SerializeField] private ApplicationArea applicationArea;
        [SerializeField] private WorkspaceArea workspaceArea;
        [SerializeField] private AIInteractionArea aiInteractionArea;

        [Header("Window Manager")]
        [SerializeField] private VRWindowManager windowManager;

        [Header("System HUD")]
        [SerializeField] private SpatialHUD systemHud;

        [Header("Shell Settings")]
        [SerializeField] private bool autoRecenterOnStart = true;
        [SerializeField] private string shellVersion = "0.1.0-alpha";

        public ApplicationArea ApplicationArea => applicationArea;
        public WorkspaceArea WorkspaceArea => workspaceArea;
        public AIInteractionArea AIInteractionArea => aiInteractionArea;
        public VRWindowManager WindowManager => windowManager;
        public SpatialHUD SystemHud => systemHud;
        public VRCameraController CameraController => cameraController;

        public event Action OnShellReady;

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
            InitializeShell();
        }

        private void InitializeShell()
        {
            Debug.Log($"[NEXUS VR] Initializing NEXUS VR Shell (v{shellVersion}) with OpenXR compatibility...");

            if (userHead == null && Camera.main != null)
            {
                userHead = Camera.main.transform;
            }

            if (autoRecenterOnStart && cameraController != null)
            {
                cameraController.Recenter();
            }

            // Sync workspace area with HUD
            if (workspaceArea != null && systemHud != null)
            {
                workspaceArea.OnWorkspaceChanged += (idx, name) =>
                {
                    systemHud.SetWorkspace(name);
                };
                systemHud.SetWorkspace(workspaceArea.ActiveWorkspaceName);
            }

            // Sync AI state with HUD
            if (aiInteractionArea != null && systemHud != null)
            {
                aiInteractionArea.OnStatusStateChanged += (state) =>
                {
                    systemHud.SetStatus($"AI {state.ToString().ToUpper()}");
                };
            }

            // Wire window manager events to workspace area
            if (windowManager != null)
            {
                windowManager.OnWindowCreated += (windowId) =>
                {
                    if (workspaceArea != null) workspaceArea.AddWindow();
                    Debug.Log($"[NEXUS VR] Window created: {windowId}");
                };

                windowManager.OnWindowClosed += (windowId) =>
                {
                    if (workspaceArea != null) workspaceArea.RemoveWindow();
                    Debug.Log($"[NEXUS VR] Window closed: {windowId}");
                };

                windowManager.OnWindowFocused += (windowId) =>
                {
                    if (systemHud != null)
                    {
                        var win = windowManager.GetWindow(windowId);
                        if (win != null) systemHud.SetStatus($"Window: {win.Title}");
                    }
                };

                Debug.Log($"[NEXUS VR] VRWindowManager initialized ({windowManager.WindowCount} windows)");
            }

            Debug.Log("[NEXUS VR] All spatial areas (Application, Workspace, AI Interaction) and HUD ready.");
            OnShellReady?.Invoke();
        }

        public void FocusArea(NexusArea area)
        {
            if (area == null) return;
            area.FocusArea();
        }
    }
}
