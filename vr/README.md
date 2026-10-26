# NEXUS OS — Unity VR Shell

The initial OpenXR-compatible spatial virtual reality shell for **NEXUS OS**.

## Architecture & Layout

The NEXUS VR shell provides an ambient, distraction-free spatial computing environment arranged ergonomically around the user:

```
                         [ Spatial HUD (Time / OS Status / Workspace) ]
                                            (Y=2.2m, Z=2.5m)

    [ Application Area ]                  [ Workspace Area ]                 [ AI Interaction Area ]
 (Launcher & App Dock)                (Virtual Desktop & Tiling)          (Status Orb & Transcript)
   X=-1.8m, Z=2.2m, +32°                  X=0.0m, Z=2.6m, 0°                 X=+1.8m, Z=2.2m, -32°
            \                                      |                                     /
             \                                     |                                    /
              `------------------------- [ User / VR Rig ] ----------------------------'
                                        (CameraOffset @ 1.6m)
                                       [ Minimal Floor Grid ]
```

---

## Key Features

1. **OpenXR-Compatible Tracking**
   - Configured with `com.unity.xr.openxr`, `com.unity.xr.management`, and `com.unity.xr.interaction.toolkit`.
   - Uses modern `TrackingOriginModeFlags.Floor` / `Device` via `XRInputSubsystem`.
   - Automated recentering via `VRCameraController.Recenter()`.

2. **Desktop Simulator Fallback (Zero-Hardware Testing)**
   - When no VR HMD is detected, developers can test the environment directly:
     - **Mouse Right-Click + Drag**: 360° Free look.
     - **W / A / S / D**: Move horizontal / lateral.
     - **Q / E**: Lower / raise eye elevation.
     - **Spacebar / Left Mouse Click**: Click spatial buttons.
     - **R**: Recenter view.

3. **Simple NEXUS Home Environment**
   - Dark modern slate palette (`#0B0E13`) with subtle cyan accents (`#00B0D9`).
   - Ground plane with boundary circles (`EnvironmentFloor.cs`) providing personal space orientation without heavy textures or GPU overhead.

4. **Spatial UI Panels (`SpatialUIPanel.cs`)**
   - World-space interactive canvases.
   - Billboarding and facing options (`BillboardToUser`, `FixedWorld`, `LazyFollowHMD`).
   - Smooth focus highlighting and press transitions (`SpatialButton.cs`).

5. **Functional Spatial Areas**
   - **Application Area (`ApplicationArea.cs`)**:
     - Launcher cards for Terminal (Bash), System Monitor, File Browser, Web Browser.
     - Active application tracking and launch/close lifecycle actions.
   - **Workspace Area (`WorkspaceArea.cs`)**:
     - Virtual desktop switcher (Workspace 1, Workspace 2, Workspace 3).
     - Window layout toggling (`CurvedArc`, `FlatGrid`, `FreeFloating`).
     - Add / remove spatial window anchors.
   - **AI Interaction Area (`AIInteractionArea.cs`)**:
     - Minimal status orb (Idle, Listening, Thinking, Responding, Error).
     - Transcript conversation feed.
     - Action buttons: "Push to Talk (Voice Input)" and "Clear History".
     - Ready for future integration with the NEXUS core and voice input module.


6. **VR Window Manager**
   - Full spatial window lifecycle: create, close, move, resize, rotate, focus.
   - `WindowAgent` (Python) owns logical state; Unity renders via `VRWindowHandle`.
   - JSON-over-WebSocket IPC bridge (`VRBridge` ↔ `VRBridgeClient`, port 9100).
   - `WindowRegistry` maintains focus stack and z-ordering.
   - Spatial layout engines: `CurvedArc`, `FlatGrid`, `FreeFloating`.
   - User-initiated grab moves in VR reconcile back to Python state automatically.

---

## Directory Structure

```
vr/
├── Packages/
│   └── manifest.json                    # OpenXR, XR Management, Input System, UGUI
├── ProjectSettings/
│   ├── ProjectVersion.txt               # Unity 6000.6.6f1
│   ├── ProjectSettings.asset            # NEXUS VR Shell settings
│   └── XRGeneralSettingsPerBuildTarget.asset
├── Assets/
│   ├── Scenes/
│   │   ├── NexusHome.unity              # Pre-built complete VR scene
│   │   └── NexusHome.unity.meta
│   └── Scripts/
│       ├── Core/
│       │   ├── NexusVRManager.cs        # Master VR shell orchestrator
│       │   ├── VRCameraController.cs    # OpenXR camera & desktop simulator
│       │   └── EnvironmentFloor.cs      # Minimal procedural floor & boundary
│       ├── UI/
│       │   ├── SpatialUIPanel.cs        # World-space panel wrapper
│       │   ├── SpatialButton.cs         # Gaze & pointer interactive button
│       │   ├── SpatialHUD.cs            # Status bar (Clock, Workspace, Status)
│       │   └── UIPanelType.cs           # Types and facing modes
│       ├── Window/
│       │   ├── WindowData.cs            # Serializable structs (wire protocol)
│       │   ├── VRWindowHandle.cs        # Per-window MonoBehaviour (extends SpatialUIPanel)
│       │   ├── VRWindowManager.cs       # Central window coordinator
│       │   └── VRBridgeClient.cs        # WebSocket client to Python bridge
│       ├── Areas/
│       │   ├── NexusArea.cs             # Base spatial zone
│       │   ├── ApplicationArea.cs       # App launcher & running docks
│       │   ├── WorkspaceArea.cs         # Virtual desktop switcher & tiling
│       │   └── AIInteractionArea.cs     # AI status orb, feed & PTT trigger
│       ├── Interaction/
│       │   ├── SimpleGazePointer.cs     # Reticle crosshair pointer for camera
│       │   └── LaserPointer.cs          # Controller laser beam pointer
│       └── Editor/
│           └── NexusVRSceneBuilder.cs   # Automated scene construction script
├── window_types.py                      # VRWindow, Vec3, Quat, enums
├── window_protocol.py                   # WindowCommand, WindowEvent, payloads
├── window_registry.py                   # In-memory window state store
├── vr_bridge.py                         # WebSocket server (Python ↔ Unity)
├── __init__.py                          # Python bridge for NEXUS OS
└── README.md
```

---

## Opening in Unity & Rebuilding

### Open via Unity Hub
1. Open **Unity Hub**.
2. Click **Add** -> select the `vr/` folder in `NEXUS OS`.
3. Open with Unity 6 (6000.x).
4. Load `Assets/Scenes/NexusHome.unity` and press **Play**.

### Rebuilding Scene Programmatically
In Unity Editor:
- Click top menu: **NEXUS** -> **Setup VR Shell Scene**.

From terminal / CI:
```bash
/home/swappy/Unity/Hub/Editor/6000.6.6f1/Editor/Unity \
  -batchmode -nographics -projectPath "vr" \
  -executeMethod Nexus.VR.Editor.NexusVRSceneBuilder.BuildScene \
  -quit -logFile -
```
