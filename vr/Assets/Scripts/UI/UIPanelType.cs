namespace Nexus.VR.UI
{
    /// <summary>
    /// Identifies the functional domain of a spatial UI panel in NEXUS VR.
    /// </summary>
    public enum UIPanelType
    {
        SystemHUD,
        Application,
        Workspace,
        AIInteraction,
        Settings,
        Window,
        Custom
    }

    /// <summary>
    /// Orientation behaviour for spatial panels.
    /// </summary>
    public enum PanelOrientationMode
    {
        FixedWorld,
        BillboardToUser,
        LazyFollowHMD,
        CurvedCylinder
    }
}
