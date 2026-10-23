using System;
using UnityEngine;
using UnityEngine.UI;

namespace Nexus.VR.UI
{
    /// <summary>
    /// Minimal spatial HUD displaying core NEXUS OS system status, clock, and workspace.
    /// </summary>
    public class SpatialHUD : MonoBehaviour
    {
        [Header("UI References")]
        [SerializeField] private Text clockText;
        [SerializeField] private Text statusText;
        [SerializeField] private Text workspaceText;
        [SerializeField] private Text xrStatusText;

        [Header("Configuration")]
        [SerializeField] private string systemStatus = "ONLINE";
        [SerializeField] private string currentWorkspace = "Workspace 1 (Default)";

        private float timer = 0f;

        private void Start()
        {
            UpdateDisplays();
            if (xrStatusText != null)
            {
                xrStatusText.text = "OpenXR: Active";
            }
        }

        private void Update()
        {
            timer += Time.deltaTime;
            if (timer >= 1.0f)
            {
                timer = 0f;
                UpdateClock();
            }
        }

        private void UpdateClock()
        {
            if (clockText != null)
            {
                clockText.text = DateTime.Now.ToString("HH:mm:ss");
            }
        }

        public void SetWorkspace(string workspaceName)
        {
            currentWorkspace = workspaceName;
            if (workspaceText != null)
            {
                workspaceText.text = currentWorkspace;
            }
        }

        public void SetStatus(string status)
        {
            systemStatus = status;
            if (statusText != null)
            {
                statusText.text = systemStatus;
            }
        }

        public void UpdateDisplays()
        {
            UpdateClock();
            if (statusText != null) statusText.text = systemStatus;
            if (workspaceText != null) workspaceText.text = currentWorkspace;
        }
    }
}
