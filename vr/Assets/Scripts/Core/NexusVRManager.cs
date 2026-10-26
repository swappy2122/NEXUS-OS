using System;
using UnityEngine;
using Nexus.VR.Areas;
using Nexus.VR.UI;
using Nexus.VR.Window;

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

        [Header("Window Management")]
        [SerializeField] private VRWindowManager windowManager;
        [SerializeField] private VRBridgeClient bridgeClient;

        [Header("System HUD")]
        [SerializeField] private SpatialHUD systemHud;

        [Header("Shell Settings")]
        [SerializeField] private bool autoRecenterOnStart = true;
        [SerializeField] private string shellVersion = "0.1.0-alpha";

        public ApplicationArea ApplicationArea => applicationArea;
        public WorkspaceArea WorkspaceArea => workspaceArea;
        public AIInteractionArea AIInteractionArea => aiInteractionArea;
        public VRWindowManager WindowManager => windowManager;
        public VRBridgeClient BridgeClient => bridgeClient;
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

            if (bridgeClient != null && aiInteractionArea != null)
            {
                bridgeClient.OnProtocolMessage += aiInteractionArea.HandleProtocolMessage;
            }

            // Connect window manager to workspace area for live window counts
            if (windowManager != null && workspaceArea != null)
            {
                workspaceArea.SetWindowManager(windowManager);

                windowManager.OnWindowCountChanged += (count) =>
                {
                    if (systemHud != null)
                    {
                        systemHud.SetStatus($"Windows: {count}");
                    }
                };
            }

            Debug.Log("[NEXUS VR] All spatial areas (Application, Workspace, AI Interaction), Window Manager, and HUD ready.");
            OnShellReady?.Invoke();
        }

        private void OnDestroy()
        {
            if (bridgeClient != null && aiInteractionArea != null)
            {
                bridgeClient.OnProtocolMessage -= aiInteractionArea.HandleProtocolMessage;
            }
            if (instance == this) instance = null;
        }

        public void FocusArea(NexusArea area)
        {
            if (area == null) return;
            area.FocusArea();
        }
    }
}
