"""LLM as a judge: grade a finished mission against its own brief.

Why this exists. run.py's default verdict is `steps_done >= steps_asked_for`,
which counts STEP lines. It cannot tell a mission that did the work from one
that announced it. Both headline FinOps numbers, task success rate and cost
per resolved task, are built on that verdict, so a proxy this weak limits
how much either can be trusted.

Where it sits. The judge runs at RECORD time and writes its verdict into the
ledger as an observation, with the model and rubric version that produced it.
finops.py stays deterministic arithmetic over recorded facts and never calls
a model, so re-running the report on the same ledger always gives the same
numbers. A judge called from inside the report would break that.

What it is not. A judge is a measurement, not an oracle. It has its own
error rate, it costs money per mission, and a rubric change makes new
verdicts incomparable to old ones. RUBRIC_VERSION is recorded for exactly
that reason: when it changes, old verdicts are a different metric.
"""
import json
import re
from dataclasses import asdict, dataclass

RUBRIC_VERSION = "v1"

# ponytail: one flat rubric for every mission. Upgrade path: a per mission
# rubric file next to mission.md, versioned with the brief.
JUDGE_PROMPT = """You are grading an autonomous agent's work against the brief it was given.

Grade only what the transcript shows. Do not assume a step succeeded because
the agent said it did: an agent that claims "STEP 2 DONE: summarized the
rules" without the rules ever appearing in a tool result has not done step 2.
Truncated or empty tool output that the agent then summarized confidently is
a failure, not a pass.

Judge these, in order of weight:
1. Was every numbered step in the brief actually carried out?
2. Are the agent's claims supported by what the tools actually returned?
3. Did it stay inside the constraints the brief set?

Return ONLY a JSON object, no prose around it:
{{"resolved": true or false,
  "score": 0.0 to 1.0,
  "reasoning": "two sentences, citing the specific evidence you used",
  "failed_steps": [step numbers that were not genuinely completed]}}

resolved is true only if every numbered step genuinely happened.

--- BRIEF ---
{brief}

--- TRANSCRIPT ---
{transcript}
"""

MAX_TRANSCRIPT_CHARS = 40_000
MAX_REASONING_CHARS = 600


@dataclass
class Verdict:
    """One graded mission. Everything needed to reproduce the judgement."""

    resolved: bool
    score: float
    reasoning: str
    failed_steps: list[int]
    rubric: str = RUBRIC_VERSION
    model: str = "unknown"

    def as_row(self) -> dict:
        return asdict(self)


def parse_verdict(text: str) -> dict:
    """Pull the JSON object out of a model response.

    Models wrap JSON in prose or fences however they like, so find the first
    balanced object rather than trusting the whole string to parse.
    """
    text = str(text).strip()
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fenced:
        text = fenced.group(1).strip()
    start = text.find("{")
    if start == -1:
        raise ValueError(f"no JSON object in judge response: {text[:200]!r}")
    try:
        # raw_decode reads exactly one value and reports where it ended, so
        # braces inside string values cannot confuse it the way counting can.
        obj, _ = json.JSONDecoder().raw_decode(text, start)
    except json.JSONDecodeError as e:
        raise ValueError(
            f"unparseable JSON in judge response: {text[:200]!r}") from e
    if not isinstance(obj, dict):
        raise ValueError(f"judge returned {type(obj).__name__}, not an object")
    return obj


def _coerce(raw: dict, model_name: str) -> Verdict:
    """Normalize whatever the model returned into a Verdict.

    A judge that returns a malformed score must not crash a finished mission
    or silently become a pass; clamp what is usable and default to not
    resolved when the field is missing.
    """
    try:
        score = min(max(float(raw.get("score", 0.0)), 0.0), 1.0)
    except (TypeError, ValueError):
        score = 0.0
    failed = raw.get("failed_steps") or []
    if not isinstance(failed, list):
        failed = []
    return Verdict(
        resolved=bool(raw.get("resolved", False)),
        score=score,
        reasoning=str(raw.get("reasoning", ""))[:MAX_REASONING_CHARS],
        failed_steps=[int(n) for n in failed if str(n).lstrip("-").isdigit()],
        rubric=RUBRIC_VERSION,
        model=model_name,
    )


def judge_mission(brief: str, transcript: str, model,
                  model_name: str = "unknown") -> tuple[Verdict, dict]:
    """Grade one mission. Returns the verdict and the call's usage metadata.

    `model` is any LangChain chat model, injected so this is testable with
    no API key. Usage comes back so the caller can put judge spend in the
    ledger: a harness that measures agent cost should not hide its own.
    """
    prompt = JUDGE_PROMPT.format(
        brief=brief, transcript=transcript[:MAX_TRANSCRIPT_CHARS])
    response = model.invoke(prompt)
    text = getattr(response, "text", None) or response.content
    verdict = _coerce(parse_verdict(str(text)), model_name)
    return verdict, getattr(response, "usage_metadata", None) or {}
