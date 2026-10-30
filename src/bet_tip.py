"""Strictly weaker, quoted alternatives to an AI bet rejected by the model."""
import math

from src.bet_audit import norm
from src.combo_ticket import binary_market


def relaxation_distance(pick, bet):
    """Distance between binary lines whose winning results contain the AI's.

    Win is equivalent to handicap -0.5; +0.5 covers win or draw. Only the
    same team or same totals direction can qualify. Push/quarter lines and
    BTTS have no default relaxation. No bounded score-grid approximation.
    """
    pm, bm = pick.get('market', ''), bet.get('market', '')
    if not binary_market(pm) or not binary_market(bm):
        return None
    if pm.startswith('Over/Under ') and bm.startswith('Over/Under ') and pick['outcome'] == bet['outcome']:
        a, b = float(pm.split()[-1]), float(bm.split()[-1])
        distance = b - a if pick['outcome'] == 'Under' else a - b
        return distance if distance > 0 else None
    if not pick.get('team') or norm(pick['team']) != norm(bet.get('team', '')):
        return None
    def team_line(b):
        if b['market'] == '1X2' and b['outcome'] in ('home_win', 'away_win'):
            return -.5
        if b['market'].startswith('Handicap '):
            return float(b['market'].split()[-1])
        return None
    a, b = team_line(pick), team_line(bet)
    return b - a if a is not None and b is not None and b > a else None


def fallback_pick(pick, bets, min_odds=1.30):
    """Nearest quoted relaxation with model >= market; no EV filter."""
    candidates = []
    for bet in bets:
        try:
            p = bet.get('model_probability_raw')
            if p is None:
                p = bet.get('probability')
            q, odds = bet.get('market_probability'), bet.get('best_odds')
            if p is None or q is None or odds is None:
                continue
            if not all(math.isfinite(x) for x in (p, q, odds)):
                continue
            if not 0 <= q <= p <= 1 or odds < min_odds or not (bet.get('quote_fresh') or bet.get('quote_carried_forward')):
                continue
            distance = relaxation_distance(pick, bet)
            if distance is not None:
                candidates.append((distance, bet))
        except (ValueError, TypeError, KeyError):
            continue
    if not candidates:
        return None
    return min(candidates, key=lambda x: (x[0], -x[1]['best_odds'],
                                         x[1]['market'], x[1]['outcome'], x[1].get('team') or ''))[1]
