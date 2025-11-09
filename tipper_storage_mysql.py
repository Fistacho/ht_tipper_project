"""
Moduł przechowywania danych typera w bazie MySQL
"""
import json
import os
import logging
from typing import Dict, List, Optional
from datetime import datetime
import streamlit as st

logger = logging.getLogger(__name__)


class TipperStorageMySQL:
    """Klasa do przechowywania i zarządzania danymi typera w MySQL"""
    
    def __init__(self):
        """Inicjalizuje połączenie z bazą MySQL"""
        try:
            # Użyj Streamlit connection do MySQL
            self.conn = st.connection('mysql', type='sql')
            self._init_database()
            logger.info("Połączono z bazą MySQL")
        except Exception as e:
            logger.error(f"Błąd połączenia z MySQL: {e}")
            raise
    
    def _init_database(self):
        """Inicjalizuje strukturę bazy danych (tworzy tabele jeśli nie istnieją)"""
        try:
            # Tabela graczy
            self.conn.query("""
                CREATE TABLE IF NOT EXISTS players (
                    player_name VARCHAR(255) PRIMARY KEY,
                    total_points INT DEFAULT 0,
                    rounds_played INT DEFAULT 0,
                    best_score INT DEFAULT 0,
                    worst_score INT DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
            """, ttl=0)
            
            # Tabela lig
            self.conn.query("""
                CREATE TABLE IF NOT EXISTS leagues (
                    league_id VARCHAR(50) PRIMARY KEY,
                    league_name VARCHAR(255),
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
            """, ttl=0)
            
            # Tabela sezonów
            self.conn.query("""
                CREATE TABLE IF NOT EXISTS seasons (
                    season_id VARCHAR(255) PRIMARY KEY,
                    league_id VARCHAR(50),
                    start_date VARCHAR(50),
                    end_date VARCHAR(50),
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (league_id) REFERENCES leagues(league_id) ON DELETE CASCADE
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
            """, ttl=0)
            
            # Tabela rund
            self.conn.query("""
                CREATE TABLE IF NOT EXISTS rounds (
                    round_id VARCHAR(255) PRIMARY KEY,
                    season_id VARCHAR(255),
                    start_date VARCHAR(50),
                    end_date VARCHAR(50),
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (season_id) REFERENCES seasons(season_id) ON DELETE CASCADE
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
            """, ttl=0)
            
            # Tabela meczów
            self.conn.query("""
                CREATE TABLE IF NOT EXISTS matches (
                    match_id VARCHAR(255),
                    round_id VARCHAR(255),
                    home_team_name VARCHAR(255),
                    away_team_name VARCHAR(255),
                    match_date VARCHAR(50),
                    home_goals INT,
                    away_goals INT,
                    league_id INT,
                    PRIMARY KEY (match_id, round_id),
                    FOREIGN KEY (round_id) REFERENCES rounds(round_id) ON DELETE CASCADE
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
            """, ttl=0)
            
            # Tabela typów (predictions)
            self.conn.query("""
                CREATE TABLE IF NOT EXISTS predictions (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    round_id VARCHAR(255),
                    player_name VARCHAR(255),
                    match_id VARCHAR(255),
                    home_goals INT,
                    away_goals INT,
                    timestamp VARCHAR(50),
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                    UNIQUE KEY unique_prediction (round_id, player_name, match_id),
                    FOREIGN KEY (round_id) REFERENCES rounds(round_id) ON DELETE CASCADE,
                    FOREIGN KEY (player_name) REFERENCES players(player_name) ON DELETE CASCADE
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
            """, ttl=0)
            
            # Tabela punktów za mecze
            self.conn.query("""
                CREATE TABLE IF NOT EXISTS match_points (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    round_id VARCHAR(255),
                    player_name VARCHAR(255),
                    match_id VARCHAR(255),
                    points INT DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                    UNIQUE KEY unique_match_points (round_id, player_name, match_id),
                    FOREIGN KEY (round_id) REFERENCES rounds(round_id) ON DELETE CASCADE,
                    FOREIGN KEY (player_name) REFERENCES players(player_name) ON DELETE CASCADE
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
            """, ttl=0)
            
            # Tabela ustawień
            self.conn.query("""
                CREATE TABLE IF NOT EXISTS settings (
                    setting_key VARCHAR(255) PRIMARY KEY,
                    setting_value TEXT,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
            """, ttl=0)
            
            logger.info("Struktura bazy danych zainicjalizowana")
        except Exception as e:
            logger.error(f"Błąd inicjalizacji bazy danych: {e}")
            raise
    
    @property
    def data(self) -> Dict:
        """Zwraca dane w formacie JSON (dla kompatybilności z TipperStorage)"""
        return self._load_data()
    
    def _load_data(self) -> Dict:
        """Ładuje wszystkie dane z bazy MySQL do formatu JSON"""
        try:
            data = {
                'players': {},
                'rounds': {},
                'seasons': {},
                'leagues': {},
                'settings': {}
            }
            
            # Załaduj graczy
            players_df = self.conn.query("SELECT * FROM players", ttl=0)
            for _, row in players_df.iterrows():
                data['players'][row['player_name']] = {
                    'total_points': int(row['total_points']) if row['total_points'] else 0,
                    'rounds_played': int(row['rounds_played']) if row['rounds_played'] else 0,
                    'best_score': int(row['best_score']) if row['best_score'] else 0,
                    'worst_score': int(row['worst_score']) if row['worst_score'] else 0,
                    'predictions': {}
                }
            
            # Załaduj ligi
            leagues_df = self.conn.query("SELECT * FROM leagues", ttl=0)
            for _, row in leagues_df.iterrows():
                data['leagues'][row['league_id']] = {
                    'name': row['league_name'],
                    'seasons': []
                }
            
            # Załaduj sezony
            seasons_df = self.conn.query("SELECT * FROM seasons", ttl=0)
            for _, row in seasons_df.iterrows():
                data['seasons'][row['season_id']] = {
                    'league_id': row['league_id'],
                    'rounds': [],
                    'start_date': row['start_date'],
                    'end_date': row['end_date']
                }
            
            # Załaduj rundy
            rounds_df = self.conn.query("SELECT * FROM rounds", ttl=0)
            for _, row in rounds_df.iterrows():
                round_id = row['round_id']
                data['rounds'][round_id] = {
                    'season_id': row['season_id'],
                    'start_date': row['start_date'],
                    'end_date': row['end_date'],
                    'matches': [],
                    'predictions': {},
                    'match_points': {}
                }
                
                # Załaduj mecze dla rundy
                matches_df = self.conn.query(
                    f"SELECT * FROM matches WHERE round_id = '{round_id}'", ttl=0
                )
                for _, match_row in matches_df.iterrows():
                    data['rounds'][round_id]['matches'].append({
                        'match_id': match_row['match_id'],
                        'home_team_name': match_row['home_team_name'],
                        'away_team_name': match_row['away_team_name'],
                        'match_date': match_row['match_date'],
                        'home_goals': match_row['home_goals'],
                        'away_goals': match_row['away_goals'],
                        'league_id': match_row['league_id']
                    })
                
                # Załaduj typy dla rundy
                predictions_df = self.conn.query(
                    f"SELECT * FROM predictions WHERE round_id = '{round_id}'", ttl=0
                )
                for _, pred_row in predictions_df.iterrows():
                    player_name = pred_row['player_name']
                    match_id = pred_row['match_id']
                    if player_name not in data['rounds'][round_id]['predictions']:
                        data['rounds'][round_id]['predictions'][player_name] = {}
                    data['rounds'][round_id]['predictions'][player_name][match_id] = {
                        'home': int(pred_row['home_goals']),
                        'away': int(pred_row['away_goals']),
                        'timestamp': pred_row['timestamp']
                    }
                    
                    # Dodaj do gracza
                    if player_name in data['players']:
                        if round_id not in data['players'][player_name]['predictions']:
                            data['players'][player_name]['predictions'][round_id] = {}
                        data['players'][player_name]['predictions'][round_id][match_id] = {
                            'home': int(pred_row['home_goals']),
                            'away': int(pred_row['away_goals']),
                            'timestamp': pred_row['timestamp']
                        }
                
                # Załaduj punkty za mecze
                match_points_df = self.conn.query(
                    f"SELECT * FROM match_points WHERE round_id = '{round_id}'", ttl=0
                )
                for _, points_row in match_points_df.iterrows():
                    player_name = points_row['player_name']
                    match_id = points_row['match_id']
                    if player_name not in data['rounds'][round_id]['match_points']:
                        data['rounds'][round_id]['match_points'][player_name] = {}
                    data['rounds'][round_id]['match_points'][player_name][match_id] = int(points_row['points'])
            
            # Załaduj ustawienia
            settings_df = self.conn.query("SELECT * FROM settings", ttl=0)
            for _, row in settings_df.iterrows():
                key = row['setting_key']
                value = row['setting_value']
                try:
                    data['settings'][key] = json.loads(value)
                except:
                    data['settings'][key] = value
            
            logger.info(f"Załadowano dane z MySQL: {len(data.get('players', {}))} graczy, {len(data.get('rounds', {}))} rund")
            return data
        except Exception as e:
            logger.error(f"Błąd ładowania danych z MySQL: {e}")
            return self._get_default_data()
    
    def _get_default_data(self) -> Dict:
        """Zwraca domyślną strukturę danych"""
        return {
            'players': {},
            'rounds': {},
            'seasons': {},
            'leagues': {},
            'settings': {
                'selected_teams': []
            }
        }
    
    def reload_data(self):
        """Przeładowuje dane z bazy (dla kompatybilności)"""
        logger.info("Przeładowano dane z MySQL")
    
    def _save_data(self):
        """Zapisuje dane do bazy (dla kompatybilności - dane są zapisywane na bieżąco)"""
        # W MySQL dane są zapisywane na bieżąco, więc ta metoda jest pusta
        pass
    
    def add_league(self, league_id: int, league_name: str = None):
        """Dodaje ligę do systemu"""
        try:
            league_id_str = str(league_id)
            self.conn.query(
                f"INSERT INTO leagues (league_id, league_name) VALUES ('{league_id_str}', '{league_name or f\"Liga {league_id}\"}') "
                f"ON DUPLICATE KEY UPDATE league_name = '{league_name or f\"Liga {league_id}\"}'",
                ttl=0
            )
            logger.info(f"Dodano ligę: {league_id}")
        except Exception as e:
            logger.error(f"Błąd dodawania ligi: {e}")
    
    def add_season(self, league_id: int, season_id: str, start_date: str = None, end_date: str = None):
        """Dodaje sezon do ligi"""
        try:
            league_id_str = str(league_id)
            self.add_league(league_id, None)
            
            self.conn.query(
                f"INSERT INTO seasons (season_id, league_id, start_date, end_date) "
                f"VALUES ('{season_id}', '{league_id_str}', '{start_date or ''}', '{end_date or ''}') "
                f"ON DUPLICATE KEY UPDATE league_id = '{league_id_str}', start_date = '{start_date or ''}', end_date = '{end_date or ''}'",
                ttl=0
            )
            logger.info(f"Dodano sezon: {season_id}")
        except Exception as e:
            logger.error(f"Błąd dodawania sezonu: {e}")
    
    def add_round(self, season_id: str, round_id: str, matches: List[Dict], start_date: str = None):
        """Dodaje rundę do sezonu"""
        try:
            # Dodaj sezon jeśli nie istnieje
            if not self.conn.query(f"SELECT * FROM seasons WHERE season_id = '{season_id}'", ttl=0).empty:
                pass
            else:
                self.add_season(None, season_id, None, None)
            
            # Dodaj rundę
            self.conn.query(
                f"INSERT INTO rounds (round_id, season_id, start_date, end_date) "
                f"VALUES ('{round_id}', '{season_id}', '{start_date or ''}', '{start_date or ''}') "
                f"ON DUPLICATE KEY UPDATE season_id = '{season_id}', start_date = '{start_date or ''}', end_date = '{start_date or ''}'",
                ttl=0
            )
            
            # Dodaj mecze
            for match in matches:
                match_id = str(match.get('match_id', ''))
                home_team = match.get('home_team_name', '').replace("'", "''")
                away_team = match.get('away_team_name', '').replace("'", "''")
                match_date = match.get('match_date', '').replace("'", "''")
                home_goals = match.get('home_goals') if match.get('home_goals') is not None else 'NULL'
                away_goals = match.get('away_goals') if match.get('away_goals') is not None else 'NULL'
                league_id = match.get('league_id', 'NULL')
                
                self.conn.query(
                    f"INSERT INTO matches (match_id, round_id, home_team_name, away_team_name, match_date, home_goals, away_goals, league_id) "
                    f"VALUES ('{match_id}', '{round_id}', '{home_team}', '{away_team}', '{match_date}', {home_goals}, {away_goals}, {league_id}) "
                    f"ON DUPLICATE KEY UPDATE home_team_name = '{home_team}', away_team_name = '{away_team}', "
                    f"match_date = '{match_date}', home_goals = {home_goals}, away_goals = {away_goals}, league_id = {league_id}",
                    ttl=0
                )
            
            logger.info(f"Dodano rundę: {round_id} z {len(matches)} meczami")
        except Exception as e:
            logger.error(f"Błąd dodawania rundy: {e}")
            raise
    
    def add_prediction(self, round_id: str, player_name: str, match_id: str, prediction: tuple):
        """Dodaje lub aktualizuje typ gracza dla meczu"""
        try:
            # Upewnij się, że gracz istnieje
            self.conn.query(
                f"INSERT INTO players (player_name, total_points, rounds_played, best_score, worst_score) "
                f"VALUES ('{player_name}', 0, 0, 0, 0) "
                f"ON DUPLICATE KEY UPDATE player_name = '{player_name}'",
                ttl=0
            )
            
            # Dodaj lub zaktualizuj typ
            timestamp = datetime.now().isoformat()
            self.conn.query(
                f"INSERT INTO predictions (round_id, player_name, match_id, home_goals, away_goals, timestamp) "
                f"VALUES ('{round_id}', '{player_name}', '{match_id}', {prediction[0]}, {prediction[1]}, '{timestamp}') "
                f"ON DUPLICATE KEY UPDATE home_goals = {prediction[0]}, away_goals = {prediction[1]}, timestamp = '{timestamp}'",
                ttl=0
            )
            
            # Jeśli mecz jest rozegrany, przelicz punkty
            match_result = self.conn.query(
                f"SELECT home_goals, away_goals FROM matches WHERE match_id = '{match_id}' AND round_id = '{round_id}'",
                ttl=0
            )
            if not match_result.empty and match_result.iloc[0]['home_goals'] is not None and match_result.iloc[0]['away_goals'] is not None:
                from tipper import Tipper
                home_goals = int(match_result.iloc[0]['home_goals'])
                away_goals = int(match_result.iloc[0]['away_goals'])
                points = Tipper.calculate_points(prediction, (home_goals, away_goals))
                
                # Zapisz punkty
                self.conn.query(
                    f"INSERT INTO match_points (round_id, player_name, match_id, points) "
                    f"VALUES ('{round_id}', '{player_name}', '{match_id}', {points}) "
                    f"ON DUPLICATE KEY UPDATE points = {points}",
                    ttl=0
                )
                
                # Przelicz całkowite punkty gracza
                self._recalculate_player_totals()
            
            logger.info(f"Dodano typ: {player_name} dla meczu {match_id} w rundzie {round_id}")
            return True
        except Exception as e:
            logger.error(f"Błąd dodawania typu: {e}")
            return False
    
    def update_match_result(self, round_id: str, match_id: str, home_goals: int, away_goals: int):
        """Aktualizuje wynik meczu i przelicza punkty"""
        try:
            # Aktualizuj wynik meczu
            self.conn.query(
                f"UPDATE matches SET home_goals = {home_goals}, away_goals = {away_goals} "
                f"WHERE match_id = '{match_id}' AND round_id = '{round_id}'",
                ttl=0
            )
            
            # Przelicz punkty dla wszystkich graczy
            from tipper import Tipper
            predictions_df = self.conn.query(
                f"SELECT * FROM predictions WHERE round_id = '{round_id}' AND match_id = '{match_id}'",
                ttl=0
            )
            
            for _, pred_row in predictions_df.iterrows():
                player_name = pred_row['player_name']
                prediction = (int(pred_row['home_goals']), int(pred_row['away_goals']))
                points = Tipper.calculate_points(prediction, (home_goals, away_goals))
                
                # Zapisz punkty
                self.conn.query(
                    f"INSERT INTO match_points (round_id, player_name, match_id, points) "
                    f"VALUES ('{round_id}', '{player_name}', '{match_id}', {points}) "
                    f"ON DUPLICATE KEY UPDATE points = {points}",
                    ttl=0
                )
            
            # Przelicz całkowite punkty graczy
            self._recalculate_player_totals()
            logger.info(f"Zaktualizowano wynik meczu {match_id} w rundzie {round_id}")
        except Exception as e:
            logger.error(f"Błąd aktualizacji wyniku meczu: {e}")
    
    def _recalculate_player_totals(self):
        """Przelicza całkowite punkty dla wszystkich graczy"""
        try:
            from tipper import Tipper
            
            # Pobierz wszystkich graczy
            players_df = self.conn.query("SELECT player_name FROM players", ttl=0)
            
            for _, player_row in players_df.iterrows():
                player_name = player_row['player_name']
                
                # Pobierz wszystkie punkty gracza
                points_df = self.conn.query(
                    f"SELECT points FROM match_points WHERE player_name = '{player_name}'",
                    ttl=0
                )
                
                total_points = int(points_df['points'].sum()) if not points_df.empty else 0
                
                # Pobierz punkty per runda
                round_points_df = self.conn.query(
                    f"SELECT round_id, SUM(points) as round_total FROM match_points WHERE player_name = '{player_name}' GROUP BY round_id",
                    ttl=0
                )
                
                rounds_played = len(round_points_df) if not round_points_df.empty else 0
                best_score = int(round_points_df['round_total'].max()) if not round_points_df.empty and len(round_points_df) > 0 else 0
                worst_score = int(round_points_df['round_total'].min()) if not round_points_df.empty and len(round_points_df) > 0 else 0
                
                # Aktualizuj gracza
                self.conn.query(
                    f"UPDATE players SET total_points = {total_points}, rounds_played = {rounds_played}, "
                    f"best_score = {best_score}, worst_score = {worst_score} WHERE player_name = '{player_name}'",
                    ttl=0
                )
            
            logger.info("Przeliczono całkowite punkty dla wszystkich graczy")
        except Exception as e:
            logger.error(f"Błąd przeliczania punktów: {e}")
    
    def get_round_predictions(self, round_id: str) -> Dict:
        """Zwraca typy dla rundy"""
        try:
            predictions_df = self.conn.query(
                f"SELECT * FROM predictions WHERE round_id = '{round_id}'",
                ttl=0
            )
            
            result = {}
            for _, row in predictions_df.iterrows():
                player_name = row['player_name']
                match_id = row['match_id']
                if player_name not in result:
                    result[player_name] = {}
                result[player_name][match_id] = {
                    'home': int(row['home_goals']),
                    'away': int(row['away_goals']),
                    'timestamp': row['timestamp']
                }
            
            return result
        except Exception as e:
            logger.error(f"Błąd pobierania typów dla rundy: {e}")
            return {}
    
    def get_player_predictions(self, player_name: str, round_id: str = None) -> Dict:
        """Zwraca typy gracza"""
        try:
            if round_id:
                query = f"SELECT * FROM predictions WHERE player_name = '{player_name}' AND round_id = '{round_id}'"
            else:
                query = f"SELECT * FROM predictions WHERE player_name = '{player_name}'"
            
            predictions_df = self.conn.query(query, ttl=0)
            
            if round_id:
                result = {}
                for _, row in predictions_df.iterrows():
                    result[row['match_id']] = {
                        'home': int(row['home_goals']),
                        'away': int(row['away_goals']),
                        'timestamp': row['timestamp']
                    }
                return result
            else:
                result = {}
                for _, row in predictions_df.iterrows():
                    r_id = row['round_id']
                    if r_id not in result:
                        result[r_id] = {}
                    result[r_id][row['match_id']] = {
                        'home': int(row['home_goals']),
                        'away': int(row['away_goals']),
                        'timestamp': row['timestamp']
                    }
                return result
        except Exception as e:
            logger.error(f"Błąd pobierania typów gracza: {e}")
            return {}
    
    def get_leaderboard(self, exclude_worst: bool = True) -> List[Dict]:
        """Zwraca ranking graczy (z opcją odrzucenia najgorszego wyniku)"""
        try:
            players_df = self.conn.query("SELECT * FROM players ORDER BY total_points DESC", ttl=0)
            
            leaderboard = []
            for _, row in players_df.iterrows():
                player_name = row['player_name']
                
                # Pobierz punkty per runda
                round_points_df = self.conn.query(
                    f"SELECT round_id, SUM(points) as round_total FROM match_points WHERE player_name = '{player_name}' GROUP BY round_id ORDER BY round_total",
                    ttl=0
                )
                
                round_points = [int(p) for p in round_points_df['round_total']] if not round_points_df.empty else []
                original_total = int(row['total_points'])
                worst_score = int(row['worst_score']) if row['worst_score'] else 0
                
                if exclude_worst and worst_score > 0 and len(round_points) > 1:
                    total_points = original_total - worst_score
                    excluded_worst = True
                else:
                    total_points = original_total
                    excluded_worst = False
                
                leaderboard.append({
                    'player_name': player_name,
                    'total_points': total_points,
                    'original_total': original_total,
                    'rounds_played': int(row['rounds_played']),
                    'best_score': int(row['best_score']),
                    'worst_score': worst_score,
                    'excluded_worst': excluded_worst,
                    'round_points': sorted(round_points, reverse=True)
                })
            
            leaderboard.sort(key=lambda x: x['total_points'], reverse=True)
            return leaderboard
        except Exception as e:
            logger.error(f"Błąd pobierania rankingu: {e}")
            return []
    
    def get_round_leaderboard(self, round_id: str) -> List[Dict]:
        """Zwraca ranking dla rundy"""
        try:
            # Pobierz punkty per gracz dla rundy
            points_df = self.conn.query(
                f"SELECT player_name, match_id, points FROM match_points WHERE round_id = '{round_id}' ORDER BY player_name, match_id",
                ttl=0
            )
            
            player_totals = {}
            player_match_points = {}
            
            for _, row in points_df.iterrows():
                player_name = row['player_name']
                match_id = row['match_id']
                points = int(row['points'])
                
                if player_name not in player_totals:
                    player_totals[player_name] = 0
                    player_match_points[player_name] = []
                
                player_totals[player_name] += points
                player_match_points[player_name].append(points)
            
            # Stwórz ranking
            leaderboard = []
            for player_name, total_points in sorted(player_totals.items(), key=lambda x: x[1], reverse=True):
                leaderboard.append({
                    'player_name': player_name,
                    'total_points': total_points,
                    'match_points': player_match_points[player_name],
                    'matches_count': len(player_match_points[player_name])
                })
            
            return leaderboard
        except Exception as e:
            logger.error(f"Błąd pobierania rankingu rundy: {e}")
            return []
    
    def get_selected_teams(self) -> List[str]:
        """Zwraca listę wybranych drużyn"""
        try:
            result = self.conn.query(
                "SELECT setting_value FROM settings WHERE setting_key = 'selected_teams'",
                ttl=0
            )
            if not result.empty:
                value = result.iloc[0]['setting_value']
                return json.loads(value) if value else []
            return []
        except Exception as e:
            logger.error(f"Błąd pobierania wybranych drużyn: {e}")
            return []
    
    def set_selected_teams(self, teams: List[str]):
        """Zapisuje listę wybranych drużyn"""
        try:
            value = json.dumps(teams)
            self.conn.query(
                f"INSERT INTO settings (setting_key, setting_value) VALUES ('selected_teams', '{value}') "
                f"ON DUPLICATE KEY UPDATE setting_value = '{value}'",
                ttl=0
            )
            logger.info(f"Zapisano wybrane drużyny: {len(teams)}")
        except Exception as e:
            logger.error(f"Błąd zapisywania wybranych drużyn: {e}")

