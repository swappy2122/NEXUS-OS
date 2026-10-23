#if UNITY_EDITOR
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.EventSystems;
using UnityEngine.UI;
using Nexus.VR.Core;
using Nexus.VR.UI;
using Nexus.VR.Areas;
using Nexus.VR.Interaction;

namespace Nexus.VR.Editor
{
    /// <summary>
    /// Automated builder to construct the initial NEXUS VR Shell scene.
    /// Run via menu: NEXUS > Setup VR Shell Scene.
    /// </summary>
    public static class NexusVRSceneBuilder
    {
        private const string ScenePath = "Assets/Scenes/NexusHome.unity";

        [MenuItem("NEXUS/Setup VR Shell Scene")]
        public static void BuildScene()
        {
            var scene = EditorSceneManager.NewScene(NewSceneSetup.EmptyScene, NewSceneMode.Single);

            // 1. Lighting & Environment
            var envRoot = new GameObject("[Environment]");
            var lightObj = new GameObject("Directional Light");
            lightObj.transform.SetParent(envRoot.transform);
            var light = lightObj.AddComponent<Light>();
            light.type = LightType.Directional;
            light.color = new Color(0.85f, 0.92f, 1.0f);
            light.intensity = 0.8f;
            lightObj.transform.rotation = Quaternion.Euler(45, -30, 0);

            // Floor Platform
            var floor = GameObject.CreatePrimitive(PrimitiveType.Cylinder);
            floor.name = "Floor";
            floor.transform.SetParent(envRoot.transform);
            floor.transform.position = new Vector3(0, -0.05f, 0);
            floor.transform.localScale = new Vector3(12f, 0.05f, 12f);
            floor.AddComponent<EnvironmentFloor>();

            // 2. VR Rig & Camera
            var rigObj = new GameObject("[NEXUS_VR_Rig]");
            rigObj.transform.position = Vector3.zero;

            var offsetObj = new GameObject("CameraOffset");
            offsetObj.transform.SetParent(rigObj.transform);
            offsetObj.transform.localPosition = new Vector3(0, 1.6f, 0); // Default eye level

            var camObj = new GameObject("Main Camera");
            camObj.transform.SetParent(offsetObj.transform);
            camObj.transform.localPosition = Vector3.zero;
            camObj.tag = "MainCamera";

            var camera = camObj.AddComponent<Camera>();
            camera.clearFlags = CameraClearFlags.SolidColor;
            camera.backgroundColor = new Color(0.04f, 0.05f, 0.07f, 1.0f); // Deep dark slate
            camera.nearClipPlane = 0.1f;
            camera.farClipPlane = 100f;

            camObj.AddComponent<AudioListener>();
            var camCtrl = camObj.AddComponent<VRCameraController>();
            camObj.AddComponent<SimpleGazePointer>();

            // 3. Event System
            var eventSysObj = new GameObject("[EventSystem]");
            eventSysObj.AddComponent<EventSystem>();
            eventSysObj.AddComponent<StandaloneInputModule>();

            // 4. Master Manager
            var managerObj = new GameObject("[NexusVRManager]");
            var vrManager = managerObj.AddComponent<NexusVRManager>();

            // 5. HUD Panel (Floating high forward)
            var hudPanelObj = CreateSpatialCanvas("Spatial_HUD", new Vector3(0, 2.2f, 2.5f), new Vector2(800, 120), 0.0015f);
            var hud = hudPanelObj.AddComponent<SpatialHUD>();

            var hudBg = CreatePanelBackground(hudPanelObj, new Color(0.08f, 0.11f, 0.15f, 0.85f));
            CreateText(hudPanelObj, "NEXUS OS — VR Shell", new Vector2(-220, 15), 24, TextAnchor.MiddleLeft, Color.cyan);
            var clockText = CreateText(hudPanelObj, "12:00:00", new Vector2(250, 15), 20, TextAnchor.MiddleRight, Color.white);
            var statusText = CreateText(hudPanelObj, "STATUS: ONLINE", new Vector2(-220, -20), 16, TextAnchor.MiddleLeft, new Color(0.3f, 0.9f, 0.4f));
            var wsText = CreateText(hudPanelObj, "Workspace 1 (Default)", new Vector2(250, -20), 16, TextAnchor.MiddleRight, new Color(0.7f, 0.8f, 0.9f));

            SetPrivateField(hud, "clockText", clockText);
            SetPrivateField(hud, "statusText", statusText);
            SetPrivateField(hud, "workspaceText", wsText);

            // 6. Application Area (Left Angle)
            var appAreaObj = new GameObject("[Area_Application]");
            appAreaObj.transform.position = new Vector3(-1.8f, 1.35f, 2.2f);
            appAreaObj.transform.rotation = Quaternion.Euler(0, 32, 0);
            var appArea = appAreaObj.AddComponent<ApplicationArea>();

            var appCanvas = CreateSpatialCanvas("App_Panel", Vector3.zero, new Vector2(600, 700), 0.0018f);
            appCanvas.transform.SetParent(appAreaObj.transform, false);
            var appPanel = appCanvas.AddComponent<SpatialUIPanel>();
            SetPrivateField(appPanel, "panelTitle", "Application Dock");

            CreatePanelBackground(appCanvas, new Color(0.07f, 0.10f, 0.14f, 0.92f));
            CreateText(appCanvas, "Applications", new Vector2(0, 310), 26, TextAnchor.MiddleCenter, Color.cyan);
            var appCountText = CreateText(appCanvas, "Running Apps: 2", new Vector2(0, 270), 18, TextAnchor.MiddleCenter, Color.gray);
            var appStatusText = CreateText(appCanvas, "Ready to launch", new Vector2(0, -310), 16, TextAnchor.MiddleCenter, new Color(0.6f, 0.7f, 0.8f));

            CreateSpatialButton(appCanvas, "Terminal (Bash)", new Vector2(0, 180), new Vector2(480, 50), () => appArea.LaunchApp("Terminal"));
            CreateSpatialButton(appCanvas, "System Monitor", new Vector2(0, 110), new Vector2(480, 50), () => appArea.LaunchApp("System Monitor"));
            CreateSpatialButton(appCanvas, "File Browser", new Vector2(0, 40), new Vector2(480, 50), () => appArea.LaunchApp("File Browser"));
            CreateSpatialButton(appCanvas, "Web Browser", new Vector2(0, -30), new Vector2(480, 50), () => appArea.LaunchApp("Web Browser"));
            CreateSpatialButton(appCanvas, "Close Active App", new Vector2(0, -120), new Vector2(480, 45), () => appArea.CloseApp("Terminal"));

            SetPrivateField(appArea, "appLauncherPanel", appPanel);
            SetPrivateField(appArea, "activeAppCountText", appCountText);
            SetPrivateField(appArea, "statusMessageText", appStatusText);

            // 7. Workspace Area (Center Straight)
            var wsAreaObj = new GameObject("[Area_Workspace]");
            wsAreaObj.transform.position = new Vector3(0f, 1.35f, 2.6f);
            var wsArea = wsAreaObj.AddComponent<WorkspaceArea>();

            var wsCanvas = CreateSpatialCanvas("Workspace_Panel", Vector3.zero, new Vector2(650, 700), 0.0018f);
            wsCanvas.transform.SetParent(wsAreaObj.transform, false);
            var wsPanel = wsCanvas.AddComponent<SpatialUIPanel>();
            SetPrivateField(wsPanel, "panelTitle", "Workspace Manager");

            CreatePanelBackground(wsCanvas, new Color(0.07f, 0.10f, 0.14f, 0.92f));
            CreateText(wsCanvas, "Workspaces", new Vector2(0, 310), 26, TextAnchor.MiddleCenter, Color.cyan);
            var wsTitleText = CreateText(wsCanvas, "Workspace 1 (General)", new Vector2(0, 260), 20, TextAnchor.MiddleCenter, Color.white);
            var wsWinCountText = CreateText(wsCanvas, "Windows: 3", new Vector2(-150, 200), 18, TextAnchor.MiddleLeft, Color.gray);
            var wsLayoutText = CreateText(wsCanvas, "Layout: CurvedArc", new Vector2(150, 200), 18, TextAnchor.MiddleRight, Color.gray);

            CreateSpatialButton(wsCanvas, "< Previous Workspace", new Vector2(-150, 100), new Vector2(250, 50), () => wsArea.PreviousWorkspace());
            CreateSpatialButton(wsCanvas, "Next Workspace >", new Vector2(150, 100), new Vector2(250, 50), () => wsArea.NextWorkspace());
            CreateSpatialButton(wsCanvas, "+ New Workspace", new Vector2(0, 20), new Vector2(400, 50), () => wsArea.CreateWorkspace());
            CreateSpatialButton(wsCanvas, "Cycle Layout Mode", new Vector2(0, -60), new Vector2(400, 50), () => wsArea.CycleLayoutMode());
            CreateSpatialButton(wsCanvas, "+ Add Spatial Window", new Vector2(0, -140), new Vector2(400, 50), () => wsArea.AddWindow());

            SetPrivateField(wsArea, "workspacePanel", wsPanel);
            SetPrivateField(wsArea, "currentWorkspaceTitleText", wsTitleText);
            SetPrivateField(wsArea, "windowCountText", wsWinCountText);
            SetPrivateField(wsArea, "layoutModeText", wsLayoutText);

            // 8. AI Interaction Area (Right Angle)
            var aiAreaObj = new GameObject("[Area_AIInteraction]");
            aiAreaObj.transform.position = new Vector3(1.8f, 1.35f, 2.2f);
            aiAreaObj.transform.rotation = Quaternion.Euler(0, -32, 0);
            var aiArea = aiAreaObj.AddComponent<AIInteractionArea>();

            var aiCanvas = CreateSpatialCanvas("AI_Panel", Vector3.zero, new Vector2(600, 700), 0.0018f);
            aiCanvas.transform.SetParent(aiAreaObj.transform, false);
            var aiPanel = aiCanvas.AddComponent<SpatialUIPanel>();
            SetPrivateField(aiPanel, "panelTitle", "AI Interaction");

            CreatePanelBackground(aiCanvas, new Color(0.07f, 0.10f, 0.14f, 0.92f));
            CreateText(aiCanvas, "AI Assistant", new Vector2(0, 310), 26, TextAnchor.MiddleCenter, Color.cyan);

            // Orb status visual
            var orbImg = CreateOrbImage(aiCanvas, new Vector2(0, 250), 40);
            var aiStatusText = CreateText(aiCanvas, "AI: IDLE", new Vector2(0, 210), 18, TextAnchor.MiddleCenter, Color.white);

            // Transcript text
            var transcriptText = CreateText(aiCanvas, "[System] Ready.\nGaze or point to interact.", new Vector2(0, 30), 16, TextAnchor.UpperLeft, new Color(0.8f, 0.85f, 0.9f));
            transcriptText.rectTransform.sizeDelta = new Vector2(520, 240);

            CreateSpatialButton(aiCanvas, "Push To Talk (Voice Input)", new Vector2(0, -150), new Vector2(480, 55), () => aiArea.TriggerVoiceInput());
            CreateSpatialButton(aiCanvas, "Clear History", new Vector2(0, -230), new Vector2(480, 45), () => aiArea.ClearHistory());

            SetPrivateField(aiArea, "aiPanel", aiPanel);
            SetPrivateField(aiArea, "statusBadgeText", aiStatusText);
            SetPrivateField(aiArea, "statusOrbImage", orbImg);
            SetPrivateField(aiArea, "transcriptLogText", transcriptText);

            // Wire up VRManager
            SetPrivateField(vrManager, "cameraController", camCtrl);
            SetPrivateField(vrManager, "applicationArea", appArea);
            SetPrivateField(vrManager, "workspaceArea", wsArea);
            SetPrivateField(vrManager, "aiInteractionArea", aiArea);
            SetPrivateField(vrManager, "systemHud", hud);

            // Save scene
            System.IO.Directory.CreateDirectory("Assets/Scenes");
            EditorSceneManager.SaveScene(scene, ScenePath);
            Debug.Log($"[NEXUS VR] Scene successfully built and saved to {ScenePath}");
        }

