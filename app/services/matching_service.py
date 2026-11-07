"""
app/services/matching_service.py
================================
Smart Skill Matching Engine for SkillSwap.

This module contains the pure-Python matching algorithm with zero
Flask dependencies, making it trivially testable in isolation.

Matching formula (per the specification)
---------------------------------------
    Match Percentage = (Matched Skill Directions / 2) * 100

There are two possible "directions" of skill overlap:

    Direction 1 (they → me):
        The candidate TEACHES a skill that I want to LEARN.
        (candidate.teaching ∩ my.learning)

    Direction 2 (me → them):
        I TEACH a skill that the candidate wants to LEARN.
        (my.teaching ∩ candidate.learning)

    Both directions match  →  (2 / 2) * 100 = 100%  (mutual match)
    Only one direction      →  (1 / 2) * 100 = 50%
    Neither direction       →  (0 / 2) * 100 = 0%   (excluded)

Public API
----------
    compute_match(my_teaching, my_learning, candidate_teaching, candidate_learning)
        → dict | None

    find_matches(current_user, candidates, ...)
        → list[MatchResult]
"""

from dataclasses import dataclass, field
from typing import Optional


# ══════════════════════════════════════════════════════════════════
# Data classes
# ══════════════════════════════════════════════════════════════════

@dataclass
class SkillRef:
    """Lightweight skill reference — avoids coupling to the ORM model."""
    id: int
    name: str
    category: str = ''
    icon: str = 'fa-star'


@dataclass
class MatchResult:
    """The output of matching one candidate against the current user."""
    user: object                          # the candidate User ORM object
    score: int                            # 0–100
    matched_directions: int               # 0, 1, or 2
    can_teach_me: list = field(default_factory=list)   # SkillRefs they can teach me
    you_teach_them: list = field(default_factory=list)  # SkillRefs I can teach them
    reasons: list = field(default_factory=list)        # human-readable strings

    def __repr__(self):
        return f'<MatchResult {self.user} {self.score}%>'


# ══════════════════════════════════════════════════════════════════
# Core matching function (pure Python, no Flask)
# ══════════════════════════════════════════════════════════════════

