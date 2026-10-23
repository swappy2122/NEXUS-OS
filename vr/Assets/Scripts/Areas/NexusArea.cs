using System;
using UnityEngine;

namespace Nexus.VR.Areas
{
    /// <summary>
    /// Base spatial zone in the NEXUS VR shell.
    /// Manages positioning, focus, and visibility of functional sub-areas.
    /// </summary>
    public abstract class NexusArea : MonoBehaviour
    {
        [Header("Area Metadata")]
        [SerializeField] protected string areaName = "Nexus Area";
        [SerializeField] protected bool isActiveArea = true;
        [SerializeField] protected float comfortRadius = 2.0f;

        public string AreaName => areaName;
        public bool IsActiveArea => isActiveArea;
        public float ComfortRadius => comfortRadius;

        public event Action<NexusArea, bool> OnAreaActiveChanged;

        protected virtual void Start()
        {
            InitializeArea();
        }

        protected abstract void InitializeArea();

        public virtual void SetAreaActive(bool active)
        {
            isActiveArea = active;
            gameObject.SetActive(active);
            OnAreaActiveChanged?.Invoke(this, active);
        }

        public virtual void FocusArea()
        {
            SetAreaActive(true);
        }
    }
}
