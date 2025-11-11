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
        # Użyj bezwzględnej ścieżki dla pewności (szczególnie na Streamlit Cloud)
        self.data_file = os.path.abspath(data_file)
        self.github_config = self._get_github_config()
        self.data = self._load_data()
        # Mechanizm opóźnionego zapisu (debounce) - zapisuje dopiero po 2 sekundach bez zmian
        self._pending_save = False
        self._last_save_time = 0
        self._save_delay = 2.0  # 2 sekundy opóźnienia
    
    def _get_github_config(self) -> Optional[Dict]:
        """Pobiera konfigurację GitHub API z .env lub Streamlit Secrets"""
        try:
            # Najpierw spróbuj z .env (dla lokalnego rozwoju)
            from dotenv import load_dotenv
            load_dotenv()
            
            github_token = os.getenv('GITHUB_TOKEN')
            github_repo_owner = os.getenv('GITHUB_REPO_OWNER')
            github_repo_name = os.getenv('GITHUB_REPO_NAME')
            
            # Jeśli nie ma w .env, spróbuj z Streamlit Secrets (dla Streamlit Cloud)
            if not github_token:
                try:
                    import streamlit as st
                    github_token = st.secrets.get('GITHUB_TOKEN', '')
                    github_repo_owner = st.secrets.get('GITHUB_REPO_OWNER', '')
                    github_repo_name = st.secrets.get('GITHUB_REPO_NAME', '')
                except Exception:
                    pass
            
            # Jeśli wszystkie wymagane wartości są dostępne, zwróć konfigurację
            if github_token and github_repo_owner and github_repo_name:
                return {
                    'token': github_token,
                    'repo_owner': github_repo_owner,
                    'repo_name': github_repo_name
                }
        except Exception as e:
            logger.debug(f"Brak konfiguracji GitHub API: {e}")
        
        return None
    
    def _load_data(self) -> Dict:
        """Ładuje dane z pliku JSON - lokalnie lub z GitHub API"""
        # Próbuj najpierw załadować z GitHub API (jeśli skonfigurowane)
        if self.github_config:
            github_data = self._load_from_github()
            if github_data:
                logger.info(f"✅ Załadowano dane z GitHub: {len(github_data.get('players', {}))} graczy, {len(github_data.get('rounds', {}))} rund")
                return github_data
        
        # Fallback: załaduj lokalnie (dla lokalnego rozwoju)
        abs_path = os.path.abspath(self.data_file)
        
        if os.path.exists(abs_path):
            try:
                with open(abs_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    logger.info(f"Załadowano dane z pliku {abs_path}: {len(data.get('players', {}))} graczy, {len(data.get('rounds', {}))} rund")
                    return data
            except (json.JSONDecodeError, IOError) as e:
                logger.error(f"Błąd ładowania danych typera z {abs_path}: {e}")
                return self._get_default_data()
        else:
            logger.warning(f"Plik {abs_path} nie istnieje, używam domyślnych danych")
            return self._get_default_data()
    
    def _load_from_github(self) -> Optional[Dict]:
        """Ładuje dane z GitHub przez API"""
        try:
            from github import Github
            from github.Auth import Token
            import base64
            
            # Połącz z GitHub używając nowego API autoryzacji
            auth = Token(self.github_config['token'])
            g = Github(auth=auth)
            repo = g.get_repo(f"{self.github_config['repo_owner']}/{self.github_config['repo_name']}")
            
            # Nazwa pliku w repozytorium
            file_path = os.path.basename(self.data_file)
            
            # Pobierz plik z repozytorium
            file = repo.get_contents(file_path)
            
            # Dekoduj zawartość (GitHub zwraca base64)
            content = base64.b64decode(file.content).decode('utf-8')
            data = json.loads(content)
            
            return data
            
        except Exception as e:
            logger.debug(f"Nie udało się załadować z GitHub (może plik nie istnieje): {e}")
            return None
    
    def reload_data(self):
        """Przeładowuje dane z pliku (użyteczne po zmianach zewnętrznych)"""
        self.data = self._load_data()
        logger.info("Przeładowano dane z pliku")
    
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
    
    def _save_data(self, force: bool = False):
        """
        Zapisuje dane do pliku JSON - lokalnie lub przez GitHub API
        Używa mechanizmu debounce - zapisuje dopiero po 2 sekundach bez zmian
        (lub natychmiast jeśli force=True)
        """
        import time
        current_time = time.time()
        
        # Jeśli force=True, zapisz natychmiast
        if force:
            self._pending_save = False
            self._last_save_time = current_time
            self._do_save()
            return
        
        # Oznacz, że zapis jest potrzebny
        self._pending_save = True
        
        # Sprawdź czy minęło wystarczająco czasu od ostatniego zapisu
        time_since_last_save = current_time - self._last_save_time
        if time_since_last_save >= self._save_delay:
            # Zapisz natychmiast
            self._pending_save = False
            self._last_save_time = current_time
            self._do_save()
        else:
            # Zaplanuj zapis za pozostały czas
            remaining_time = self._save_delay - time_since_last_save
            logger.debug(f"Opóźniam zapis o {remaining_time:.2f} sekund (debounce)")
    
    def _do_save(self):
        """Wykonuje faktyczny zapis danych"""
        # Próbuj najpierw zapisać przez GitHub API (jeśli skonfigurowane)
        if self.github_config:
            if self._save_to_github():
                logger.debug("Zapisano dane do GitHub przez API")
                return
        
        # Fallback: zapis lokalny (dla lokalnego rozwoju)
        try:
            # Użyj bezwzględnej ścieżki dla pewności (szczególnie na Streamlit Cloud)
            abs_path = os.path.abspath(self.data_file)
            
            # Zapisuj do pliku z trybem 'w' (nadpisuje istniejący)
            with open(abs_path, 'w', encoding='utf-8') as f:
                json.dump(self.data, f, ensure_ascii=False, indent=2)
            
            logger.debug(f"Zapisano dane do pliku {abs_path}: {len(self.data.get('players', {}))} graczy, {len(self.data.get('rounds', {}))} rund")
            
            # Sprawdź czy plik rzeczywiście istnieje po zapisie
            if os.path.exists(abs_path):
                file_size = os.path.getsize(abs_path)
                logger.debug(f"Plik zapisany poprawnie, rozmiar: {file_size} bajtów")
            else:
                logger.warning(f"Plik {abs_path} nie istnieje po zapisie (może być normalne na Streamlit Cloud)")
                
        except IOError as e:
            logger.error(f"Błąd zapisywania danych typera: {e}")
    
    def flush_save(self):
        """Wymusza natychmiastowy zapis wszystkich oczekujących zmian"""
        if self._pending_save:
            import time
            self._pending_save = False
            self._last_save_time = time.time()
            self._do_save()
    
    def _save_to_github(self) -> bool:
        """Zapisuje dane do GitHub przez API (używa REST API bezpośrednio dla lepszej kompatybilności)"""
        try:
            import requests
            import base64
            
            # Przygotuj zawartość JSON
            json_content = json.dumps(self.data, ensure_ascii=False, indent=2)
            json_bytes = json_content.encode('utf-8')
            json_b64 = base64.b64encode(json_bytes).decode('utf-8')
            
            # Nazwa pliku w repozytorium
            file_path = os.path.basename(self.data_file)
            
            # URL do API GitHub
            url = f"https://api.github.com/repos/{self.github_config['repo_owner']}/{self.github_config['repo_name']}/contents/{file_path}"
            
            headers = {
                "Authorization": f"token {self.github_config['token']}",
                "Accept": "application/vnd.github.v3+json",
                "User-Agent": "Hattrick-Tipper-App"
            }
            
            # Sprawdź czy plik już istnieje
            response = requests.get(url, headers=headers)
            
            if response.status_code == 200:
                # Plik istnieje - zaktualizuj go
                file_data = response.json()
                sha = file_data['sha']
                
                data = {
                    "message": f"Auto-update: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
                    "content": json_b64,
                    "sha": sha
                }
                
                response = requests.put(url, headers=headers, json=data)
                
                if response.status_code == 200:
                    logger.info(f"Zaktualizowano plik {file_path} w GitHub")
                    return True
                else:
                    error_msg = response.text
                    logger.error(f"Błąd aktualizacji pliku w GitHub: {response.status_code}")
                    logger.error(f"Szczegóły: {error_msg[:500]}")
                    if response.status_code == 403:
                        logger.error("UWAGA: Token nie ma uprawnień do zapisu.")
                        logger.error("Dla Fine-grained token: ustaw 'Contents' permission na 'Read and write'")
                        logger.error("Dla Classic token: upewnij się, że ma uprawnienie 'repo'")
                    return False
                    
            elif response.status_code == 404:
                # Plik nie istnieje - utwórz nowy
                data = {
                    "message": f"Auto-create: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
                    "content": json_b64
                }
                
                response = requests.put(url, headers=headers, json=data)
                
                if response.status_code == 201:
                    logger.info(f"Utworzono plik {file_path} w GitHub")
                    return True
                else:
                    error_msg = response.text
                    logger.error(f"Błąd tworzenia pliku w GitHub: {response.status_code}")
                    logger.error(f"Szczegóły: {error_msg[:500]}")
                    return False
            else:
                error_msg = response.text
                logger.error(f"Błąd sprawdzania pliku w GitHub: {response.status_code}")
                logger.error(f"Szczegóły: {error_msg[:500]}")
                return False
            
        except Exception as e:
            error_msg = str(e)
            logger.error(f"Błąd zapisu do GitHub: {e}")
            logger.error(f"Szczegóły: {error_msg}")
            return False
    
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
    
    def delete_player_predictions(self, round_id: str, player_name: str):
        """Usuwa wszystkie typy gracza dla danej rundy"""
        if round_id not in self.data['rounds']:
            logger.error(f"Runda {round_id} nie istnieje")
            return False
        
        if player_name not in self.data['players']:
            logger.error(f"Gracz {player_name} nie istnieje")
            return False
        
        # Usuń typy z rundy
        if 'predictions' in self.data['rounds'][round_id]:
            if player_name in self.data['rounds'][round_id]['predictions']:
                del self.data['rounds'][round_id]['predictions'][player_name]
        
        # Usuń typy z gracza
        if round_id in self.data['players'][player_name]['predictions']:
            del self.data['players'][player_name]['predictions'][round_id]
        
        # Usuń punkty dla tego gracza w tej rundzie
        if 'match_points' in self.data['rounds'][round_id]:
            if player_name in self.data['rounds'][round_id]['match_points']:
                del self.data['rounds'][round_id]['match_points'][player_name]
        
        self._save_data()
        self._recalculate_player_totals()
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
    
    def _is_round_finished(self, round_data: Dict) -> bool:
        """Sprawdza czy runda jest rozegrana (wszystkie mecze mają wyniki)"""
        matches = round_data.get('matches', [])
        if not matches:
            return False
        
        # Runda jest rozegrana jeśli wszystkie mecze mają wyniki
        for match in matches:
            home_goals = match.get('home_goals')
            away_goals = match.get('away_goals')
            if home_goals is None or away_goals is None:
                return False
        
        return True
    
    def _recalculate_player_totals(self):
        """Przelicza całkowite punkty dla wszystkich graczy"""
        from tipper import Tipper
        
        for player_name, player_data in self.data['players'].items():
            total_points = 0
            rounds_played = 0
            best_score = 0
            worst_score = float('inf')
            round_scores = {}  # {round_id: total_points_in_round}
            finished_round_scores = []  # Lista punktów tylko z rozegranych kolejek (dla worst_score)
            
            # Przejdź przez wszystkie rundy
            for round_id, round_data in self.data['rounds'].items():
                round_points = 0
                match_points = round_data.get('match_points', {}).get(player_name, {})
                
                # Sumuj punkty z meczów w rundzie (jeśli gracz typował)
                for match_id, points in match_points.items():
                    round_points += points
                
                # Zawsze zapisz punkty do round_scores (dla wyświetlania)
                round_scores[round_id] = round_points
                total_points += round_points
                
                # Jeśli gracz typował w tej rundzie (ma typy) lub ma punkty, to runda jest "rozegrana"
                if player_name in round_data.get('predictions', {}) or round_points > 0:
                    rounds_played += 1
                
                # WAŻNE: Uwzględnij 0 jako najgorszy wynik TYLKO dla rozegranych kolejek
                is_finished = self._is_round_finished(round_data)
                if is_finished:
                    # Dla rozegranych kolejek: jeśli gracz nie typował, ma 0 punktów
                    if round_points == 0 and player_name not in round_data.get('predictions', {}):
                        # Gracz nie typował w rozegranej kolejce - ma 0 punktów
                        finished_round_scores.append(0)
                    elif round_points > 0:
                        # Gracz typował i ma punkty
                        finished_round_scores.append(round_points)
                        best_score = max(best_score, round_points)
                
                # Aktualizuj best_score dla wszystkich rund (nie tylko rozegranych)
                if round_points > 0:
                    best_score = max(best_score, round_points)
            
            # Oblicz worst_score tylko z rozegranych kolejek
            if finished_round_scores:
                worst_score = min(finished_round_scores)
            elif round_scores:
                # Jeśli nie ma rozegranych kolejek, ale są jakieś rundy, użyj minimum z wszystkich
                worst_score = min(round_scores.values()) if round_scores.values() else 0
            
            # Aktualizuj dane gracza
            player_data['total_points'] = total_points
            player_data['rounds_played'] = rounds_played
            player_data['best_score'] = best_score if best_score > 0 else 0
            # Jeśli worst_score jest inf, oznacza to że gracz nie ma żadnych rund - ustaw 0
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
            finished_round_points = []  # Punkty tylko z rozegranych kolejek
            for round_id, round_data in all_rounds:
                round_points = round_scores.get(round_id, 0)
                round_points_list.append(round_points)
                
                # Zbierz punkty tylko z rozegranych kolejek (dla odrzucania najgorszego)
                if self._is_round_finished(round_data):
                    # Jeśli gracz nie typował w rozegranej kolejce, ma 0 punktów
                    if round_points == 0 and player_name not in round_data.get('predictions', {}):
                        finished_round_points.append(0)
                    elif round_points > 0:
                        finished_round_points.append(round_points)
            
            # Odrzuć najgorszy wynik jeśli exclude_worst=True
            # WAŻNE: Odrzucamy tylko z rozegranych kolejek
            final_total_points = total_points
            if exclude_worst and len(finished_round_points) > 1:
                # Oblicz worst_score tylko z rozegranych kolejek
                worst_from_finished = min(finished_round_points) if finished_round_points else 0
                # Odrzuć najgorszy wynik tylko jeśli jest więcej niż jedna rozegrana kolejka
                final_total_points -= worst_from_finished
                excluded_worst = True
                actual_worst_score = worst_from_finished
            else:
                excluded_worst = False
                actual_worst_score = worst_score
            
            leaderboard.append({
                'player_name': player_name,
                'total_points': final_total_points,
                'rounds_played': player_data['rounds_played'],
                'best_score': player_data.get('best_score', 0),
                'worst_score': actual_worst_score,
                'excluded_worst': excluded_worst,
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

