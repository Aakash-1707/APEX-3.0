"""
APEX LLM Service — Claude Strategy Intelligence
=================================================
Anthropic Claude integration for F1 strategy narration,
what-if analysis, and conversational strategy queries.

Supports Anthropic Claude and Google Gemini.

Set `ANTHROPIC_API_KEY` for Claude, or `GEMINI_API_KEY` for Gemini.
"""

import os
import json
from typing import Optional

_ANTHROPIC_AVAILABLE = False
try:
    import anthropic
    _ANTHROPIC_AVAILABLE = True
except ImportError:
    pass

_GEMINI_AVAILABLE = False
try:
    import google.generativeai as genai
    _GEMINI_AVAILABLE = True
except ImportError:
    pass

MODEL = os.environ.get("APEX_CLAUDE_MODEL", "claude-sonnet-4-20250514")
MAX_TOKENS = 1024

SYSTEM_PROMPT = """You are APEX, an elite Formula 1 race strategist AI. You analyze tyre degradation data, \
Monte Carlo simulation results, and historical strategy patterns to provide clear, actionable race strategy \
recommendations.

Your communication style:
- Concise and direct, like a pit wall engineer talking to a driver
- Use specific numbers: lap times, gaps, probabilities
- When recommending a strategy, explain WHY with data
- Flag risks and uncertainties explicitly
- Reference historical precedent when relevant

When analyzing scenarios:
- Consider tyre degradation curves and compound characteristics
- Factor in safety car and VSC probabilities for the circuit
- Account for track position and undercut/overcut dynamics
- Note weather conditions if relevant

Format your responses with clear structure. Use bullet points for multiple factors. \
Keep recommendations under 200 words unless a detailed breakdown is requested."""