        private static GameObject CreateSpatialCanvas(string name, Vector3 position, Vector2 size, float scale)
        {
            var obj = new GameObject(name);
            obj.transform.position = position;

            var canvas = obj.AddComponent<Canvas>();
            canvas.renderMode = RenderMode.WorldSpace;

            var scaler = obj.AddComponent<CanvasScaler>();
            scaler.dynamicPixelsPerUnit = 2;

            obj.AddComponent<GraphicRaycaster>();

            var rect = obj.GetComponent<RectTransform>();
            rect.sizeDelta = size;
            rect.localScale = Vector3.one * scale;

            var collider = obj.AddComponent<BoxCollider>();
            collider.size = new Vector3(size.x, size.y, 2.0f);

            return obj;
        }

        private static Image CreatePanelBackground(GameObject parent, Color color)
        {
            var bgObj = new GameObject("Background");
            bgObj.transform.SetParent(parent.transform, false);

            var img = bgObj.AddComponent<Image>();
            img.color = color;

            var rect = bgObj.GetComponent<RectTransform>();
            rect.anchorMin = Vector2.zero;
            rect.anchorMax = Vector2.one;
            rect.sizeDelta = Vector2.zero;

            return img;
        }

        private static Text CreateText(GameObject parent, string content, Vector2 anchoredPosition, int fontSize, TextAnchor alignment, Color color)
        {
            var textObj = new GameObject("Text");
            textObj.transform.SetParent(parent.transform, false);

            var text = textObj.AddComponent<Text>();
            text.text = content;
            text.fontSize = fontSize;
            text.alignment = alignment;
            text.color = color;
            text.font = Resources.GetBuiltinResource<Font>("LegacyRuntime.ttf");

            var rect = textObj.GetComponent<RectTransform>();
            rect.anchoredPosition = anchoredPosition;
            rect.sizeDelta = new Vector2(400, 40);

            return text;
        }

