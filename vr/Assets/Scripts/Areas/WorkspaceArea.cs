using System;
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.UI;
using Nexus.VR.UI;

namespace Nexus.VR.Areas
{
    /// <summary>
    /// Layout arrangement for windows in a spatial workspace.
    /// </summary>
    public enum WindowLayoutMode
    {
        CurvedArc,
        FlatGrid,
        FreeFloating
    }

    /// <summary>
    /// Workspace Area for NEXUS VR.
    /// Controls spatial virtual desktops, workspace switching, and spatial window organization.
    /// </summary>
    public class WorkspaceArea : NexusArea
    {
        [Header("UI References")]
        [SerializeField] private SpatialUIPanel workspacePanel;
        [SerializeField] private Text currentWorkspaceTitleText;
        [SerializeField] private Text windowCountText;
        [SerializeField] private Text layoutModeText;

        [Header("Workspace State")]
        [SerializeField] private int activeWorkspaceIndex = 0;
        [SerializeField] private WindowLayoutMode layoutMode = WindowLayoutMode.CurvedArc;

        private readonly List<string> workspaces = new List<string>
        {
            "Workspace 1 (General)",
            "Workspace 2 (Development)",
            "Workspace 3 (Monitoring)"
        };

        private int activeWindowCount = 3;

        public string ActiveWorkspaceName => workspaces[activeWorkspaceIndex];
        public WindowLayoutMode LayoutMode => layoutMode;
        public IReadOnlyList<string> Workspaces => workspaces;

        public event Action<int, string> OnWorkspaceChanged;
        public event Action<WindowLayoutMode> OnLayoutModeChanged;

        protected override void InitializeArea()
        {
            areaName = "Workspace Area";
            UpdateUI();
        }

        public void SwitchWorkspace(int index)
        {
            if (index >= 0 && index < workspaces.Count)
            {
                activeWorkspaceIndex = index;
                UpdateUI();
                OnWorkspaceChanged?.Invoke(activeWorkspaceIndex, workspaces[activeWorkspaceIndex]);
            }
        }

        public void NextWorkspace()
        {
            int nextIndex = (activeWorkspaceIndex + 1) % workspaces.Count;
            SwitchWorkspace(nextIndex);
        }

        public void PreviousWorkspace()
        {
            int prevIndex = (activeWorkspaceIndex - 1 + workspaces.Count) % workspaces.Count;
            SwitchWorkspace(prevIndex);
        }

        public void CreateWorkspace(string name = null)
        {
            string newName = string.IsNullOrEmpty(name) ? $"Workspace {workspaces.Count + 1}" : name;
            workspaces.Add(newName);
            SwitchWorkspace(workspaces.Count - 1);
        }

        public void CycleLayoutMode()
        {
            layoutMode = layoutMode switch
            {
                WindowLayoutMode.CurvedArc => WindowLayoutMode.FlatGrid,
                WindowLayoutMode.FlatGrid => WindowLayoutMode.FreeFloating,
                _ => WindowLayoutMode.CurvedArc
            };
            UpdateUI();
            OnLayoutModeChanged?.Invoke(layoutMode);
        }

        public void AddWindow()
        {
            activeWindowCount++;
            UpdateUI();
        }

        public void RemoveWindow()
        {
            if (activeWindowCount > 0)
            {
                activeWindowCount--;
                UpdateUI();
            }
        }

        private void UpdateUI()
        {
            if (currentWorkspaceTitleText != null)
            {
                currentWorkspaceTitleText.text = workspaces[activeWorkspaceIndex];
            }
            if (windowCountText != null)
            {
                windowCountText.text = $"Windows: {activeWindowCount}";
            }
            if (layoutModeText != null)
            {
                layoutModeText.text = $"Layout: {layoutMode}";
            }
        }
    }
}
