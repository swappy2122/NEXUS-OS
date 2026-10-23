using UnityEngine;

namespace Nexus.VR.Core
{
    /// <summary>
    /// Minimal procedural floor and boundary ring for the NEXUS VR home environment.
    /// Provides spatial grounding and personal space boundaries with zero heavy assets.
    /// </summary>
    public class EnvironmentFloor : MonoBehaviour
    {
        [Header("Floor Dimensions")]
        [SerializeField] private float platformRadius = 6.0f;
        [SerializeField] private Color floorColor = new Color(0.06f, 0.08f, 0.11f, 1.0f); // Deep slate navy
        [SerializeField] private Color ringAccentColor = new Color(0.0f, 0.65f, 0.85f, 0.6f); // Soft cyan ring

        private void Awake()
        {
            ApplyMinimalVisuals();
        }

        private void ApplyMinimalVisuals()
        {
            var renderer = GetComponent<MeshRenderer>();
            if (renderer != null && renderer.material != null)
            {
                renderer.material.color = floorColor;
            }
        }

        private void OnDrawGizmos()
        {
            Gizmos.color = ringAccentColor;
            Gizmos.DrawWireSphere(transform.position, platformRadius);
            Gizmos.DrawWireSphere(transform.position, 1.0f); // Personal space radius
        }
    }
}
