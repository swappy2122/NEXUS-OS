using UnityEngine;
using UnityEngine.EventSystems;
using Nexus.VR.UI;

namespace Nexus.VR.Interaction
{
    /// <summary>
    /// Minimal Laser Pointer component for VR hand controllers.
    /// Projects a line renderer beam and triggers spatial button events.
    /// </summary>
    [RequireComponent(typeof(LineRenderer))]
    public class LaserPointer : MonoBehaviour
    {
        [Header("Laser Settings")]
        [SerializeField] private float maxDistance = 6.0f;
        [SerializeField] private LayerMask raycastMask = ~0;
        [SerializeField] private Color beamColor = new Color(0.0f, 0.7f, 0.9f, 0.5f);

        private LineRenderer lineRenderer;
        private SpatialButton hoveredButton;

        private void Awake()
        {
            lineRenderer = GetComponent<LineRenderer>();
            ConfigureLineRenderer();
        }

        private void ConfigureLineRenderer()
        {
            lineRenderer.positionCount = 2;
            lineRenderer.startWidth = 0.005f;
            lineRenderer.endWidth = 0.002f;
            lineRenderer.startColor = beamColor;
            lineRenderer.endColor = beamColor;
            lineRenderer.material = new Material(Shader.Find("Sprites/Default"));
        }

        private void Update()
        {
            lineRenderer.SetPosition(0, transform.position);

            Ray ray = new Ray(transform.position, transform.forward);
            if (Physics.Raycast(ray, out RaycastHit hit, maxDistance, raycastMask))
            {
                lineRenderer.SetPosition(1, hit.point);

                var button = hit.collider.GetComponentInParent<SpatialButton>();
                if (button != hoveredButton)
                {
                    ClearHover();
                    if (button != null)
                    {
                        hoveredButton = button;
                        hoveredButton.OnPointerEnter(new PointerEventData(EventSystem.current));
                    }
                }
            }
            else
            {
                lineRenderer.SetPosition(1, transform.position + (transform.forward * maxDistance));
                ClearHover();
            }

            if (Input.GetMouseButtonDown(0))
            {
                if (hoveredButton != null)
                {
                    hoveredButton.TriggerClick();
                }
            }
        }

        private void ClearHover()
        {
            if (hoveredButton != null)
            {
                hoveredButton.OnPointerExit(new PointerEventData(EventSystem.current));
                hoveredButton = null;
            }
        }
    }
}
