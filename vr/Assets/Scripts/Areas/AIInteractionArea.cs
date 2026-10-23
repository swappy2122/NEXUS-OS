using System;
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.UI;
using Nexus.VR.UI;

namespace Nexus.VR.Areas
{
    /// <summary>
    /// AI state indicator mode for the spatial interaction area.
    /// </summary>
    public enum AIStatusState
    {
        Idle,
        Listening,
        Thinking,
        Responding,
        Error
    }

    /// <summary>
    /// AI Interaction Area for NEXUS VR.
    /// Dedicated spatial console providing status indicators, transcript display, and input triggers.
    /// Note: Does not implement AI communication logic yet; provides functional VR shell hooks.
    /// </summary>
    public class AIInteractionArea : NexusArea
    {
        [Header("UI Panels")]
        [SerializeField] private SpatialUIPanel aiPanel;
        [SerializeField] private Text statusBadgeText;
        [SerializeField] private Image statusOrbImage;
        [SerializeField] private Text transcriptLogText;
        [SerializeField] private Text currentPromptText;

        [Header("Status Visuals (Minimal Palettes)")]
        [SerializeField] private Color idleColor = new Color(0.0f, 0.70f, 0.85f, 1.0f);      // Cyan
        [SerializeField] private Color listeningColor = new Color(0.15f, 0.85f, 0.40f, 1.0f); // Green
        [SerializeField] private Color thinkingColor = new Color(1.0f, 0.75f, 0.10f, 1.0f);  // Amber
        [SerializeField] private Color errorColor = new Color(0.95f, 0.25f, 0.25f, 1.0f);     // Red

        private AIStatusState currentState = AIStatusState.Idle;
        private readonly List<string> transcriptHistory = new List<string>
        {
            "[System] NEXUS VR Shell initialized.",
            "[AI] Ready. Gaze or point to interact."
        };

        public AIStatusState CurrentState => currentState;
        public IReadOnlyList<string> TranscriptHistory => transcriptHistory;

        public event Action<AIStatusState> OnStatusStateChanged;
        public event Action OnVoiceTriggered;

        protected override void InitializeArea()
        {
            areaName = "AI Interaction Area";
            SetStatusState(AIStatusState.Idle);
            RefreshTranscript();
        }

        public void SetStatusState(AIStatusState newState)
        {
            currentState = newState;
            if (statusBadgeText != null)
            {
                statusBadgeText.text = $"AI: {currentState.ToString().ToUpper()}";
            }

            if (statusOrbImage != null)
            {
                statusOrbImage.color = currentState switch
                {
                    AIStatusState.Listening => listeningColor,
                    AIStatusState.Thinking => thinkingColor,
                    AIStatusState.Error => errorColor,
                    _ => idleColor
                };
            }

            OnStatusStateChanged?.Invoke(currentState);
        }

        public void TriggerVoiceInput()
        {
            // Toggle listening state in the shell UI
            if (currentState == AIStatusState.Listening)
            {
                SetStatusState(AIStatusState.Idle);
                AddTranscriptEntry("[Voice] Listening stopped.");
            }
            else
            {
                SetStatusState(AIStatusState.Listening);
                AddTranscriptEntry("[Voice] Listening for input...");
                OnVoiceTriggered?.Invoke();
            }
        }

        public void AddTranscriptEntry(string message)
        {
            transcriptHistory.Add(message);
            if (transcriptHistory.Count > 10)
            {
                transcriptHistory.RemoveAt(0);
            }
            RefreshTranscript();
        }

        public void ClearHistory()
        {
            transcriptHistory.Clear();
            AddTranscriptEntry("[System] Transcript history cleared.");
            SetStatusState(AIStatusState.Idle);
        }

        private void RefreshTranscript()
        {
            if (transcriptLogText != null)
            {
                transcriptLogText.text = string.Join("\n", transcriptHistory);
            }
        }
    }
}