def compute_match(my_teaching: list[SkillRef],
                  my_learning:  list[SkillRef],
                  cand_teaching: list[SkillRef],
                  cand_learning:  list[SkillRef]) -> Optional[dict]:
    """
    Compare two students' skill sets and return a match dict, or None
    if there is zero overlap.

    Parameters
    ----------
    my_teaching   : Skills the logged-in user can teach.
    my_learning   : Skills the logged-in user wants to learn.
    cand_teaching : Skills the candidate can teach.
    cand_learning : Skills the candidate wants to learn.

    Returns
    -------
    dict with keys:
        score              → int  (0, 50, or 100)
        matched_directions → int  (0, 1, or 2)
        can_teach_me       → list[SkillRef]  (skills they teach that I learn)
        you_teach_them     → list[SkillRef]  (skills I teach that they learn)
        reasons            → list[str]      (human-readable explanation)
    or None if no overlap exists.
    """

    # Build ID sets for fast intersection
    my_teach_ids   = {s.id for s in my_teaching}
    my_learn_ids   = {s.id for s in my_learning}
    cand_teach_ids = {s.id for s in cand_teaching}
    cand_learn_ids = {s.id for s in cand_learning}

    # ── Direction 1: they can teach me ────────────────────────
    # candidate.teaching ∩ my.learning
    can_teach_me_ids = cand_teach_ids & my_learn_ids
    direction_1 = len(can_teach_me_ids) > 0

    # ── Direction 2: I can teach them ─────────────────────────
    # my.teaching ∩ candidate.learning
    you_teach_them_ids = my_teach_ids & cand_learn_ids
    direction_2 = len(you_teach_them_ids) > 0

    # ── Count matched directions ──────────────────────────────
    matched_directions = (1 if direction_1 else 0) + (1 if direction_2 else 0)

    if matched_directions == 0:
        return None   # zero overlap — exclude from results

    # ── Score: (matched_directions / 2) * 100 ──────────────────
    score = (matched_directions // 2) * 100 if matched_directions == 2 \
            else (matched_directions * 50)
    # Equivalent: score = int((matched_directions / 2) * 100)

    # ── Build SkillRef lists for matched skills ────────────────
    can_teach_me = [s for s in cand_teaching if s.id in can_teach_me_ids]
    you_teach_them = [s for s in my_teaching if s.id in you_teach_them_ids]

    # ── Human-readable reasons ─────────────────────────────────
    reasons: list[str] = []

    if direction_1:
        names = ', '.join(s.name for s in can_teach_me)
        reasons.append(f'Can teach you: {names}')

    if direction_2:
        names = ', '.join(s.name for s in you_teach_them)
        reasons.append(f'Wants to learn from you: {names}')

    if direction_1 and direction_2:
        reasons.append('Mutual skill exchange — perfect match!')

    return {
        'score':              score,
        'matched_directions':  matched_directions,
        'can_teach_me':        can_teach_me,
        'you_teach_them':      you_teach_them,
        'reasons':             reasons,
    }


# ══════════════════════════════════════════════════════════════════
# Helper: extract SkillRefs from a User ORM object
# ══════════════════════════════════════════════════════════════════

def _to_skill_refs(user_skills) -> list[SkillRef]:
    """Convert a list of Skill ORM objects to SkillRef dataclasses."""
    return [
        SkillRef(id=s.id, name=s.name, category=s.category or '', icon=s.icon or 'fa-star')
        for s in user_skills
    ]


# ══════════════════════════════════════════════════════════════════
# Full search: match current user against all candidates
# ══════════════════════════════════════════════════════════════════

def find_matches(current_user,
                 candidates: list,
                 min_score: int = 0,
                 category_filter: str = '',
                 search_query: str = '') -> list[MatchResult]:
    """
    Run the matching algorithm for *current_user* against every
    candidate in *candidates*.

    Parameters
    ----------
    current_user    : the logged-in User ORM object
    candidates      : list of User ORM objects (already filtered to
                      active, non-admin, excluding current_user)
    min_score       : drop results below this score (default 0 = show all)
    category_filter : only include matches where at least one matched
                      skill belongs to this category
    search_query    : case-insensitive name/college substring filter

    Returns
    -------
    list[MatchResult] sorted by score descending, then by name ascending.
    Duplicates are impossible because each candidate appears at most once.
    """

    # Extract the current user's skills once
    my_teaching = _to_skill_refs(current_user.teaching_skills.all())
    my_learning = _to_skill_refs(current_user.learning_skills.all())

    # Early exit: if the user has no skills at all, return empty
    if not my_teaching and not my_learning:
        return []

    results: list[MatchResult] = []

    # Track processed user IDs to avoid duplicate recommendations
    seen_user_ids: set[int] = set()

    for candidate in candidates:
        # ── Skip duplicates (each candidate appears at most once) ──
        if candidate.id in seen_user_ids:
            continue
        seen_user_ids.add(candidate.id)
        # Skip if candidate has no skills at all
        cand_teaching = _to_skill_refs(candidate.teaching_skills.all())
        cand_learning = _to_skill_refs(candidate.learning_skills.all())

        if not cand_teaching and not cand_learning:
            continue

        match = compute_match(my_teaching, my_learning,
                              cand_teaching, cand_learning)

        if match is None:
            continue   # 0% — no overlap

        # ── Apply category filter ───────────────────────────────
        if category_filter:
            all_matched = match['can_teach_me'] + match['you_teach_them']
            if not any(s.category == category_filter for s in all_matched):
                continue

        # ── Apply search filter (name or college) ────────────────
        if search_query:
            q = search_query.lower()
            full_name = (candidate.full_name or '').lower()
            college   = (candidate.college or '').lower()
            if q not in full_name and q not in college:
                continue

        # ── Apply minimum score filter ───────────────────────────
        if match['score'] < min_score:
            continue

        # ── Build MatchResult ───────────────────────────────────
        results.append(MatchResult(
            user=candidate,
            score=match['score'],
            matched_directions=match['matched_directions'],
            can_teach_me=match['can_teach_me'],
            you_teach_them=match['you_teach_them'],
            reasons=match['reasons'],
        ))

    # ── Sort: score descending, then name ascending ──────────────
    results.sort(key=lambda r: (-r.score, r.user.full_name.lower()))

    return results