        private static Image CreateOrbImage(GameObject parent, Vector2 anchoredPosition, float size)
        {
            var orbObj = new GameObject("StatusOrb");
            orbObj.transform.SetParent(parent.transform, false);

            var img = orbObj.AddComponent<Image>();
            img.color = new Color(0.0f, 0.75f, 0.9f, 1.0f);

            var rect = orbObj.GetComponent<RectTransform>();
            rect.anchoredPosition = anchoredPosition;
            rect.sizeDelta = new Vector2(size, size);

            return img;
        }

        private static SpatialButton CreateSpatialButton(GameObject parent, string label, Vector2 anchoredPosition, Vector2 size, System.Action onClickAction)
        {
            var btnObj = new GameObject($"Btn_{label.Replace(" ", "_")}");
            btnObj.transform.SetParent(parent.transform, false);

            var rect = btnObj.AddComponent<RectTransform>();
            rect.anchoredPosition = anchoredPosition;
            rect.sizeDelta = size;

            var img = btnObj.AddComponent<Image>();
            img.color = new Color(0.12f, 0.16f, 0.22f, 0.90f);

            var collider = btnObj.AddComponent<BoxCollider>();
            collider.size = new Vector3(size.x, size.y, 5.0f);

            var textObj = new GameObject("Label");
            textObj.transform.SetParent(btnObj.transform, false);

            var text = textObj.AddComponent<Text>();
            text.text = label;
            text.fontSize = 18;
            text.alignment = TextAnchor.MiddleCenter;
            text.color = Color.white;
            text.font = Resources.GetBuiltinResource<Font>("LegacyRuntime.ttf");

            var textRect = textObj.GetComponent<RectTransform>();
            textRect.anchorMin = Vector2.zero;
            textRect.anchorMax = Vector2.one;
            textRect.sizeDelta = Vector2.zero;

            var button = btnObj.AddComponent<SpatialButton>();
            if (onClickAction != null)
            {
                button.onClick.AddListener(() => onClickAction());
            }

            return button;
        }

        private static void SetPrivateField(object target, string fieldName, object value)
        {
            var field = target.GetType().GetField(fieldName, System.Reflection.BindingFlags.NonPublic | System.Reflection.BindingFlags.Instance);
            if (field != null)
            {
                field.SetValue(target, value);
            }
        }
    }
}
#endif
