using System;
using System.Collections.Generic;
using System.Text;
using UnityEngine;
using UnityEngine.UI;
using Nexus.VR.UI;
using Nexus.VR.Window;

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
        private readonly Dictionary<string, StringBuilder> responseBuffers = new Dictionary<string, StringBuilder>();
        private readonly HashSet<string> completedResponses = new HashSet<string>();

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

        /// <summary>
        /// Consume one validated AI protocol envelope on Unity's main thread.
        /// Chunks are isolated by response_id and never replace another response.
        /// </summary>
        public void HandleProtocolMessage(string json)
        {
            NexusEnvelope envelope = NexusMessageParser.ParseEnvelope(json);
            if (envelope == null || envelope.topic != NexusProtocol.TopicAI) return;

            switch (envelope.message_type)
            {
                case NexusProtocol.TypeAIState:
                    var state = JsonUtility.FromJson<NexusAIStateMessage>(json);
                    SetStatusState(ParseStatus(state.payload.state));
                    break;
                case NexusProtocol.TypeAIToken:
                    var token = JsonUtility.FromJson<NexusAITokenMessage>(json);
                    if (string.IsNullOrEmpty(token.payload.response_id)) return;
                    if (completedResponses.Contains(token.payload.response_id)) return;
                    if (!responseBuffers.TryGetValue(token.payload.response_id, out var buffer))
                    {
                        buffer = new StringBuilder();
                        responseBuffers[token.payload.response_id] = buffer;
                    }
                    buffer.Append(token.payload.token ?? "");
                    SetStatusState(AIStatusState.Responding);
                    if (token.payload.is_final)
                    {
                        AddTranscriptEntry("[AI] " + buffer.ToString());
                        responseBuffers.Remove(token.payload.response_id);
                        completedResponses.Add(token.payload.response_id);
                        SetStatusState(AIStatusState.Idle);
                    }
                    break;
                case NexusProtocol.TypeAIError:
                    var error = JsonUtility.FromJson<NexusAIErrorMessage>(json);
                    if (string.IsNullOrEmpty(error.payload.response_id)
                        || completedResponses.Contains(error.payload.response_id)) return;
                    responseBuffers.Remove(error.payload.response_id);
                    completedResponses.Add(error.payload.response_id);
                    AddTranscriptEntry("[AI Error] " + (error.payload.error ?? "Response failed"));
                    SetStatusState(AIStatusState.Error);
                    break;
            }
        }

        private static AIStatusState ParseStatus(string state)
        {
            switch (state)
            {
                case "thinking": return AIStatusState.Thinking;
                case "responding": return AIStatusState.Responding;
                case "listening": return AIStatusState.Listening;
                case "error": return AIStatusState.Error;
                default: return AIStatusState.Idle;
            }
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
