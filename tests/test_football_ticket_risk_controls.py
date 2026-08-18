from src.football_quant.ticket_builder import build_legs, build_tickets


def _leg(fid, market, selection, price, probability, score):
    return {
        'fixture_id': fid,
        'market': market,
        'selection': selection,
        'odd': price,
        'model_probability': probability,
        'score': score,
        'signal_source': 'MODEL+MARKET',
        'bookmaker_quotes': {'Book A': price, 'Book B': round(price - 0.01, 2)},
    }


def test_fixture_is_used_in_only_one_ticket():
    legs = [
        _leg(1, 'Dupla chance', 'A ou empate', 1.28, 0.82, 82),
        _leg(2, 'Total de gols', 'Mais de 1.5', 1.30, 0.81, 81),
        _leg(3, 'Dupla chance', 'C ou empate', 1.31, 0.80, 80),
        _leg(4, 'Total de gols', 'Menos de 4.5', 1.27, 0.84, 84),
        _leg(5, 'Vencedor', 'E', 1.72, 0.64, 74),
    ]
    tickets = build_tickets(legs, target=3)
    fixture_ids = [leg['fixture_id'] for ticket in tickets for leg in ticket['legs']]
    assert len(tickets) == 3
    assert len(fixture_ids) == len(set(fixture_ids))


def test_coarse_probability_cup_double_chance_requires_strong_market():
    fixture = {
        'fixture': {'id': 99, 'status': {'short': 'NS'}, 'date': '2026-08-18T13:30:00-03:00'},
        'league': {'name': 'Svenska Cupen', 'country': 'Sweden', 'type': 'Cup'},
        'teams': {'home': {'name': 'Karlberg'}, 'away': {'name': 'IK brage'}},
    }
    prediction = {
        'predictions': {
            'percent': {'home': '0%', 'draw': '50%', 'away': '50%'},
            'advice': 'draw or IK brage',
            'under_over': '-2.5',
        },
        'comparison': {},
    }
    odds = {'bookmakers': []}
    for i, odd in enumerate([1.36, 1.32, 1.28, 1.20, 1.32, 1.36, 1.32, 1.32, 1.27, 1.35]):
        odds['bookmakers'].append({
            'name': f'B{i}',
            'bets': [{'name': 'Double Chance', 'values': [{'value': 'Draw/Away', 'odd': odd}]}],
        })

    legs = build_legs(fixture, prediction, odds)
    assert not any(leg['market'] == 'Dupla chance' for leg in legs)
