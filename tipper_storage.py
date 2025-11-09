"""
Moduł przechowywania danych typera
"""
import json
import os
from typing import Dict, List, Optional
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

# Ścieżka do pliku z danymi typera
TIPPER_DATA_FILE = "tipper_data.json"


class TipperStorage:
    """Klasa do przechowywania i zarządzania danymi typera"""
    
    def __init__(self, data_file: str = TIPPER_DATA_FILE):
        self.data_file = data_file
        self.data = self._load_data()
    
    def _load_data(self) -> Dict:
        """Ładuje dane z pliku JSON"""
        if os.path.exists(self.data_file):
            try:
                with open(self.data_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError) as e:
                logger.error(f"Błąd ładowania danych typera: {e}")
                return self._get_default_data()
        else:
            return self._get_default_data()
    
    def _get_default_data(self) -> Dict:
        """Zwraca domyślną strukturę danych"""
        return {
            'players': {},  # {player_name: {predictions: {}, total_points: 0, ...}}
            'rounds': {},  # {round_id: {matches: [], start_date: ..., end_date: ...}}
            'seasons': {},  # {season_id: {rounds: [], start_date: ..., end_date: ...}}
            'leagues': {},  # {league_id: {name: ..., seasons: []}}
            'settings': {  # Ustawienia typera
                'selected_teams': []  # Lista nazw drużyn do typowania
            }
        }
    
    def _save_data(self):
        """Zapisuje dane do pliku JSON"""
        try:
            with open(self.data_file, 'w', encoding='utf-8') as f:
                json.dump(self.data, f, ensure_ascii=False, indent=2)
        except IOError as e:
            logger.error(f"Błąd zapisywania danych typera: {e}")
    
    def add_league(self, league_id: int, league_name: str = None):
        """Dodaje ligę do systemu"""
        if str(league_id) not in self.data['leagues']:
            self.data['leagues'][str(league_id)] = {
                'name': league_name or f"Liga {league_id}",
                'seasons': []
            }
            self._save_data()
    
    def add_season(self, league_id: int, season_id: str, start_date: str = None, end_date: str = None):
        """Dodaje sezon do ligi"""
        league_key = str(league_id)
        if league_key not in self.data['leagues']:
            self.add_league(league_id)
        
        if season_id not in self.data['seasons']:
            self.data['seasons'][season_id] = {
                'league_id': league_id,
                'rounds': [],
                'start_date': start_date,
                'end_date': end_date
            }
            self.data['leagues'][league_key]['seasons'].append(season_id)
            self._save_data()
    
    def add_round(self, season_id: str, round_id: str, matches: List[Dict], start_date: str = None):
        """Dodaje rundę do sezonu"""
        if season_id not in self.data['seasons']:
            # Automatycznie utwórz sezon jeśli nie istnieje
            logger.info(f"Tworzenie sezonu {season_id}")
            self.data['seasons'][season_id] = {
                'league_id': None,  # Nie wiemy jeszcze ID ligi
                'rounds': [],
                'start_date': None,
                'end_date': None
            }
        
        if round_id not in self.data['rounds']:
            # Znajdź najwcześniejszą datę meczu
            if not start_date and matches:
                match_dates = [m.get('match_date') for m in matches if m.get('match_date')]
                if match_dates:
                    start_date = min(match_dates)
            
            self.data['rounds'][round_id] = {
                'season_id': season_id,
                'matches': matches,
                'start_date': start_date,
                'predictions': {}  # {player_name: {match_id: (home, away)}}
            }
            self.data['seasons'][season_id]['rounds'].append(round_id)
            self._save_data()
    
    def add_prediction(self, round_id: str, player_name: str, match_id: str, prediction: tuple):
        """Dodaje lub aktualizuje typ gracza dla meczu (tylko jeden typ na gracza i mecz)"""
        if round_id not in self.data['rounds']:
            logger.error(f"Runda {round_id} nie istnieje")
            return False
        
        if player_name not in self.data['players']:
            self.data['players'][player_name] = {
                'predictions': {},
                'total_points': 0,
                'rounds_played': 0,
                'best_score': 0,
                'worst_score': float('inf')
            }
        
        # Sprawdź czy typ już istnieje
        existing_prediction = None
        if 'predictions' in self.data['rounds'][round_id]:
            if player_name in self.data['rounds'][round_id]['predictions']:
                if match_id in self.data['rounds'][round_id]['predictions'][player_name]:
                    existing_prediction = self.data['rounds'][round_id]['predictions'][player_name][match_id]
        
        # Dodaj lub aktualizuj typ do rundy
        if 'predictions' not in self.data['rounds'][round_id]:
            self.data['rounds'][round_id]['predictions'] = {}
        
        if player_name not in self.data['rounds'][round_id]['predictions']:
            self.data['rounds'][round_id]['predictions'][player_name] = {}
        
        # Nadpisz istniejący typ (lub dodaj nowy)
        self.data['rounds'][round_id]['predictions'][player_name][match_id] = {
            'home': prediction[0],
            'away': prediction[1],
            'timestamp': datetime.now().isoformat()
        }
        
        # Dodaj lub aktualizuj typ do gracza
        if round_id not in self.data['players'][player_name]['predictions']:
            self.data['players'][player_name]['predictions'][round_id] = {}
        
        # Nadpisz istniejący typ (lub dodaj nowy)
        self.data['players'][player_name]['predictions'][round_id][match_id] = {
            'home': prediction[0],
            'away': prediction[1],
            'timestamp': datetime.now().isoformat()
        }
        
        # Jeśli typ już istniał i mecz jest rozegrany, przelicz punkty
        if existing_prediction:
            # Sprawdź czy mecz jest rozegrany
            matches = self.data['rounds'][round_id].get('matches', [])
            for match in matches:
                if str(match.get('match_id')) == str(match_id):
                    home_goals = match.get('home_goals')
                    away_goals = match.get('away_goals')
                    if home_goals is not None and away_goals is not None:
                        # Przelicz punkty dla nowego typu
                        from tipper import Tipper
                        points = Tipper.calculate_points(prediction, (int(home_goals), int(away_goals)))
                        
                        # Aktualizuj punkty w match_points
                        if 'match_points' not in self.data['rounds'][round_id]:
                            self.data['rounds'][round_id]['match_points'] = {}
                        if player_name not in self.data['rounds'][round_id]['match_points']:
                            self.data['rounds'][round_id]['match_points'][player_name] = {}
                        
                        self.data['rounds'][round_id]['match_points'][player_name][match_id] = points
                        
                        # Przelicz całkowite punkty gracza
                        self._recalculate_player_totals()
                    break
        
        self._save_data()
        return True
    
    def update_match_result(self, round_id: str, match_id: str, home_goals: int, away_goals: int):
        """Aktualizuje wynik meczu i przelicza punkty"""
        if round_id not in self.data['rounds']:
            logger.error(f"Runda {round_id} nie istnieje")
            return
        
        # Znajdź mecz w rundzie
        matches = self.data['rounds'][round_id]['matches']
        for match in matches:
            if str(match.get('match_id')) == str(match_id):
                match['home_goals'] = home_goals
                match['away_goals'] = away_goals
                match['result_updated'] = datetime.now().isoformat()
                break
        
        # Przelicz punkty dla wszystkich graczy
        from tipper import Tipper
        predictions = self.data['rounds'][round_id].get('predictions', {})
        
        for player_name, player_predictions in predictions.items():
            if match_id in player_predictions:
                pred = player_predictions[match_id]
                prediction_tuple = (pred['home'], pred['away'])
                points = Tipper.calculate_points(prediction_tuple, (home_goals, away_goals))
                
                # Aktualizuj punkty gracza
                if player_name not in self.data['players']:
                    self.data['players'][player_name] = {
                        'predictions': {},
                        'total_points': 0,
                        'rounds_played': 0,
                        'best_score': 0,
                        'worst_score': float('inf')
                    }
                
                # Zapisz punkty dla tego meczu
                if 'match_points' not in self.data['rounds'][round_id]:
                    self.data['rounds'][round_id]['match_points'] = {}
                if player_name not in self.data['rounds'][round_id]['match_points']:
                    self.data['rounds'][round_id]['match_points'][player_name] = {}
                
                self.data['rounds'][round_id]['match_points'][player_name][match_id] = points
        
        self._save_data()
        self._recalculate_player_totals()
    
    def _recalculate_player_totals(self):
        """Przelicza całkowite punkty dla wszystkich graczy"""
        from tipper import Tipper
        
        for player_name, player_data in self.data['players'].items():
            total_points = 0
            rounds_played = 0
            best_score = 0
            worst_score = float('inf')
            round_scores = {}  # {round_id: total_points_in_round}
            
            # Przejdź przez wszystkie rundy
            for round_id, round_data in self.data['rounds'].items():
                if player_name in round_data.get('predictions', {}):
                    round_points = 0
                    match_points = round_data.get('match_points', {}).get(player_name, {})
                    
                    # Sumuj punkty z meczów w rundzie
                    for match_id, points in match_points.items():
                        round_points += points
                    
                    if round_points > 0:
                        round_scores[round_id] = round_points
                        total_points += round_points
                        rounds_played += 1
                        best_score = max(best_score, round_points)
                        worst_score = min(worst_score, round_points)
            
            # Aktualizuj dane gracza
            player_data['total_points'] = total_points
            player_data['rounds_played'] = rounds_played
            player_data['best_score'] = best_score if best_score > 0 else 0
            player_data['worst_score'] = worst_score if worst_score != float('inf') else 0
            player_data['round_scores'] = round_scores
        
        self._save_data()
    
    def get_round_predictions(self, round_id: str) -> Dict:
        """Zwraca typy dla rundy"""
        if round_id not in self.data['rounds']:
            return {}
        return self.data['rounds'][round_id].get('predictions', {})
    
    def get_player_predictions(self, player_name: str, round_id: str = None) -> Dict:
        """Zwraca typy gracza"""
        if player_name not in self.data['players']:
            return {}
        
        if round_id:
            return self.data['players'][player_name]['predictions'].get(round_id, {})
        else:
            return self.data['players'][player_name]['predictions']
    
    def get_leaderboard(self, exclude_worst: bool = True) -> List[Dict]:
        """Zwraca ranking graczy (z opcją odrzucenia najgorszego wyniku)"""
        leaderboard = []
        
        # Pobierz wszystkie rundy posortowane po dacie (najstarsza pierwsza)
        all_rounds = sorted(self.data['rounds'].items(), key=lambda x: x[1].get('start_date', ''))
        
        for player_name, player_data in self.data['players'].items():
            total_points = player_data['total_points']
            worst_score = player_data.get('worst_score', 0)
            round_scores = player_data.get('round_scores', {})
            
            # Zbierz punkty z każdej kolejki w kolejności (najstarsza pierwsza)
            round_points_list = []
            for round_id, round_data in all_rounds:
                round_points = round_scores.get(round_id, 0)
                round_points_list.append(round_points)
            
            # Odrzuć najgorszy wynik jeśli exclude_worst=True
            final_total_points = total_points
            if exclude_worst and worst_score > 0:
                final_total_points -= worst_score
            
            leaderboard.append({
                'player_name': player_name,
                'total_points': final_total_points,
                'rounds_played': player_data['rounds_played'],
                'best_score': player_data.get('best_score', 0),
                'worst_score': worst_score,
                'excluded_worst': exclude_worst and worst_score > 0,
                'round_points': round_points_list,  # Lista punktów z każdej kolejki
                'original_total': total_points  # Suma przed odrzuceniem najgorszego
            })
        
        # Sortuj po punktach (malejąco)
        leaderboard.sort(key=lambda x: x['total_points'], reverse=True)
        
        return leaderboard
    
    def get_round_leaderboard(self, round_id: str) -> List[Dict]:
        """Zwraca ranking graczy dla konkretnej rundy"""
        if round_id not in self.data['rounds']:
            return []
        
        round_data = self.data['rounds'][round_id]
        match_points = round_data.get('match_points', {})
        predictions = round_data.get('predictions', {})
        matches = round_data.get('matches', [])
        
        # Stwórz mapę match_id -> mecz dla łatwego dostępu
        matches_map = {str(m.get('match_id', '')): m for m in matches}
        
        # Pobierz wszystkich graczy, którzy mają typy w jakiejkolwiek kolejce
        all_players = set()
        for player_name in self.data['players'].keys():
            all_players.add(player_name)
        
        # Dodaj graczy, którzy mają typy w tej konkretnej kolejce
        for player_name in predictions.keys():
            all_players.add(player_name)
        
        # Oblicz punkty dla każdego gracza w rundzie
        player_scores = {}
        for player_name in all_players:
            total_points = 0
            matches_count = 0
            match_points_list = []  # Lista punktów za każdy mecz w kolejności
            
            # Sumuj punkty z meczów (w kolejności meczów)
            if player_name in match_points:
                # Sortuj mecze według daty lub kolejności
                sorted_match_ids = sorted(match_points[player_name].keys(), 
                                         key=lambda mid: matches_map.get(mid, {}).get('match_date', ''))
                
                for match_id in sorted_match_ids:
                    points = match_points[player_name][match_id]
                    total_points += points
                    matches_count += 1
                    match_points_list.append(points)
            
            # Jeśli gracz nie typował w tej kolejce, ma 0 punktów
            if total_points == 0 and matches_count == 0:
                # Dla każdego meczu w rundzie dodaj 0
                sorted_match_ids = sorted([str(m.get('match_id', '')) for m in matches],
                                         key=lambda mid: matches_map.get(mid, {}).get('match_date', ''))
                for match_id in sorted_match_ids:
                    match_points_list.append(0)
            
            player_scores[player_name] = {
                'player_name': player_name,
                'total_points': total_points,
                'matches_count': matches_count,
                'match_points': match_points_list  # Lista punktów za każdy mecz
            }
        
        # Konwertuj na listę i sortuj
        leaderboard = list(player_scores.values())
        leaderboard.sort(key=lambda x: x['total_points'], reverse=True)
        
        return leaderboard
    
    def get_round_matches(self, round_id: str) -> List[Dict]:
        """Zwraca mecze w rundzie"""
        if round_id not in self.data['rounds']:
            return []
        return self.data['rounds'][round_id].get('matches', [])
    
    def get_selected_teams(self) -> List[str]:
        """Zwraca listę wybranych drużyn do typowania"""
        if 'settings' not in self.data:
            self.data['settings'] = {'selected_teams': []}
        return self.data['settings'].get('selected_teams', [])
    
    def set_selected_teams(self, team_names: List[str]):
        """Zapisuje listę wybranych drużyn do typowania"""
        if 'settings' not in self.data:
            self.data['settings'] = {}
        self.data['settings']['selected_teams'] = team_names
        self._save_data()

