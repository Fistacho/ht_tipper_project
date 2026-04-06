"""
Moduł przechowywania danych typera
"""
import json
import os
import glob
import re
import hashlib
import time
from typing import Dict, List, Optional, Tuple
from datetime import datetime
import logging
from functools import lru_cache

logger = logging.getLogger(__name__)

# Ścieżka do pliku z danymi typera
TIPPER_DATA_FILE = "tipper_data.json"
DEFAULT_GITHUB_BACKUP_INTERVAL_SECONDS = 3600


def default_exclude_worst_rule(season_id: str) -> bool:
    """Domyślna reguła sezonu, jeśli ustawienie nie zostało zapisane w danych."""
    if not season_id or not str(season_id).startswith("season_"):
        return True

    try:
        season_num = int(str(season_id).replace("season_", ""))
    except ValueError:
        return True

    return season_num < 82


def season_uses_worst_score_rule(season_id: str, season_data: Optional[Dict] = None) -> bool:
    """Zwraca regułę odrzucania najgorszego wyniku dla sezonu."""
    if season_data and 'exclude_worst_rule' in season_data:
        return bool(season_data.get('exclude_worst_rule'))

    return default_exclude_worst_rule(season_id)


def get_season_file_signatures(base_dir: str = None) -> tuple:
    """Zwraca sygnatury plików sezonów do cache'owania obliczeń."""
    search_dir = base_dir or os.getcwd()
    pattern = os.path.join(search_dir, "tipper_data_season_*.json")
    season_files = []

    for file_path in glob.glob(pattern):
        filename = os.path.basename(file_path)
        match = re.search(r'tipper_data_season_(\d+)\.json', filename)
        if not match:
            continue

        season_num = int(match.group(1))
        season_files.append((season_num, os.path.abspath(file_path), os.path.getmtime(file_path)))

    season_files.sort(key=lambda item: item[0], reverse=True)
    return tuple((file_path, mtime) for _, file_path, mtime in season_files)


@lru_cache(maxsize=16)
def get_cached_all_time_leaderboard(file_signatures: tuple, exclude_worst: bool = False) -> List[Dict]:
    """Oblicza ranking wszechczasów z cache zależnym od zmian plików sezonów."""
    players_total = {}

    for file_path, _mtime in file_signatures:
        try:
            filename = os.path.basename(file_path)
            match = re.search(r'tipper_data_season_(\d+)\.json', filename)
            if not match:
                continue

            season_num = int(match.group(1))
            season_id = f"season_{season_num}"

            with open(file_path, 'r', encoding='utf-8') as file_handle:
                data = json.load(file_handle)

            players_data = {}
            season_data = data.get('seasons', {}).get(season_id, {})
            if season_id in data.get('seasons', {}):
                if 'players' in season_data and season_data['players']:
                    players_data = season_data['players']

            if not players_data and 'players' in data and data['players']:
                players_data = data['players']

            for player_name, player_data in players_data.items():
                if player_name not in players_total:
                    players_total[player_name] = {
                        'total': 0,
                        'team_name': '',
                        'seasons': 0,
                        'rounds': 0,
                        'seasons_data': {}
                    }

                team_name = str(player_data.get('team_name', '') or '').strip()
                if team_name and not players_total[player_name]['team_name']:
                    players_total[player_name]['team_name'] = team_name

                total_points = player_data.get('total_points', 0)
                worst_score = player_data.get('worst_score', 0)
                rounds_played = player_data.get('rounds_played', 0)

                if exclude_worst and season_uses_worst_score_rule(season_id, season_data) and worst_score > 0:
                    season_points = total_points - worst_score
                else:
                    season_points = total_points

                players_total[player_name]['total'] += season_points
                players_total[player_name]['seasons'] += 1
                players_total[player_name]['rounds'] += rounds_played
                players_total[player_name]['seasons_data'][season_id] = season_points

        except Exception as error:
            logger.error(f"Błąd przetwarzania pliku {file_path}: {error}")
            continue

    leaderboard = []
    for player_name, data in players_total.items():
        leaderboard.append({
            'player_name': player_name,
            'team_name': data.get('team_name', ''),
            'total_points': data['total'],
            'seasons_played': data['seasons'],
            'rounds_played': data['rounds'],
            'seasons_data': data['seasons_data']
        })

    leaderboard.sort(key=lambda item: item['total_points'], reverse=True)
    return leaderboard


