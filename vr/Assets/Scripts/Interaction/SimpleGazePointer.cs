using UnityEngine;
using UnityEngine.EventSystems;
using UnityEngine.UI;
using Nexus.VR.UI;

namespace Nexus.VR.Interaction
{
    /// <summary>
    /// Lightweight Gaze & Crosshair Pointer for NEXUS VR.
    /// Projects a subtle reticle forward from the center of the VR camera,
    /// triggering hover and click interactions on SpatialButtons and WorldSpace UI.
    /// </summary>
    public class SimpleGazePointer : MonoBehaviour
    {
        [Header("Gaze Settings")]
        [SerializeField] private float maxDistance = 5.0f;
        [SerializeField] private LayerMask raycastMask = ~0;
        [SerializeField] private GameObject reticlePrefab;

        [Header("Key Triggers")]
        [SerializeField] private KeyCode primaryClickKey = KeyCode.Space;

        private Camera gazeCamera;
        private SpatialButton currentHoveredButton;
        private Transform reticleInstance;

        private void Awake()
        {
            gazeCamera = GetComponent<Camera>();
            CreateReticle();
        }

        private void CreateReticle()
        {
            var reticleObj = GameObject.CreatePrimitive(PrimitiveType.Sphere);
            reticleObj.name = "[GazeReticle]";
            reticleObj.transform.localScale = Vector3.one * 0.015f;
            Destroy(reticleObj.GetComponent<Collider>());

            var renderer = reticleObj.GetComponent<MeshRenderer>();
            if (renderer != null && renderer.material != null)
            {
                renderer.material.color = new Color(0.0f, 0.8f, 1.0f, 0.85f);
            }

            reticleInstance = reticleObj.transform;
            reticleInstance.position = transform.position + (transform.forward * 2.0f);
        }

        private void Update()
        {
            PerformRaycast();
            HandleInput();
        }

        private void PerformRaycast()
        {
            Ray ray = new Ray(transform.position, transform.forward);
            if (Physics.Raycast(ray, out RaycastHit hit, maxDistance, raycastMask))
            {
                if (reticleInstance != null)
                {
                    reticleInstance.position = hit.point - (transform.forward * 0.02f);
                    reticleInstance.rotation = Quaternion.LookRotation(hit.normal);
                }

                var button = hit.collider.GetComponentInParent<SpatialButton>();
                if (button != currentHoveredButton)
                {
                    ClearHover();
                    if (button != null)
                    {
                        currentHoveredButton = button;
                        currentHoveredButton.OnPointerEnter(new PointerEventData(EventSystem.current));
                    }
                }
            }
            else
            {
                if (reticleInstance != null)
                {
                    reticleInstance.position = transform.position + (transform.forward * 2.0f);
                    reticleInstance.rotation = transform.rotation;
                }
                ClearHover();
            }
        }

        private void HandleInput()
        {
            // Triggers click on spacebar, left mouse button, or VR primary button
            if (Input.GetKeyDown(primaryClickKey) || Input.GetMouseButtonDown(0))
            {
                if (currentHoveredButton != null)
                {
                    currentHoveredButton.TriggerClick();
                }
            }
        }

        private void ClearHover()
        {
            if (currentHoveredButton != null)
            {
                currentHoveredButton.OnPointerExit(new PointerEventData(EventSystem.current));
                currentHoveredButton = null;
            }
        }

        private void OnDestroy()
        {
            if (reticleInstance != null)
            {
                Destroy(reticleInstance.gameObject);
            }
        }
    }
}