class LLMService:
    """Claude-powered F1 strategy assistant."""

    def __init__(self):
        self.client = None
        self.provider: Optional[str] = None
        self.model_name: Optional[str] = None

        # Prefer Gemini if provided (user asked to use Gemini for now).
        gemini_key = os.environ.get("GEMINI_API_KEY")
        if _GEMINI_AVAILABLE and gemini_key:
            try:
                gemini_model = os.environ.get("APEX_GEMINI_MODEL", "models/gemini-2.0-flash")
                genai.configure(api_key=gemini_key)
                self.client = genai.GenerativeModel(model_name=gemini_model)
                self.provider = "gemini"
                self.model_name = gemini_model
            except Exception as e:
                print(f"LLM: Gemini client init failed: {e}")

        # Fallback to Claude if Gemini isn't available.
        if self.client is None:
            api_key = os.environ.get("ANTHROPIC_API_KEY")
            if _ANTHROPIC_AVAILABLE and api_key:
                try:
                    self.client = anthropic.Anthropic(api_key=api_key)
                    self.provider = "anthropic"
                    self.model_name = MODEL
                except Exception as e:
                    print(f"LLM: Anthropic client init failed: {e}")

    @property
    def available(self) -> bool:
        return self.client is not None and self.provider is not None

    def narrate_strategy(self, simulation_result: dict,
                         rag_context: list[dict] = None,
                         driver_focus: Optional[str] = None) -> str:
        """Generate strategy narration from simulation output."""
        if not self.available:
            return self._fallback_narration(simulation_result, driver_focus)

        prompt_parts = ["Analyze this F1 race strategy simulation and provide recommendations.\n"]

        meta = simulation_result.get("meta", {})
        prompt_parts.append(
            f"Circuit: {meta.get('circuit', 'Unknown')} | "
            f"Laps: {meta.get('total_laps', '?')} | "
            f"Pit loss: {meta.get('pit_loss_time', '?')}s | "
            f"SC prob: {meta.get('sc_probability', '?')} | "
            f"Sims: {meta.get('n_sims', '?')}\n"
        )

        drivers = simulation_result.get("drivers", [])
        if driver_focus:
            drivers = [d for d in drivers if d["driver"] == driver_focus] or drivers[:3]
        else:
            drivers = drivers[:5]

        for d in drivers:
            prompt_parts.append(f"\n{d['driver']} ({d.get('team', '')}):")
            for i, s in enumerate(d.get("strategies", [])[:3]):
                prompt_parts.append(
                    f"  Strategy {i+1}: {s['label']} — "
                    f"{s['probability']}% optimal, avg P{s['avg_position']}"
                )

        if rag_context:
            prompt_parts.append("\nHistorical context:")
            for ctx in rag_context[:3]:
                prompt_parts.append(f"  - {ctx['text']}")

        prompt_parts.append(
            "\nProvide a strategy briefing: recommended strategy per driver, "
            "key risks, and tactical opportunities."
        )

        return self._call_llm("\n".join(prompt_parts))

    def chat(self, user_message: str,
             simulation_context: Optional[dict] = None,
             rag_context: list[dict] = None,
             conversation_history: list[dict] = None) -> str:
        """Conversational strategy query."""
        if not self.available:
            return ("APEX Strategy Assistant is offline. "
                    "Set ANTHROPIC_API_KEY or GEMINI_API_KEY to enable LLM integration.")

        messages = []

        if conversation_history:
            for msg in conversation_history[-10:]:
                messages.append({
                    "role": msg.get("role", "user"),
                    "content": msg.get("content", ""),
                })

        context_parts = []
        if simulation_context:
            meta = simulation_context.get("meta", {})
            context_parts.append(
                f"Current race: {meta.get('circuit', '?')} | "
                f"{meta.get('total_laps', '?')} laps | "
                f"SC prob {meta.get('sc_probability', '?')}"
            )
            for d in simulation_context.get("drivers", [])[:5]:
                best = d.get("strategies", [{}])[0] if d.get("strategies") else {}
                context_parts.append(
                    f"{d['driver']}: optimal {best.get('label', '?')} "
                    f"({best.get('probability', 0)}%)"
                )

        if rag_context:
            context_parts.append("Historical context:")
            for ctx in rag_context[:3]:
                context_parts.append(f"  {ctx['text']}")

        user_content = user_message
        if context_parts:
            user_content = (
                f"[Race context: {' | '.join(context_parts[:2])}]\n\n"
                f"[Driver strategies: {'; '.join(context_parts[2:6])}]\n\n"
                f"{user_message}"
            )

        messages.append({"role": "user", "content": user_content})
        return self._call_llm_messages(messages)

    def analyze_undercut(self, undercut_result: dict,
                         rag_context: list[dict] = None) -> str:
        """Narrate an undercut/overcut analysis."""
        if not self.available:
            return self._fallback_undercut(undercut_result)

        prompt = (
            f"Analyze this undercut/overcut scenario:\n"
            f"Driver ahead: {undercut_result.get('driver_ahead', '?')}\n"
            f"Driver behind: {undercut_result.get('driver_behind', '?')}\n"
            f"Current gap: {undercut_result.get('current_gap', '?')}s on lap "
            f"{undercut_result.get('current_lap', '?')}/{undercut_result.get('total_laps', '?')}\n\n"
        )

        for name, sc in undercut_result.get("scenarios", {}).items():
            prompt += (
                f"{name}: final gap {sc.get('final_gap', '?')}s, "
                f"overtake lap {sc.get('overtake_lap', 'none')}\n"
            )

        prompt += (
            f"\nRecommendation from model: {undercut_result.get('recommendation', '?')}\n"
            f"Tyre info: {json.dumps(undercut_result.get('tyre_info', {}))}\n\n"
            f"Provide a brief pit wall recommendation (under 150 words). "
            f"Be specific about timing and risks."
        )

        if rag_context:
            prompt += "\n\nHistorical context:\n"
            for ctx in rag_context[:2]:
                prompt += f"  - {ctx['text']}\n"

        return self._call_llm(prompt)

    def _call_llm(self, prompt: str) -> str:
        """Dispatch prompt to the active provider."""
        if self.provider == "anthropic":
            return self._call_claude(prompt)
        if self.provider == "gemini":
            return self._call_gemini(prompt)
        return "LLM not available"

    def _call_llm_messages(self, messages: list[dict]) -> str:
        """Dispatch messages to the active provider."""
        if self.provider == "anthropic":
            return self._call_claude_messages(messages)
        if self.provider == "gemini":
            transcript = []
            for msg in messages:
                role = (msg.get("role") or "user").upper()
                content = msg.get("content") or ""
                transcript.append(f"{role}: {content}")
            prompt = "\n".join(transcript)
            return self._call_gemini(prompt)
        return "LLM not available"

    def _call_claude(self, prompt: str) -> str:
        try:
            response = self.client.messages.create(
                model=MODEL,
                max_tokens=MAX_TOKENS,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": prompt}],
            )
            return response.content[0].text
        except Exception as e:
            return f"Claude API error: {e}"

    def _call_claude_messages(self, messages: list[dict]) -> str:
        try:
            response = self.client.messages.create(
                model=MODEL,
                max_tokens=MAX_TOKENS,
                system=SYSTEM_PROMPT,
                messages=messages,
            )
            return response.content[0].text
        except Exception as e:
            return f"Claude API error: {e}"

    def _call_gemini(self, prompt: str) -> str:
        """Call Gemini with a single prompt string."""
        try:
            # google-generativeai returns a response with `.text` for common models.
            full_prompt = f"{SYSTEM_PROMPT}\n\n{prompt}"
            response = self.client.generate_content(full_prompt)

            # Be robust to SDK differences.
            text = getattr(response, "text", None)
            if text:
                return text

            # Fallback: try candidates/parts extraction.
            candidates = getattr(response, "candidates", None) or []
            if candidates:
                parts = getattr(candidates[0], "parts", None) or []
                if parts:
                    return getattr(parts[0], "text", None) or str(parts[0])

            return str(response)
        except Exception as e:
            return f"Gemini API error: {e}"

    def _fallback_narration(self, sim: dict, driver_focus: Optional[str]) -> str:
        """Generate basic narration without Claude."""
        lines = ["**APEX Strategy Briefing**\n"]
        meta = sim.get("meta", {})
        lines.append(
            f"Circuit: {meta.get('circuit', '?')} | "
            f"{meta.get('total_laps', '?')} laps | "
            f"Pit loss: {meta.get('pit_loss_time', '?')}s\n"
        )

        drivers = sim.get("drivers", [])
        if driver_focus:
            drivers = [d for d in drivers if d["driver"] == driver_focus] or drivers

        for d in drivers[:5]:
            best = d.get("strategies", [{}])[0] if d.get("strategies") else {}
            lines.append(
                f"**{d['driver']}** ({d.get('team', '')}): "
                f"Optimal strategy **{best.get('label', '?')}** — "
                f"{best.get('probability', 0)}% probability, "
                f"avg finish P{best.get('avg_position', '?')}"
            )

        sc_pct = (meta.get("sc_probability", 0) * 100)
        if sc_pct > 40:
            lines.append(
                f"\n*High safety car probability ({sc_pct:.0f}%) — "
                f"consider strategies that benefit from free pit stops.*"
            )

        lines.append("\n*Enable an LLM (ANTHROPIC_API_KEY or GEMINI_API_KEY) for detailed analysis.*")
        return "\n".join(lines)

    def _fallback_undercut(self, result: dict) -> str:
        rec = result.get("recommendation", "stay_out")
        gap = result.get("current_gap", 0)
        scenarios = result.get("scenarios", {})
        best = scenarios.get(rec, {})
        return (
            f"**Recommendation: {rec.replace('_', ' ').title()}**\n\n"
            f"Current gap: {gap}s | "
            f"Projected final gap: {best.get('final_gap', '?')}s\n"
            f"{'Overtake on lap ' + str(best.get('overtake_lap')) if best.get('overtake_lap') else 'No overtake projected'}\n\n"
            f"*Enable an LLM (ANTHROPIC_API_KEY or GEMINI_API_KEY) for detailed analysis.*"
        )


_llm_instance: Optional[LLMService] = None


def get_llm() -> LLMService:
    """Singleton accessor for the LLM service."""
    global _llm_instance
    if _llm_instance is None:
        _llm_instance = LLMService()
        if _llm_instance.available:
            print(f"LLM: {getattr(_llm_instance, 'provider', 'unknown')} strategy assistant ready")
        else:
            print("LLM: Running without LLM (set ANTHROPIC_API_KEY or GEMINI_API_KEY to enable)")
    return _llm_instance