class TipperStorage:
    """Klasa do przechowywania i zarządzania danymi typera"""

    @staticmethod
    def _build_player_entry(team_name: str = "") -> Dict:
        """Tworzy domyślną strukturę danych gracza."""
        normalized_team_name = (team_name or "").strip()
        player_entry = {
            'predictions': {},
            'total_points': 0,
            'rounds_played': 0,
            'best_score': 0,
            'worst_score': float('inf')
        }

        if normalized_team_name:
            player_entry['team_name'] = normalized_team_name

        return player_entry
    
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
        self.sync_meta_file = f"{self.data_file}.sync.json"
        self.github_config = self._get_github_config()
        self._github_backup_interval_seconds = int(
            os.getenv('TIPPER_GITHUB_BACKUP_INTERVAL_SECONDS', str(DEFAULT_GITHUB_BACKUP_INTERVAL_SECONDS))
        )
        self._pending_save = False
        self._last_save_time = 0
        self._save_delay = 2.0  # 2 sekundy opóźnienia
        self._last_github_backup_time = 0.0
        self._last_github_backup_hash = ""
        self._has_unsynced_changes = False
        self.data = self._load_data()
        self._initialize_sync_state()
    
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
    
    def _load_data(self, prefer_github: bool = False) -> Dict:
        """Ładuje dane z pliku JSON, preferując lokalny stan aplikacji."""
        data, source = self._load_data_with_source(prefer_github=prefer_github)

        if data is None:
            abs_path = os.path.abspath(self.data_file)
            logger.warning(f"Brak danych w źródłach dla {abs_path}, używam domyślnych danych")
            data = self._get_default_data()
            source = 'default'
        
        # Migracja danych: przenieś graczy ze starej struktury do sezonu
        self._migrate_players_to_season(data)

        if source == 'github':
            self._write_local_data(data)
            self._mark_github_backup_success(self._calculate_data_hash(data), backup_time=time.time())
        
        return data

    def _load_data_with_source(self, prefer_github: bool = False) -> Tuple[Optional[Dict], Optional[str]]:
        """Ładuje dane wraz z informacją o źródle odczytu."""
        load_order = []
        if prefer_github and self.github_config:
            load_order.append('github')
        load_order.append('local')
        if not prefer_github and self.github_config:
            load_order.append('github')

        for source in load_order:
            if source == 'local':
                local_data = self._load_from_local_file()
                if local_data is not None:
                    return local_data, 'local'
            elif source == 'github':
                github_data = self._load_from_github()
                if github_data is not None:
                    logger.info(
                        f"✅ Załadowano dane z GitHub: {len(github_data.get('players', {}))} graczy, {len(github_data.get('rounds', {}))} rund"
                    )
                    return github_data, 'github'

        return None, None

    def _load_from_local_file(self) -> Optional[Dict]:
        """Ładuje dane z lokalnego pliku roboczego."""
        abs_path = os.path.abspath(self.data_file)

        if not os.path.exists(abs_path):
            logger.warning(f"Plik {abs_path} nie istnieje")
            return None

        try:
            with open(abs_path, 'r', encoding='utf-8') as file_handle:
                data = json.load(file_handle)
            logger.info(
                f"Załadowano dane z pliku {abs_path}: {len(data.get('players', {}))} graczy, {len(data.get('rounds', {}))} rund"
            )
            return data
        except (json.JSONDecodeError, IOError) as error:
            logger.error(f"Błąd ładowania danych typera z {abs_path}: {error}")
            return None

    def _serialize_data(self, data: Optional[Dict] = None) -> str:
        """Serializuje dane do stabilnej postaci JSON."""
        return json.dumps(data if data is not None else self.data, ensure_ascii=False, indent=2)

    def _calculate_data_hash(self, data: Optional[Dict] = None) -> str:
        """Oblicza hash bieżącego stanu danych do śledzenia synchronizacji."""
        json_content = self._serialize_data(data)
        return hashlib.sha256(json_content.encode('utf-8')).hexdigest()

    def _write_local_data(self, data: Optional[Dict] = None):
        """Zapisuje dane do lokalnego pliku roboczego."""
        abs_path = os.path.abspath(self.data_file)
        json_content = self._serialize_data(data)

        logger.info(f"_write_local_data: Zapisuję lokalnie do pliku {abs_path}")

        with open(abs_path, 'w', encoding='utf-8') as file_handle:
            file_handle.write(json_content)

        if os.path.exists(abs_path):
            file_size = os.path.getsize(abs_path)
            logger.debug(f"Plik zapisany poprawnie, rozmiar: {file_size} bajtów")
        else:
            logger.warning(f"Plik {abs_path} nie istnieje po zapisie (może być normalne na Streamlit Cloud)")

    def _load_sync_metadata(self) -> Dict:
        """Ładuje metadane ostatniej synchronizacji z GitHub."""
        if not os.path.exists(self.sync_meta_file):
            return {}

        try:
            with open(self.sync_meta_file, 'r', encoding='utf-8') as file_handle:
                metadata = json.load(file_handle)
            return metadata if isinstance(metadata, dict) else {}
        except (json.JSONDecodeError, IOError) as error:
            logger.warning(f"Nie udało się załadować metadanych synchronizacji {self.sync_meta_file}: {error}")
            return {}

    def _write_sync_metadata(self):
        """Zapisuje metadane ostatniej synchronizacji z GitHub."""
        metadata = {
            'last_github_backup_time': self._last_github_backup_time,
            'last_github_backup_hash': self._last_github_backup_hash,
        }

        try:
            with open(self.sync_meta_file, 'w', encoding='utf-8') as file_handle:
                json.dump(metadata, file_handle, ensure_ascii=False, indent=2)
        except IOError as error:
            logger.warning(f"Nie udało się zapisać metadanych synchronizacji {self.sync_meta_file}: {error}")

    def _mark_github_backup_success(self, data_hash: str, backup_time: Optional[float] = None):
        """Aktualizuje stan po udanym backupie do GitHub."""
        self._last_github_backup_hash = data_hash
        self._last_github_backup_time = backup_time if backup_time is not None else time.time()
        self._has_unsynced_changes = False
        self._write_sync_metadata()

    def _initialize_sync_state(self):
        """Ustawia stan synchronizacji po załadowaniu danych."""
        current_hash = self._calculate_data_hash()
        metadata = self._load_sync_metadata()
        self._last_github_backup_time = float(metadata.get('last_github_backup_time', 0) or 0)
        self._last_github_backup_hash = str(metadata.get('last_github_backup_hash', '') or '')

        if not self.github_config:
            self._has_unsynced_changes = False
            return

        if not self._last_github_backup_hash:
            if os.path.exists(self.data_file):
                self._last_github_backup_time = max(
                    self._last_github_backup_time,
                    os.path.getmtime(self.data_file)
                )
            self._has_unsynced_changes = True
            return

        self._has_unsynced_changes = current_hash != self._last_github_backup_hash

    def _should_run_periodic_github_backup(self) -> bool:
        """Określa, czy należy wykonać okresowy backup do GitHub."""
        if not self.github_config or not self._has_unsynced_changes:
            return False

        return (time.time() - self._last_github_backup_time) >= self._github_backup_interval_seconds

    def maybe_backup_to_github(self) -> bool:
        """Wykonuje okresowy backup do GitHub, jeśli lokalny stan nie jest jeszcze zsynchronizowany."""
        if not self._should_run_periodic_github_backup():
            return False

        logger.info("maybe_backup_to_github: Uruchamiam okresowy backup zaległych zmian do GitHub")
        return self._backup_local_state_to_github(reason='periodic')

    def _backup_local_state_to_github(self, reason: str = 'manual') -> bool:
        """Wysyła aktualny lokalny stan do GitHub jako backup."""
        if not self.github_config:
            return False

        current_hash = self._calculate_data_hash()
        if not self._has_unsynced_changes and reason != 'manual':
            return False

        if self._save_to_github():
            self._mark_github_backup_success(current_hash)
            logger.info(f"Backup do GitHub zakończony powodzeniem ({reason})")
            return True

        logger.warning(f"Backup do GitHub nie powiódł się ({reason})")
        return False
    
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
                    for key in ['rounds', 'selected_teams', 'selected_leagues', 'selected_players']:
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
                    'selected_players': [],
                    'team_metadata': {},
                    'exclude_worst_rule': default_exclude_worst_rule(target_season_id),
                    'players': {}
                }

            if 'exclude_worst_rule' not in data['seasons'][target_season_id]:
                data['seasons'][target_season_id]['exclude_worst_rule'] = default_exclude_worst_rule(target_season_id)
            if 'selected_players' not in data['seasons'][target_season_id]:
                data['seasons'][target_season_id]['selected_players'] = []
            
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
    
    def reload_data(self, prefer_github: bool = False):
        """Przeładowuje dane z pliku; domyślnie z lokalnego stanu aplikacji."""
        self.data = self._load_data(prefer_github=prefer_github)
        self._initialize_sync_state()
        logger.info("Przeładowano dane z pliku")
    
    def _get_default_data(self) -> Dict:
        """Zwraca domyślną strukturę danych"""
        return {
            'rounds': {},  # {round_id: {matches: [], start_date: ..., end_date: ...}}
            'seasons': {},  # {season_id: {rounds: [], start_date: ..., end_date: ..., players: {}, ...}}
            'leagues': {},  # {league_id: {name: ..., seasons: []}}
            'settings': {  # Ustawienia typera (kompatybilność wsteczna)
                'selected_teams': [],  # Lista nazw drużyn do typowania
                'selected_players': []  # Lista wybranych graczy
            }
        }
    
    def _save_data(self, force: bool = False):
        """
        Zapisuje dane do pliku JSON - lokalnie lub przez GitHub API
        Używa mechanizmu debounce - zapisuje dopiero po 2 sekundach bez zmian
        (lub natychmiast jeśli force=True)
        """
        current_time = time.time()
        self._has_unsynced_changes = True
        
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
        try:
            self._write_local_data()

            # Loguj szczegóły zapisu
            rounds_count = len(self.data.get('rounds', {}))
            total_predictions = 0
            for round_id, round_data in self.data.get('rounds', {}).items():
                predictions = round_data.get('predictions', {})
                for player_name, player_predictions in predictions.items():
                    total_predictions += len(player_predictions)
                    logger.info(f"_do_save: Runda {round_id}, gracz {player_name}: {len(player_predictions)} typów, match_ids: {list(player_predictions.keys())[:5]}")
            
            logger.info(f"_do_save: Zapisano dane do pliku {self.data_file}: {rounds_count} rund, {total_predictions} typów")
            logger.info(f"_do_save: Szczegóły: {len(self.data.get('seasons', {}))} sezonów")

            if self._should_run_periodic_github_backup():
                self._backup_local_state_to_github(reason='periodic')
                
        except IOError as e:
            logger.error(f"Błąd zapisywania danych typera: {e}")
    
    def flush_save(self):
        """Wymusza natychmiastowy zapis wszystkich oczekujących zmian"""
        # Zawsze zapisz, nawet jeśli nie ma pending_save (może być opóźnienie w debounce)
        self._pending_save = False
        self._last_save_time = time.time()
        self._has_unsynced_changes = True
        
        # Loguj przed zapisem - sprawdź ile typów jest w każdej rundzie
        logger.info(f"flush_save: Zapisuję do pliku {self.data_file}")
        logger.info(f"flush_save: Absolutna ścieżka: {os.path.abspath(self.data_file)}")
        for round_id, round_data in self.data.get('rounds', {}).items():
            predictions = round_data.get('predictions', {})
            for player_name, player_predictions in predictions.items():
                logger.info(f"flush_save: Runda {round_id}, gracz {player_name}: {len(player_predictions)} typów, match_ids: {list(player_predictions.keys())}")
        
        self._do_save()
        if self.github_config and self._has_unsynced_changes:
            self._backup_local_state_to_github(reason='manual')
        logger.info("flush_save: Wymuszono natychmiastowy zapis danych")
        
        # Sprawdź czy plik został zapisany
        if os.path.exists(self.data_file):
            file_size = os.path.getsize(self.data_file)
            logger.info(f"flush_save: Plik zapisany, rozmiar: {file_size} bajtów")
        else:
            logger.error(f"flush_save: BŁĄD - plik {self.data_file} nie istnieje po zapisie!")
    
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
                    logger.info(f"✅ Zaktualizowano plik {file_path} w GitHub (repo: {self.github_config['repo_owner']}/{self.github_config['repo_name']})")
                    logger.info("📦 Dane zapisane do repozytorium GitHub, nie lokalnie. Pobierz z GitHub aby zobaczyć zmiany.")
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
                    logger.info(f"✅ Utworzono plik {file_path} w GitHub (repo: {self.github_config['repo_owner']}/{self.github_config['repo_name']})")
                    logger.info("📦 Dane zapisane do repozytorium GitHub, nie lokalnie. Pobierz z GitHub aby zobaczyć zmiany.")
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
        league_key = str(league_id)
        if league_key not in self.data['leagues']:
            self.data['leagues'][str(league_id)] = {
                'name': league_name or f"Liga {league_id}",
                'seasons': []
            }
            self._save_data()
        elif league_name and self.data['leagues'][league_key].get('name') != league_name:
            self.data['leagues'][league_key]['name'] = league_name
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
                'selected_players': [],
                'team_metadata': {},
                'exclude_worst_rule': default_exclude_worst_rule(season_id),
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
                'selected_players': [],
                'team_metadata': {},
                'exclude_worst_rule': default_exclude_worst_rule(season_id),
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
            # Nowa runda musi być zapisana natychmiast, bo kolejne reruny używają reload_data().
            self._save_data(force=True)
    
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
                'selected_players': [],
                'team_metadata': {},
                'exclude_worst_rule': default_exclude_worst_rule(season_id),
                'players': {}
            }
        
        if 'players' not in self.data['seasons'][season_id]:
            self.data['seasons'][season_id]['players'] = {}
        
        return self.data['seasons'][season_id]['players']
    
    def add_prediction(
        self,
        round_id: str,
        player_name: str,
        match_id: str,
        prediction: tuple,
        recalculate_totals: bool = True
    ):
        """Dodaje lub aktualizuje typ gracza dla meczu (tylko jeden typ na gracza i mecz)."""
        if round_id not in self.data['rounds']:
            logger.error(f"Runda {round_id} nie istnieje")
            return False
        
        # Pobierz sezon z rundy
        round_data = self.data['rounds'][round_id]
        season_id = round_data.get('season_id', self.season_id)
        
        # Pobierz graczy dla sezonu
        players = self._get_season_players(season_id)
        
        if player_name not in players:
            players[player_name] = self._build_player_entry()
        
        # Dodaj lub aktualizuj typ do rundy
        if 'predictions' not in self.data['rounds'][round_id]:
            self.data['rounds'][round_id]['predictions'] = {}
        
        if player_name not in self.data['rounds'][round_id]['predictions']:
            self.data['rounds'][round_id]['predictions'][player_name] = {}
        
        # Użyj string jako klucz dla spójności
        match_id_str = str(match_id)
        
        # Nadpisz istniejący typ (lub dodaj nowy)
        self.data['rounds'][round_id]['predictions'][player_name][match_id_str] = {
            'home': prediction[0],
            'away': prediction[1],
            'timestamp': datetime.now().isoformat()
        }
        logger.info(f"add_prediction: Zapisano typ {prediction} dla gracza {player_name}, mecz {match_id_str}, runda {round_id}")
        logger.info(f"add_prediction: Łącznie typów w rundzie dla {player_name}: {len(self.data['rounds'][round_id]['predictions'][player_name])}, match_ids: {list(self.data['rounds'][round_id]['predictions'][player_name].keys())}")
        
        # Dodaj lub aktualizuj typ do gracza (w sezonie)
        if round_id not in players[player_name]['predictions']:
            players[player_name]['predictions'][round_id] = {}
        
        # Nadpisz istniejący typ (lub dodaj nowy)
        players[player_name]['predictions'][round_id][match_id_str] = {
            'home': prediction[0],
            'away': prediction[1],
            'timestamp': datetime.now().isoformat()
        }
        logger.info(f"add_prediction: Zapisano typ do struktury gracza, łącznie typów w rundzie: {len(self.data['rounds'][round_id]['predictions'][player_name])}")
        
        # Sprawdź czy mecz jest rozegrany i przelicz punkty (zarówno dla nowych jak i zaktualizowanych typów)
        matches = self.data['rounds'][round_id].get('matches', [])
        for match in matches:
            if str(match.get('match_id')) == match_id_str:
                home_goals = match.get('home_goals')
                away_goals = match.get('away_goals')
                if home_goals is not None and away_goals is not None:
                    # Przelicz punkty dla typu (zarówno nowego jak i zaktualizowanego)
                    from tipper import Tipper
                    points = Tipper.calculate_points(prediction, (int(home_goals), int(away_goals)))
                    
                    # Aktualizuj punkty w match_points (tylko jeśli nie są ręcznie ustawione)
                    if 'match_points' not in self.data['rounds'][round_id]:
                        self.data['rounds'][round_id]['match_points'] = {}
                    if player_name not in self.data['rounds'][round_id]['match_points']:
                        self.data['rounds'][round_id]['match_points'][player_name] = {}
                    
                    # Sprawdź czy punkty są ręcznie ustawione - jeśli tak, nie nadpisuj
                    if not self.is_manual_points(round_id, match_id_str, player_name):
                        self.data['rounds'][round_id]['match_points'][player_name][match_id_str] = points
                        logger.info(f"add_prediction: Przeliczono punkty {points} dla gracza {player_name}, mecz {match_id_str}, typ {prediction}, wynik {home_goals}-{away_goals}")
                    
                    # Przelicz całkowite punkty gracza (dla sezonu) tylko jeśli nie jesteśmy w trybie batch.
                    if recalculate_totals:
                        self._recalculate_player_totals(season_id=season_id)
                break
        
        # NIE zapisuj od razu przez _save_data() (używa debounce) - zapis będzie przez flush_save() po wszystkich typach
        # self._save_data()  # Wyłączone - zapis będzie przez flush_save() po wszystkich typach
        logger.info("add_prediction: Typ zapisany do pamięci, czekam na flush_save()")
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
    
    def update_match_result(
        self,
        round_id: str,
        match_id: str,
        home_goals: int,
        away_goals: int,
        save: bool = True,
        recalculate_totals: bool = True
    ):
        """Aktualizuje wynik meczu i przelicza punkty"""
        if round_id not in self.data['rounds']:
            logger.error(f"Runda {round_id} nie istnieje")
            return
        
        # Znajdź mecz w rundzie
        matches = self.data['rounds'][round_id]['matches']
        match_found = False
        for match in matches:
            if str(match.get('match_id')) == str(match_id):
                match['home_goals'] = home_goals
                match['away_goals'] = away_goals
                match['result_updated'] = datetime.now().isoformat()
                match_found = True
                logger.info(f"update_match_result: Zaktualizowano wynik meczu {match_id} w storage: {home_goals}-{away_goals}")
                break
        
        # Jeśli mecz nie został znaleziony w storage, ale są typy dla niego, dodaj go
        if not match_found:
            predictions = self.data['rounds'][round_id].get('predictions', {})
            has_predictions = False
            for player_name, player_predictions in predictions.items():
                if match_id in player_predictions or str(match_id) in player_predictions:
                    has_predictions = True
                    break
            
            if has_predictions:
                logger.warning(f"update_match_result: ⚠️ Mecz {match_id} nie jest w storage, ale gracze mają typy - dodaję mecz do storage")
                # Dodaj podstawowy mecz do storage (bez pełnych danych, ale z wynikiem)
                new_match = {
                    'match_id': str(match_id),
                    'home_goals': home_goals,
                    'away_goals': away_goals,
                    'result_updated': datetime.now().isoformat()
                }
                matches.append(new_match)
                logger.info(f"update_match_result: ✅ Dodano mecz {match_id} do storage z wynikiem {home_goals}-{away_goals}")
        
        # Pobierz sezon z rundy
        round_data = self.data['rounds'][round_id]
        season_id = round_data.get('season_id', self.season_id)
        
        # Pobierz graczy dla sezonu
        players = self._get_season_players(season_id)
        
        # Przelicz punkty dla wszystkich graczy
        from tipper import Tipper
        predictions = self.data['rounds'][round_id].get('predictions', {})
        
        logger.info(f"update_match_result: round_id={round_id}, match_id={match_id}, wynik={home_goals}-{away_goals}, graczy z typami={len(predictions)}")
        
        for player_name, player_predictions in predictions.items():
            # Sprawdź zarówno string jak i int jako klucz
            pred = None
            if match_id in player_predictions:
                pred = player_predictions[match_id]
            elif str(match_id) in player_predictions:
                pred = player_predictions[str(match_id)]
            elif match_id.isdigit() and int(match_id) in player_predictions:
                pred = player_predictions[int(match_id)]
            
            logger.info(f"update_match_result: Gracz {player_name}, match_id={match_id}, pred={pred}, player_predictions keys={list(player_predictions.keys())}")
            
            if pred:
                # Sprawdź czy punkty są ręcznie ustawione - jeśli tak, nie nadpisuj ich
                if self.is_manual_points(round_id, match_id, player_name):
                    logger.info(f"update_match_result: ⏭️ Pomijam automatyczne przeliczanie punktów dla gracza {player_name}, mecz {match_id} - punkty są ręcznie ustawione")
                    continue
                
                prediction_tuple = (pred['home'], pred['away'])
                points = Tipper.calculate_points(prediction_tuple, (home_goals, away_goals))
                
                logger.info(f"update_match_result: Gracz {player_name}, typ={prediction_tuple}, wynik={home_goals}-{away_goals}, obliczone punkty={points}")
                
                # Debug: sprawdź szczegóły obliczeń
                pred_home, pred_away = prediction_tuple
                actual_home, actual_away = home_goals, away_goals
                home_diff = abs(pred_home - actual_home)
                away_diff = abs(pred_away - actual_away)
                
                # Określ rezultat
                def get_result(home: int, away: int) -> str:
                    if home > away:
                        return 'home_win'
                    elif home < away:
                        return 'away_win'
                    else:
                        return 'draw'
                
                pred_result = get_result(pred_home, pred_away)
                actual_result_type = get_result(actual_home, actual_away)
                base_points = 10 if pred_result == actual_result_type else 5
                total_before_max = base_points - home_diff - away_diff
                
                logger.info(f"update_match_result: DEBUG - pred_result={pred_result}, actual_result={actual_result_type}, base_points={base_points}, home_diff={home_diff}, away_diff={away_diff}, total_before_max={total_before_max}, final_points={points}")
                
                # Aktualizuj punkty gracza (w sezonie)
                if player_name not in players:
                    players[player_name] = self._build_player_entry()
                
                # Zapisz punkty dla tego meczu
                if 'match_points' not in self.data['rounds'][round_id]:
                    self.data['rounds'][round_id]['match_points'] = {}
                if player_name not in self.data['rounds'][round_id]['match_points']:
                    self.data['rounds'][round_id]['match_points'][player_name] = {}
                
                # Użyj string jako klucz dla spójności
                self.data['rounds'][round_id]['match_points'][player_name][str(match_id)] = points
                logger.info(f"update_match_result: ✅ Zapisano punkty {points} dla gracza {player_name}, mecz {match_id}")
            else:
                logger.warning(f"update_match_result: ⚠️ Gracz {player_name} nie ma typu dla meczu {match_id}")
        
        if recalculate_totals:
            self._recalculate_player_totals(season_id=season_id, save=False)

        if save:
            self._save_data()
    
    def set_manual_points(self, round_id: str, match_id: str, player_name: str, points: int, season_id: str = None):
        """
        Ręcznie ustawia punkty dla gracza i meczu (może być ujemne)
        
        Args:
            round_id: ID rundy
            match_id: ID meczu
            player_name: Nazwa gracza
            points: Punkty (może być ujemne)
            season_id: ID sezonu (opcjonalne, domyślnie self.season_id)
        """
        if season_id is None:
            season_id = self.season_id
        
        if round_id not in self.data['rounds']:
            logger.error(f"Runda {round_id} nie istnieje")
            return False
        
        # Pobierz graczy dla sezonu
        players = self._get_season_players(season_id)
        
        # Upewnij się, że gracz istnieje
        if player_name not in players:
            logger.warning(f"Gracz {player_name} nie istnieje w sezonie {season_id}")
            # Możemy utworzyć gracza jeśli nie istnieje
            players[player_name] = self._build_player_entry()
        
        # Upewnij się, że struktura match_points istnieje
        if 'match_points' not in self.data['rounds'][round_id]:
            self.data['rounds'][round_id]['match_points'] = {}
        if player_name not in self.data['rounds'][round_id]['match_points']:
            self.data['rounds'][round_id]['match_points'][player_name] = {}
        
        # Upewnij się, że struktura manual_points istnieje (flaga oznaczająca ręcznie ustawione punkty)
        if 'manual_points' not in self.data['rounds'][round_id]:
            self.data['rounds'][round_id]['manual_points'] = {}
        if player_name not in self.data['rounds'][round_id]['manual_points']:
            self.data['rounds'][round_id]['manual_points'][player_name] = {}
        
        # Ustaw punkty i oznacz jako ręcznie ustawione
        match_id_str = str(match_id)
        self.data['rounds'][round_id]['match_points'][player_name][match_id_str] = points
        self.data['rounds'][round_id]['manual_points'][player_name][match_id_str] = True
        
        logger.info(f"set_manual_points: ✅ Ustawiono ręcznie punkty {points} dla gracza {player_name}, mecz {match_id} w rundzie {round_id}")
        
        # Przelicz całkowite punkty gracza
        self._recalculate_player_totals(season_id=season_id)
        self._save_data()
        
        return True
    
    def is_manual_points(self, round_id: str, match_id: str, player_name: str) -> bool:
        """
        Sprawdza czy punkty dla meczu są ręcznie ustawione
        
        Args:
            round_id: ID rundy
            match_id: ID meczu
            player_name: Nazwa gracza
            
        Returns:
            True jeśli punkty są ręcznie ustawione, False w przeciwnym razie
        """
        if round_id not in self.data['rounds']:
            return False
        
        manual_points = self.data['rounds'][round_id].get('manual_points', {})
        if player_name not in manual_points:
            return False
        
        match_id_str = str(match_id)
        return manual_points[player_name].get(match_id_str, False)
    
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
    
    def _recalculate_player_totals(self, season_id: str = None, save: bool = True):
        """Przelicza całkowite punkty dla wszystkich graczy w danym sezonie"""
        if season_id is None:
            season_id = self.season_id
        
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
                matches = round_data.get('matches', [])
                predictions = round_data.get('predictions', {}).get(player_name, {})
                
                # Pobierz wszystkie mecze w rundzie posortowane według daty
                all_matches_sorted = sorted(matches, key=lambda m: m.get('match_date', ''))
                
                # Sumuj punkty z meczów w rundzie (dla wszystkich meczów, dla których gracz ma typ)
                for match in all_matches_sorted:
                    match_id = str(match.get('match_id', ''))
                    
                    # Sprawdź czy gracz ma typ dla tego meczu
                    has_prediction = (match_id in predictions or 
                                    str(match_id) in predictions or
                                    (match_id.isdigit() and int(match_id) in predictions))
                    
                    if has_prediction:
                        # Sprawdź czy gracz ma punkty dla tego meczu
                        points = None
                        if match_id in match_points:
                            points = match_points[match_id]
                        elif str(match_id) in match_points:
                            points = match_points[str(match_id)]
                        elif match_id.isdigit() and int(match_id) in match_points:
                            points = match_points[int(match_id)]
                        else:
                            # Gracz ma typ, ale nie ma punktów - sprawdź czy mecz ma wynik
                            home_goals = match.get('home_goals')
                            away_goals = match.get('away_goals')
                            
                            if home_goals is not None and away_goals is not None:
                                # Mecz ma wynik, ale brak punktów - to błąd, ustaw 0
                                points = 0
                                logger.warning(f"_recalculate_player_totals: Gracz {player_name} ma typ dla meczu {match_id}, mecz ma wynik {home_goals}-{away_goals}, ale brak punktów!")
                            else:
                                # Mecz nie ma wyniku - ustaw 0
                                points = 0
                        
                        if points is not None:
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
                    # Sprawdź czy gracz typował w tej rundzie
                    has_predictions = player_name in round_data.get('predictions', {})
                    
                    if has_predictions:
                        # Gracz typował w rozegranej kolejce - zawsze dodaj punkty (nawet jeśli 0, np. przez ręczną korektę)
                        finished_round_scores.append(round_points)
                        if round_points > 0:
                            best_score = max(best_score, round_points)
                    else:
                        # Gracz nie typował w rozegranej kolejce - ma 0 punktów
                        finished_round_scores.append(0)
                
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
        
        if save:
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
        
        # Jeśli podano round_id, najpierw sprawdź w rounds[round_id]['predictions']
        # (to jest główne źródło danych dla rundy)
        if round_id and round_id in self.data.get('rounds', {}):
            round_predictions = self.data['rounds'][round_id].get('predictions', {})
            if player_name in round_predictions:
                return round_predictions[player_name]
        
        # Fallback: sprawdź w players[player_name]['predictions']
        # Pobierz graczy dla sezonu
        players = self._get_season_players(season_id)
        
        if player_name not in players:
            return {}
        
        if round_id:
            return players[player_name]['predictions'].get(round_id, {})
        else:
            return players[player_name]['predictions']

    def get_player_team(self, player_name: str, season_id: str = None) -> str:
        """Zwraca opcjonalne powiązanie gracza z drużyną."""
        if season_id is None:
            season_id = self.season_id

        players = self._get_season_players(season_id)
        if player_name not in players:
            return ""

        return str(players[player_name].get('team_name', '') or '').strip()

    def set_player_team(self, player_name: str, team_name: str, season_id: str = None) -> bool:
        """Ustawia opcjonalne powiązanie gracza z drużyną."""
        if season_id is None:
            season_id = self.season_id

        players = self._get_season_players(season_id)
        if player_name not in players:
            return False

        normalized_team_name = (team_name or '').strip()
        if normalized_team_name:
            players[player_name]['team_name'] = normalized_team_name
        else:
            players[player_name].pop('team_name', None)

        self._save_data()
        return True
    
    def get_leaderboard(self, exclude_worst: bool = True, season_id: str = None) -> List[Dict]:
        """Zwraca ranking graczy dla danego sezonu (z opcją odrzucenia najgorszego wyniku)"""
        if season_id is None:
            season_id = self.season_id

        season_data = self.data.get('seasons', {}).get(season_id, {})
        exclude_worst = exclude_worst and season_uses_worst_score_rule(season_id, season_data)
        
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
            round_scores = player_data.get('round_scores', {})
            
            # Ranking całości pokazuje tylko zamknięte kolejki.
            round_points_list = []
            for round_id, round_data in all_rounds:
                if not self._is_round_finished(round_data):
                    continue

                round_points = round_scores.get(round_id, 0)
                round_points_list.append(round_points)

                has_predictions = player_name in round_data.get('predictions', {})

                if has_predictions:
                    continue

                # Gracz nie typował, ale runda jest zamknięta - ma 0 punktów do tabeli całości.
                round_points_list[-1] = 0

            total_points = sum(round_points_list)
            finished_rounds_count = len(round_points_list)
            actual_best_score = max(round_points_list) if round_points_list else 0
            worst_from_finished = min(round_points_list) if round_points_list else 0
            
            # Odrzuć najgorszy wynik jeśli exclude_worst=True
            final_total_points = total_points
            if exclude_worst and len(round_points_list) > 1:
                final_total_points -= worst_from_finished
                excluded_worst = True
                actual_worst_score = worst_from_finished
            else:
                excluded_worst = False
                actual_worst_score = worst_from_finished
            
            team_name = str(player_data.get('team_name', '') or '').strip()

            leaderboard.append({
                'player_name': player_name,
                'team_name': team_name,
                'total_points': final_total_points,
                'rounds_played': finished_rounds_count,
                'best_score': actual_best_score,
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
        
        # Pobierz wszystkie mecze w rundzie posortowane według daty
        all_matches_sorted = sorted(matches, key=lambda m: m.get('match_date', ''))
        all_match_ids_sorted = [str(m.get('match_id', '')) for m in all_matches_sorted]
        
        for player_name in all_players:
            total_points = 0
            matches_count = 0
            match_points_list = []  # Lista punktów za każdy mecz w kolejności
            
            # Pobierz punkty gracza (jeśli ma)
            player_match_points = match_points.get(player_name, {})
            
            # Pobierz typy gracza (jeśli ma)
            player_predictions_dict = predictions.get(player_name, {})
            
            # Dla każdego meczu w rundzie (w kolejności) sprawdź punkty
            for match_id in all_match_ids_sorted:
                # Sprawdź czy gracz ma punkty dla tego meczu
                points = None
                if match_id in player_match_points:
                    points = player_match_points[match_id]
                elif str(match_id) in player_match_points:
                    points = player_match_points[str(match_id)]
                elif match_id.isdigit() and int(match_id) in player_match_points:
                    points = player_match_points[int(match_id)]
                else:
                    # Sprawdź czy gracz ma typ dla tego meczu
                    has_prediction = (match_id in player_predictions_dict or 
                                    str(match_id) in player_predictions_dict or
                                    (match_id.isdigit() and int(match_id) in player_predictions_dict))
                    
                    if has_prediction:
                        # Gracz ma typ, ale nie ma punktów - sprawdź czy mecz ma wynik
                        match_data = matches_map.get(match_id, {})
                        home_goals = match_data.get('home_goals')
                        away_goals = match_data.get('away_goals')
                        
                        if home_goals is not None and away_goals is not None:
                            # Mecz ma wynik, ale brak punktów - to błąd, ustaw 0
                            points = 0
                            logger.warning(f"Gracz {player_name} ma typ dla meczu {match_id}, mecz ma wynik {home_goals}-{away_goals}, ale brak punktów!")
                        else:
                            # Mecz nie ma wyniku - nie dodawaj do listy (lub dodaj 0)
                            points = 0
                    else:
                        # Gracz nie ma typu - nie dodawaj do listy
                        points = None
                
                # Dodaj punkty do listy tylko jeśli gracz ma typ (lub ma punkty)
                if points is not None:
                    match_points_list.append(points)
                    total_points += points
                    if points > 0 or (match_id in player_predictions_dict or str(match_id) in player_predictions_dict):
                        matches_count += 1
                    logger.info(f"DEBUG: Gracz {player_name}, match_id={match_id}, points={points}, total={total_points}")
            
            logger.info(f"DEBUG get_round_leaderboard: Gracz {player_name}, round_id={round_id}, "
                       f"match_points_list={match_points_list} (count={len(match_points_list)}), "
                       f"total_points={total_points}, matches_count={matches_count}")
            
            team_name = str(players.get(player_name, {}).get('team_name', '') or '').strip()

            player_scores[player_name] = {
                'player_name': player_name,
                'team_name': team_name,
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

    def get_selected_players(self, season_id: str = None) -> List[str]:
        """Zwraca listę wybranych graczy dla danego sezonu."""
        if season_id is None:
            season_id = self.season_id

        if season_id in self.data.get('seasons', {}):
            return self.data['seasons'][season_id].get('selected_players', [])

        if 'settings' in self.data and 'selected_players' in self.data['settings']:
            return self.data['settings'].get('selected_players', [])

        return []

    def get_team_metadata(self, season_id: str = None) -> Dict:
        """Zwraca metadane drużyn dla danego sezonu."""
        if season_id is None:
            season_id = self.season_id

        if season_id in self.data.get('seasons', {}):
            return self.data['seasons'][season_id].get('team_metadata', {})

        return {}

    def get_exclude_worst_rule(self, season_id: str = None) -> bool:
        """Zwraca ustawienie odrzucania najgorszego wyniku dla sezonu."""
        if season_id is None:
            season_id = self.season_id

        season_data = self.data.get('seasons', {}).get(season_id, {})
        return season_uses_worst_score_rule(season_id, season_data)

    def set_exclude_worst_rule(self, enabled: bool, season_id: str = None):
        """Ustawia regułę odrzucania najgorszego wyniku dla sezonu."""
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
                'selected_players': [],
                'team_metadata': {},
                'exclude_worst_rule': default_exclude_worst_rule(season_id)
            }

        self.data['seasons'][season_id]['exclude_worst_rule'] = bool(enabled)
        self._save_data()

    def set_team_metadata(self, team_metadata: Dict, season_id: str = None, merge: bool = True):
        """Zapisuje metadane drużyn dla danego sezonu."""
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
                'selected_players': [],
                'team_metadata': {}
            }

        if merge:
            merged_metadata = self.data['seasons'][season_id].get('team_metadata', {}).copy()
            merged_metadata.update(team_metadata)
            self.data['seasons'][season_id]['team_metadata'] = merged_metadata
        else:
            self.data['seasons'][season_id]['team_metadata'] = team_metadata

        self._save_data()
    
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
                'selected_teams': [],
                'selected_players': [],
                'team_metadata': {},
                'exclude_worst_rule': default_exclude_worst_rule(season_id)
            }
        
        # Zapisz wybór drużyn dla sezonu
        self.data['seasons'][season_id]['selected_teams'] = team_names
        self._save_data()

    def set_selected_players(self, player_names: List[str], season_id: str = None):
        """Zapisuje listę wybranych graczy dla danego sezonu."""
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
                'selected_players': [],
                'team_metadata': {},
                'exclude_worst_rule': default_exclude_worst_rule(season_id),
                'players': {}
            }

        self.data['seasons'][season_id]['selected_players'] = player_names
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
                'selected_leagues': [],
                'selected_players': [],
                'team_metadata': {},
                'exclude_worst_rule': default_exclude_worst_rule(season_id)
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
                'selected_players': [],
                'team_metadata': {},
                'exclude_worst_rule': default_exclude_worst_rule(season_id),
                'players': {}
            }
        
        # Ustaw status archiwalny
        self.data['seasons'][season_id]['archived'] = archived
        self._save_data()
    
    def add_player(self, player_name: str, season_id: str = None, team_name: str = ""):
        """Dodaje gracza do sezonu"""
        if season_id is None:
            season_id = self.season_id
        
        # Pobierz graczy dla sezonu
        players = self._get_season_players(season_id)
        
        if player_name in players:
            return False  # Gracz już istnieje
        
        players[player_name] = self._build_player_entry(team_name)
        
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

        selected_players = self.get_selected_players(season_id)
        if player_name in selected_players:
            self.data['seasons'][season_id]['selected_players'] = [name for name in selected_players if name != player_name]
        
        self._save_data()
        self._recalculate_player_totals(season_id=season_id)
        return True

    def rename_player(self, old_name: str, new_name: str, season_id: str = None):
        """Zmienia nazwę gracza w sezonie wraz z typami i punktami."""
        if season_id is None:
            season_id = self.season_id

        new_name = (new_name or "").strip()
        if not new_name:
            return False, "empty_name"

        players = self._get_season_players(season_id)

        if old_name not in players:
            return False, "missing_player"

        if old_name == new_name:
            return False, "same_name"

        if new_name in players:
            return False, "duplicate_name"

        players[new_name] = players.pop(old_name)

        selected_players = self.get_selected_players(season_id)
        if old_name in selected_players:
            self.data['seasons'][season_id]['selected_players'] = [
                new_name if player_name == old_name else player_name
                for player_name in selected_players
            ]

        for round_id, round_data in self.data['rounds'].items():
            if round_data.get('season_id') != season_id:
                continue

            if 'predictions' in round_data and old_name in round_data['predictions']:
                round_data['predictions'][new_name] = round_data['predictions'].pop(old_name)

            if 'match_points' in round_data and old_name in round_data['match_points']:
                round_data['match_points'][new_name] = round_data['match_points'].pop(old_name)

            if 'manual_points' in round_data and old_name in round_data['manual_points']:
                round_data['manual_points'][new_name] = round_data['manual_points'].pop(old_name)

        self._save_data()
        self._recalculate_player_totals(season_id=season_id)
        return True, None
    
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
            'selected_players': [],
            'team_metadata': {},
            'exclude_worst_rule': default_exclude_worst_rule(season_id),
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
