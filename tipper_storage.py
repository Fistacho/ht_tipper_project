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
    
    def __init__(self, data_file: str = None, season_id: str = None):
        """
        Inicjalizuje storage dla danego sezonu
        
        Args:
            data_file: Ścieżka do pliku (opcjonalne, jeśli None, używa domyślnej nazwy z sezonem)
            season_id: ID sezonu (np. "season_80", "season_81"). Jeśli None, używa "current_season"
        """
        if season_id is None:
            season_id = "current_season"
        
        self.season_id = season_id
        
        # Jeśli data_file nie jest podany, użyj domyślnej nazwy z sezonem
        if data_file is None:
            # Zawsze używaj plików sezonowych (nie używamy tipper_data.json)
            # Wyciągnij numer sezonu (np. "season_80" -> "80")
            if season_id == "current_season":
                # Dla current_season użyj najwyższego numeru sezonu z dostępnych plików
                import glob
                import re
                pattern = os.path.join(os.getcwd(), "tipper_data_season_*.json")
                files = glob.glob(pattern)
                season_nums = []
                for file_path in files:
                    filename = os.path.basename(file_path)
                    match = re.search(r'tipper_data_season_(\d+)\.json', filename)
                    if match:
                        season_nums.append(int(match.group(1)))
                if season_nums:
                    season_num = max(season_nums)
                    season_id = f"season_{season_num}"
                    self.season_id = season_id
                else:
                    # Jeśli nie ma plików sezonowych, użyj domyślnego 80
                    season_num = 80
                    season_id = f"season_{season_num}"
                    self.season_id = season_id
            else:
                season_num = season_id.replace("season_", "") if season_id.startswith("season_") else season_id
            data_file = f"tipper_data_season_{season_num}.json"
        
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
                data = github_data
            else:
                data = None
        else:
            data = None
        
        # Fallback: załaduj lokalnie (dla lokalnego rozwoju)
        if data is None:
            abs_path = os.path.abspath(self.data_file)
            
            if os.path.exists(abs_path):
                try:
                    with open(abs_path, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                        logger.info(f"Załadowano dane z pliku {abs_path}: {len(data.get('players', {}))} graczy, {len(data.get('rounds', {}))} rund")
                except (json.JSONDecodeError, IOError) as e:
                    logger.error(f"Błąd ładowania danych typera z {abs_path}: {e}")
                    data = self._get_default_data()
            else:
                logger.warning(f"Plik {abs_path} nie istnieje, używam domyślnych danych")
                data = self._get_default_data()
        
        # Migracja danych: przenieś graczy ze starej struktury do sezonu
        self._migrate_players_to_season(data)
        
        return data
    
    def _migrate_players_to_season(self, data: Dict):
        """Migruje graczy ze starej struktury (globalnej) do struktury per sezon"""
        # Sprawdź czy istnieją gracze w starej strukturze
        if 'players' in data and data['players']:
            # Znajdź sezon dla migracji
            target_season_id = self.season_id
            
            # Jeśli sezon to "current_season", spróbuj znaleźć właściwy sezon
            if target_season_id == "current_season":
                # Najpierw sprawdź czy w danych jest sezon "season_XX" (na podstawie nazwy pliku)
                # Wyciągnij numer sezonu z nazwy pliku
                import re
                filename = os.path.basename(self.data_file)
                match = re.search(r'tipper_data_season_(\d+)\.json', filename)
                if match:
                    season_num = match.group(1)
                    target_season_id = f"season_{season_num}"
                    self.season_id = target_season_id
                    logger.info(f"Zidentyfikowano sezon {target_season_id} na podstawie nazwy pliku")
                else:
                    # Sprawdź rundy - znajdź sezon z największą liczbą rund
                    season_rounds_count = {}
                    for round_id, round_data in data.get('rounds', {}).items():
                        round_season = round_data.get('season_id', 'current_season')
                        season_rounds_count[round_season] = season_rounds_count.get(round_season, 0) + 1
                    
                    if season_rounds_count:
                        # Wybierz sezon z największą liczbą rund
                        target_season_id = max(season_rounds_count.items(), key=lambda x: x[1])[0]
                        self.season_id = target_season_id
                        logger.info(f"Zidentyfikowano sezon {target_season_id} na podstawie rund")
            
            # Jeśli w danych jest "current_season", zamień na właściwy sezon
            if 'current_season' in data.get('seasons', {}) and target_season_id != 'current_season':
                # Przenieś dane z current_season do właściwego sezonu
                if target_season_id not in data.get('seasons', {}):
                    data['seasons'][target_season_id] = data['seasons']['current_season'].copy()
                else:
                    # Scal dane (zachowaj istniejące, dodaj brakujące)
                    current_season_data = data['seasons']['current_season']
                    for key in ['rounds', 'selected_teams', 'selected_leagues']:
                        if key in current_season_data and key not in data['seasons'][target_season_id]:
                            data['seasons'][target_season_id][key] = current_season_data[key]
                        elif key in current_season_data:
                            # Scal listy (bez duplikatów)
                            if isinstance(current_season_data[key], list):
                                existing = set(data['seasons'][target_season_id].get(key, []))
                                new_items = [item for item in current_season_data[key] if item not in existing]
                                data['seasons'][target_season_id][key].extend(new_items)
            
            # Upewnij się, że sezon istnieje w danych
            if target_season_id not in data.get('seasons', {}):
                data['seasons'][target_season_id] = {
                    'league_id': None,
                    'rounds': [],
                    'start_date': None,
                    'end_date': None,
                    'selected_teams': [],
                    'selected_leagues': [],
                    'players': {}
                }
            
            # Jeśli sezon nie ma graczy, przenieś ich ze starej struktury
            if 'players' not in data['seasons'][target_season_id] or not data['seasons'][target_season_id].get('players'):
                data['seasons'][target_season_id]['players'] = data['players'].copy()
                logger.info(f"Zmigrowano {len(data['players'])} graczy do sezonu {target_season_id}")
            
            # Przenieś selected_teams z settings do sezonu (jeśli nie ma w sezonie)
            if 'settings' in data and 'selected_teams' in data['settings']:
                if 'selected_teams' not in data['seasons'][target_season_id] or not data['seasons'][target_season_id].get('selected_teams'):
                    data['seasons'][target_season_id]['selected_teams'] = data['settings']['selected_teams'].copy()
                    logger.info(f"Zmigrowano {len(data['settings']['selected_teams'])} drużyn do sezonu {target_season_id}")
            
            # Przenieś selected_leagues z settings do sezonu (jeśli istnieją w settings)
            if 'settings' in data and 'selected_leagues' in data['settings']:
                if 'selected_leagues' not in data['seasons'][target_season_id] or not data['seasons'][target_season_id].get('selected_leagues'):
                    data['seasons'][target_season_id]['selected_leagues'] = data['settings']['selected_leagues'].copy()
                    logger.info(f"Zmigrowano {len(data['settings']['selected_leagues'])} lig do sezonu {target_season_id}")
            
            # Zaktualizuj season_id w rundach, jeśli jest "current_season"
            for round_id, round_data in data.get('rounds', {}).items():
                if round_data.get('season_id') == 'current_season':
                    round_data['season_id'] = target_season_id
            
            # Opcjonalnie: usuń starą strukturę (lub zostaw dla kompatybilności)
            # data.pop('players', None)
    
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
            'rounds': {},  # {round_id: {matches: [], start_date: ..., end_date: ...}}
            'seasons': {},  # {season_id: {rounds: [], start_date: ..., end_date: ..., players: {}, ...}}
            'leagues': {},  # {league_id: {name: ..., seasons: []}}
            'settings': {  # Ustawienia typera (kompatybilność wsteczna)
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
                'end_date': end_date,
                'selected_teams': [],
                'selected_leagues': [],
                'archived': False
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
                'end_date': None,
                'selected_teams': [],
                'selected_leagues': [],
                'archived': False
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
    
    def _get_season_players(self, season_id: str = None) -> Dict:
        """Zwraca słownik graczy dla danego sezonu"""
        if season_id is None:
            season_id = self.season_id
        
        if season_id not in self.data.get('seasons', {}):
            self.data['seasons'][season_id] = {
                'league_id': None,
                'rounds': [],
                'start_date': None,
                'end_date': None,
                'selected_teams': [],
                'selected_leagues': [],
                'players': {}
            }
        
        if 'players' not in self.data['seasons'][season_id]:
            self.data['seasons'][season_id]['players'] = {}
        
        # Kompatybilność wsteczna: jeśli sezon nie ma graczy, sprawdź starą strukturę
        if not self.data['seasons'][season_id]['players'] and 'players' in self.data and self.data['players']:
            # Przenieś graczy ze starej struktury
            self.data['seasons'][season_id]['players'] = self.data['players'].copy()
            logger.info(f"Przeniesiono {len(self.data['players'])} graczy ze starej struktury do sezonu {season_id}")
            self._save_data()  # Zapisz migrację
        
        return self.data['seasons'][season_id]['players']
    
    def add_prediction(self, round_id: str, player_name: str, match_id: str, prediction: tuple):
        """Dodaje lub aktualizuje typ gracza dla meczu (tylko jeden typ na gracza i mecz)"""
        if round_id not in self.data['rounds']:
            logger.error(f"Runda {round_id} nie istnieje")
            return False
        
        # Pobierz sezon z rundy
        round_data = self.data['rounds'][round_id]
        season_id = round_data.get('season_id', self.season_id)
        
        # Pobierz graczy dla sezonu
        players = self._get_season_players(season_id)
        
        if player_name not in players:
            players[player_name] = {
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
        
        # Dodaj lub aktualizuj typ do gracza (w sezonie)
        if round_id not in players[player_name]['predictions']:
            players[player_name]['predictions'][round_id] = {}
        
        # Nadpisz istniejący typ (lub dodaj nowy)
        players[player_name]['predictions'][round_id][match_id] = {
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
                        
                        # Przelicz całkowite punkty gracza (dla sezonu)
                        self._recalculate_player_totals(season_id=season_id)
                    break
        
        self._save_data()
        return True
    
    def delete_player_predictions(self, round_id: str, player_name: str):
        """Usuwa wszystkie typy gracza dla danej rundy"""
        if round_id not in self.data['rounds']:
            logger.error(f"Runda {round_id} nie istnieje")
            return False
        
        # Pobierz sezon z rundy
        round_data = self.data['rounds'][round_id]
        season_id = round_data.get('season_id', self.season_id)
        
        # Pobierz graczy dla sezonu
        players = self._get_season_players(season_id)
        
        if player_name not in players:
            logger.error(f"Gracz {player_name} nie istnieje w sezonie {season_id}")
            return False
        
        # Usuń typy z rundy
        if 'predictions' in self.data['rounds'][round_id]:
            if player_name in self.data['rounds'][round_id]['predictions']:
                del self.data['rounds'][round_id]['predictions'][player_name]
        
        # Usuń typy z gracza (w sezonie)
        if round_id in players[player_name]['predictions']:
            del players[player_name]['predictions'][round_id]
        
        # Usuń punkty dla tego gracza w tej rundzie
        if 'match_points' in self.data['rounds'][round_id]:
            if player_name in self.data['rounds'][round_id]['match_points']:
                del self.data['rounds'][round_id]['match_points'][player_name]
        
        self._save_data()
        self._recalculate_player_totals(season_id=season_id)
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
        
        # Pobierz sezon z rundy
        round_data = self.data['rounds'][round_id]
        season_id = round_data.get('season_id', self.season_id)
        
        # Pobierz graczy dla sezonu
        players = self._get_season_players(season_id)
        
        # Przelicz punkty dla wszystkich graczy
        from tipper import Tipper
        predictions = self.data['rounds'][round_id].get('predictions', {})
        
        for player_name, player_predictions in predictions.items():
            if match_id in player_predictions:
                pred = player_predictions[match_id]
                prediction_tuple = (pred['home'], pred['away'])
                points = Tipper.calculate_points(prediction_tuple, (home_goals, away_goals))
                
                # Aktualizuj punkty gracza (w sezonie)
                if player_name not in players:
                    players[player_name] = {
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
        self._recalculate_player_totals(season_id=season_id)
    
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
    
    def _recalculate_player_totals(self, season_id: str = None):
        """Przelicza całkowite punkty dla wszystkich graczy w danym sezonie"""
        if season_id is None:
            season_id = self.season_id
        
        from tipper import Tipper
        
        # Pobierz graczy dla sezonu
        players = self._get_season_players(season_id)
        
        # Filtruj rundy tylko dla tego sezonu
        season_rounds = {}
        for round_id, round_data in self.data['rounds'].items():
            if round_data.get('season_id') == season_id:
                season_rounds[round_id] = round_data
        
        for player_name, player_data in players.items():
            total_points = 0
            rounds_played = 0
            best_score = 0
            worst_score = float('inf')
            round_scores = {}  # {round_id: total_points_in_round}
            finished_round_scores = []  # Lista punktów tylko z rozegranych kolejek (dla worst_score)
            
            # Przejdź przez wszystkie rundy w sezonie
            for round_id, round_data in season_rounds.items():
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
    
    def get_player_predictions(self, player_name: str, round_id: str = None, season_id: str = None) -> Dict:
        """Zwraca typy gracza dla danego sezonu"""
        if season_id is None:
            season_id = self.season_id
        
        # Pobierz graczy dla sezonu
        players = self._get_season_players(season_id)
        
        if player_name not in players:
            return {}
        
        if round_id:
            return players[player_name]['predictions'].get(round_id, {})
        else:
            return players[player_name]['predictions']
    
    def get_leaderboard(self, exclude_worst: bool = True, season_id: str = None) -> List[Dict]:
        """Zwraca ranking graczy dla danego sezonu (z opcją odrzucenia najgorszego wyniku)"""
        if season_id is None:
            season_id = self.season_id
        
        leaderboard = []
        
        # Pobierz graczy dla sezonu
        players = self._get_season_players(season_id)
        
        # Filtruj rundy tylko dla tego sezonu
        season_rounds = {}
        for round_id, round_data in self.data['rounds'].items():
            if round_data.get('season_id') == season_id:
                season_rounds[round_id] = round_data
        
        # Pobierz wszystkie rundy sezonu posortowane po dacie (najstarsza pierwsza)
        all_rounds = sorted(season_rounds.items(), key=lambda x: x[1].get('start_date', ''))
        
        for player_name, player_data in players.items():
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
        
        # Pobierz sezon z rundy
        season_id = round_data.get('season_id', self.season_id)
        
        # Pobierz graczy dla sezonu
        players = self._get_season_players(season_id)
        
        # Pobierz wszystkich graczy z sezonu
        all_players = set(players.keys())
        
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
                # Upewnij się, że match_id jest stringiem dla zgodności z matches_map
                # Konwertuj wszystkie klucze na stringi dla spójności
                player_match_points = match_points[player_name]
                sorted_match_ids = sorted(player_match_points.keys(), 
                                         key=lambda mid: matches_map.get(str(mid), {}).get('match_date', ''))
                
                for match_id in sorted_match_ids:
                    # Użyj oryginalnego klucza (może być string lub int) do dostępu do danych
                    points = player_match_points[match_id]
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
    
    def get_selected_teams(self, season_id: str = None) -> List[str]:
        """Zwraca listę wybranych drużyn do typowania dla danego sezonu"""
        if season_id is None:
            season_id = self.season_id
        
        # Sprawdź czy sezon istnieje i ma zapisane drużyny
        if season_id in self.data.get('seasons', {}):
            if 'selected_teams' in self.data['seasons'][season_id]:
                return self.data['seasons'][season_id]['selected_teams']
        
        # Fallback: sprawdź stare ustawienia (kompatybilność wsteczna)
        if 'settings' in self.data and 'selected_teams' in self.data['settings']:
            return self.data['settings'].get('selected_teams', [])
        
        return []
    
    def set_selected_teams(self, team_names: List[str], season_id: str = None):
        """Zapisuje listę wybranych drużyn do typowania dla danego sezonu"""
        if season_id is None:
            season_id = self.season_id
        
        # Upewnij się, że sezon istnieje
        if season_id not in self.data.get('seasons', {}):
            self.data['seasons'][season_id] = {
                'league_id': None,
                'rounds': [],
                'start_date': None,
                'end_date': None,
                'selected_teams': []
            }
        
        # Zapisz wybór drużyn dla sezonu
        self.data['seasons'][season_id]['selected_teams'] = team_names
        self._save_data()
    
    def get_selected_leagues(self, season_id: str = None) -> List[int]:
        """Zwraca listę wybranych lig do typowania dla danego sezonu"""
        if season_id is None:
            season_id = self.season_id
        
        # Sprawdź czy sezon istnieje i ma zapisane ligi
        if season_id in self.data.get('seasons', {}):
            if 'selected_leagues' in self.data['seasons'][season_id]:
                return self.data['seasons'][season_id]['selected_leagues']
        
        # Fallback: sprawdź stare ustawienia (kompatybilność wsteczna)
        if 'settings' in self.data and 'selected_leagues' in self.data['settings']:
            return self.data['settings'].get('selected_leagues', [])
        
        return []
    
    def set_selected_leagues(self, league_ids: List[int], season_id: str = None):
        """Zapisuje listę wybranych lig do typowania dla danego sezonu"""
        if season_id is None:
            season_id = self.season_id
        
        # Upewnij się, że sezon istnieje
        if season_id not in self.data.get('seasons', {}):
            self.data['seasons'][season_id] = {
                'league_id': None,
                'rounds': [],
                'start_date': None,
                'end_date': None,
                'selected_teams': [],
                'selected_leagues': []
            }
        
        # Zapisz wybór lig dla sezonu
        self.data['seasons'][season_id]['selected_leagues'] = league_ids
        self._save_data()
    
    def is_season_archived(self, season_id: str = None) -> bool:
        """Sprawdza czy sezon jest oznaczony jako archiwalny"""
        if season_id is None:
            season_id = self.season_id
        
        # Upewnij się, że sezon istnieje
        if season_id not in self.data.get('seasons', {}):
            return False
        
        # Zwróć wartość archived (domyślnie False jeśli nie istnieje)
        return self.data['seasons'][season_id].get('archived', False)
    
    def set_season_archived(self, archived: bool, season_id: str = None):
        """Oznacza sezon jako archiwalny lub niearchiwalny"""
        if season_id is None:
            season_id = self.season_id
        
        # Upewnij się, że sezon istnieje
        if season_id not in self.data.get('seasons', {}):
            self.data['seasons'][season_id] = {
                'league_id': None,
                'rounds': [],
                'start_date': None,
                'end_date': None,
                'selected_teams': [],
                'selected_leagues': [],
                'players': {}
            }
        
        # Ustaw status archiwalny
        self.data['seasons'][season_id]['archived'] = archived
        self._save_data()
    
    def add_player(self, player_name: str, season_id: str = None):
        """Dodaje gracza do sezonu"""
        if season_id is None:
            season_id = self.season_id
        
        # Pobierz graczy dla sezonu
        players = self._get_season_players(season_id)
        
        if player_name in players:
            return False  # Gracz już istnieje
        
        players[player_name] = {
            'predictions': {},
            'total_points': 0,
            'rounds_played': 0,
            'best_score': 0,
            'worst_score': float('inf')
        }
        
        self._save_data()
        return True
    
    def remove_player(self, player_name: str, season_id: str = None):
        """Usuwa gracza z sezonu (i wszystkie jego typy)"""
        if season_id is None:
            season_id = self.season_id
        
        # Pobierz graczy dla sezonu
        players = self._get_season_players(season_id)
        
        if player_name not in players:
            return False  # Gracz nie istnieje
        
        # Usuń wszystkie typy gracza ze wszystkich rund sezonu
        for round_id, round_data in self.data['rounds'].items():
            if round_data.get('season_id') == season_id:
                # Usuń typy z rundy
                if 'predictions' in round_data:
                    if player_name in round_data['predictions']:
                        del round_data['predictions'][player_name]
                
                # Usuń punkty z rundy
                if 'match_points' in round_data:
                    if player_name in round_data['match_points']:
                        del round_data['match_points'][player_name]
        
        # Usuń gracza z sezonu
        del players[player_name]
        
        self._save_data()
        self._recalculate_player_totals(season_id=season_id)
        return True
    
    def get_season_players_list(self, season_id: str = None) -> List[str]:
        """Zwraca listę graczy dla danego sezonu"""
        if season_id is None:
            season_id = self.season_id
        
        players = self._get_season_players(season_id)
        return sorted(list(players.keys()))
    
    def create_new_season(self, season_num: int) -> bool:
        """Tworzy nowy sezon z pustym plikiem JSON"""
        season_id = f"season_{season_num}"
        data_file = f"tipper_data_season_{season_num}.json"
        
        # Sprawdź czy plik już istnieje
        abs_path = os.path.abspath(data_file)
        if os.path.exists(abs_path):
            return False  # Sezon już istnieje
        
        # Utwórz nową strukturę danych dla sezonu
        new_data = self._get_default_data()
        new_data['seasons'][season_id] = {
            'league_id': None,
            'rounds': [],
            'start_date': None,
            'end_date': None,
            'selected_teams': [],
            'selected_leagues': [],
            'players': {},
            'archived': False
        }
        
        # Zapisz do pliku
        try:
            with open(abs_path, 'w', encoding='utf-8') as f:
                json.dump(new_data, f, ensure_ascii=False, indent=2)
            logger.info(f"Utworzono nowy sezon {season_id} w pliku {abs_path}")
            return True
        except Exception as e:
            logger.error(f"Błąd tworzenia nowego sezonu: {e}")
            return False

