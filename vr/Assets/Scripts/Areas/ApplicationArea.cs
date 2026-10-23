using System;
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.UI;
using Nexus.VR.UI;

namespace Nexus.VR.Areas
{
    /// <summary>
    /// Application Area for NEXUS VR.
    /// Manages the spatial application launcher, running application cards, and app lifecycle controls.
    /// </summary>
    public class ApplicationArea : NexusArea
    {
        [Header("UI Panels")]
        [SerializeField] private SpatialUIPanel appLauncherPanel;
        [SerializeField] private Transform runningAppsContainer;
        [SerializeField] private Text activeAppCountText;
        [SerializeField] private Text statusMessageText;

        [Header("Default Applications")]
        [SerializeField] private List<string> installedApps = new List<string>
        {
            "System Monitor",
            "Terminal (Bash)",
            "File Browser",
            "Text Editor",
            "Web Browser"
        };

        private readonly List<string> runningApps = new List<string> { "System Monitor", "Terminal (Bash)" };

        public IReadOnlyList<string> InstalledApps => installedApps;
        public IReadOnlyList<string> RunningApps => runningApps;

        public event Action<string> OnApplicationLaunched;
        public event Action<string> OnApplicationClosed;

        protected override void InitializeArea()
        {
            areaName = "Application Area";
            RefreshRunningAppsDisplay();
        }

        public void LaunchApp(string appName)
        {
            if (!runningApps.Contains(appName))
            {
                runningApps.Add(appName);
                SetStatus($"Launched {appName}");
                RefreshRunningAppsDisplay();
                OnApplicationLaunched?.Invoke(appName);
            }
            else
            {
                SetStatus($"{appName} is already running");
            }
        }

        public void CloseApp(string appName)
        {
            if (runningApps.Contains(appName))
            {
                runningApps.Remove(appName);
                SetStatus($"Closed {appName}");
                RefreshRunningAppsDisplay();
                OnApplicationClosed?.Invoke(appName);
            }
        }

        public void RefreshRunningAppsDisplay()
        {
            if (activeAppCountText != null)
            {
                activeAppCountText.text = $"Running Apps: {runningApps.Count}";
            }
        }

        private void SetStatus(string message)
        {
            if (statusMessageText != null)
            {
                statusMessageText.text = message;
            }
        }
    }
}
