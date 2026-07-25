import random
import re
from dataclasses import dataclass, field
from typing import List, Optional

NOTATION_RE = re.compile(r"^(\d*)d(\d+)([+-]\d+)?$", re.IGNORECASE)
ROLL_TAG_RE = re.compile(r"\[ROLL:([^\]]+)\]", re.IGNORECASE)


@dataclass
class RollResult:
    notation: str
    sides: int
    count: int
    modifier: int
    rolls: List[int]
    total: int
    mode: Optional[str] = None
    chosen: Optional[int] = None


def roll_notation(notation, mode=None):
    cleaned = notation.strip().lower().replace(" ", "")
    match = NOTATION_RE.match(cleaned)
    if not match:
        raise ValueError(f"Invalid dice notation: {notation!r}")

    count = int(match.group(1) or 1)
    sides = int(match.group(2))
    modifier = int(match.group(3) or 0)

    if mode in ("adv", "disadv"):
        if count != 1 or sides != 20:
            raise ValueError("advantage/disadvantage only apply to a single d20")
        rolls = [random.randint(1, 20), random.randint(1, 20)]
        chosen = max(rolls) if mode == "adv" else min(rolls)
        return RollResult(
            notation=cleaned, sides=sides, count=count, modifier=modifier,
            rolls=rolls, total=chosen + modifier, mode=mode, chosen=chosen
        )

    rolls = [random.randint(1, sides) for _ in range(count)]
    return RollResult(
        notation=cleaned, sides=sides, count=count, modifier=modifier,
        rolls=rolls, total=sum(rolls) + modifier
    )


def format_roll(result):
    mod_str = f"{result.modifier:+d}" if result.modifier else ""

    if result.mode:
        label = f"d20 ({result.mode})"
        return f"🎲 {label} → {result.rolls} keep {result.chosen}{mod_str} = {result.total}"

    label = f"{result.count}d{result.sides}{mod_str}"
    return f"🎲 {label} → {result.rolls}{mod_str} = {result.total}"


def resolve_roll_tags(text):
    def _sub(match):
        raw = match.group(1).strip()
        mode = None
        parts = raw.split()
        if len(parts) == 2 and parts[1].lower() in ("adv", "disadv"):
            raw, mode = parts[0], parts[1].lower()
        try:
            result = roll_notation(raw, mode=mode)
            return format_roll(result)
        except ValueError:
            return match.group(0)

    return ROLL_TAG_RE.sub(_sub, text)
