"""
Oddzielna aplikacja dla typera - uproszczona wersja bez prognoz
"""
import streamlit as st
import pandas as pd
import plotly.express as px
from datetime import datetime
import logging
import os
from typing import List, Dict
from collections import defaultdict

from tipper import Tipper
from tipper_storage import TipperStorage
from hattrick_oauth_simple import HattrickOAuthSimple
from dotenv import load_dotenv
from auth import check_authentication, login_page, logout

# Konfiguracja strony
st.set_page_config(
    page_title="Hattrick Typer",
    page_icon="🎯",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Konfiguracja logowania
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('tipper.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

FIXTURES_CACHE_TTL_SECONDS = 300
ROUND_AUTO_SYNC_TTL_SECONDS = 120
LEAGUE_DETAILS_CACHE_TTL_SECONDS = 86400


@st.cache_data(ttl=FIXTURES_CACHE_TTL_SECONDS, show_spinner=False)
def get_cached_league_fixtures(
    consumer_key: str,
    consumer_secret: str,
    access_token: str,
    access_token_secret: str,
    league_id: int
) -> List[Dict]:
    """Pobiera fixtures ligi z krótkim cache, aby ograniczyć liczbę requestów przy rerunach."""
    client = HattrickOAuthSimple(consumer_key, consumer_secret)
    client.set_access_tokens(access_token, access_token_secret)
    fixtures = client.get_league_fixtures(league_id) or []

    normalized_fixtures = []
    for fixture in fixtures:
        fixture_copy = fixture.copy()
        fixture_copy['league_id'] = league_id
        normalized_fixtures.append(fixture_copy)

    return normalized_fixtures


@st.cache_data(ttl=LEAGUE_DETAILS_CACHE_TTL_SECONDS, show_spinner=False)
def get_cached_league_name(
    consumer_key: str,
    consumer_secret: str,
    access_token: str,
    access_token_secret: str,
    league_id: int
) -> str:
    """Pobiera nazwę ligi i trzyma ją długo w cache."""
    client = HattrickOAuthSimple(consumer_key, consumer_secret)
    client.set_access_tokens(access_token, access_token_secret)
    league_details = client.get_league_details(league_id) or {}
    return league_details.get('league_name') or f"Liga {league_id}"


def should_auto_sync_round(round_id: str, scope: str) -> bool:
    """Ogranicza automatyczne synchronizacje tej samej rundy przy kolejnych rerunach."""
    sync_key = f"_last_auto_sync_{scope}_{round_id}"
    now_ts = datetime.now().timestamp()
    last_sync_ts = float(st.session_state.get(sync_key, 0))

    if now_ts - last_sync_ts < ROUND_AUTO_SYNC_TTL_SECONDS:
        return False

    st.session_state[sync_key] = now_ts
    return True


def build_team_metadata_from_fixtures(fixtures: List[Dict], league_names: Dict[int, str]) -> Dict[str, Dict]:
    """Buduje etykiety drużyn z nazwami lig na podstawie już pobranych fixtures."""
    team_metadata = {}

    for fixture in fixtures:
        league_id = fixture.get('league_id')
        league_name = league_names.get(league_id) if league_id is not None else None

        for team_key in ['home_team_name', 'away_team_name']:
            team_name = (fixture.get(team_key) or '').strip()
            if not team_name:
                continue

            entry = team_metadata.setdefault(team_name, {
                'league_ids': [],
                'league_names': [],
                'label': team_name
            })

            if league_id is not None and league_id not in entry['league_ids']:
                entry['league_ids'].append(league_id)

            if league_name and league_name not in entry['league_names']:
                entry['league_names'].append(league_name)

    for team_name, entry in team_metadata.items():
        if entry['league_names']:
            entry['label'] = f"{team_name} ({', '.join(entry['league_names'])})"

    return team_metadata


def get_all_time_leaderboard(exclude_worst: bool = False) -> List[Dict]:
    """
    Oblicza ranking wszechczasów - suma punktów ze wszystkich sezonów dla każdego gracza
    
    Args:
        exclude_worst: Czy odrzucić najgorszy wynik z każdego sezonu
    
    Returns:
        Lista słowników z danymi graczy posortowana po sumie punktów (malejąco)
    """
    import glob
    import re
    import json
    
    # Znajdź wszystkie pliki sezonów
    pattern = os.path.join(os.getcwd(), "tipper_data_season_*.json")
    files = glob.glob(pattern)
    
    # Słownik do przechowywania sum punktów dla każdego gracza
    players_total = {}  # {player_name: {'total': int, 'seasons': int, 'rounds': int, 'seasons_data': {season_id: points}}}
    
    # Przejdź przez wszystkie pliki sezonów
    logger.info(f"get_all_time_leaderboard: Znaleziono {len(files)} plików sezonów")
    for file_path in files:
        try:
            filename = os.path.basename(file_path)
            match = re.search(r'tipper_data_season_(\d+)\.json', filename)
            if not match:
                continue
            
            season_num = int(match.group(1))
            season_id = f"season_{season_num}"
            
            logger.info(f"get_all_time_leaderboard: Przetwarzam sezon {season_id} z pliku {filename}")
            
            # Wczytaj dane sezonu
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            # Pobierz graczy z sezonu (najpierw sprawdź w seasons, potem w players)
            # Ta sama logika jak w auth.py
            players_data = {}
            if season_id in data.get('seasons', {}):
                season_data = data['seasons'][season_id]
                if 'players' in season_data and season_data['players']:
                    players_data = season_data['players']
            
            # Jeśli nie ma w sezonie, sprawdź starą strukturę
            if not players_data and 'players' in data and data['players']:
                players_data = data['players']
            
            # Przetwarzaj graczy z tego sezonu
            for player_name, player_data in players_data.items():
                if player_name not in players_total:
                    players_total[player_name] = {
                        'total': 0,
                        'seasons': 0,
                        'rounds': 0,
                        'seasons_data': {}
                    }
                
                # Pobierz punkty gracza (używamy total_points z danych gracza)
                total_points = player_data.get('total_points', 0)
                worst_score = player_data.get('worst_score', 0)
                rounds_played = player_data.get('rounds_played', 0)
                
                # Odrzuć najgorszy wynik jeśli exclude_worst=True
                if exclude_worst and worst_score > 0:
                    season_points = total_points - worst_score
                else:
                    season_points = total_points
                
                logger.info(f"get_all_time_leaderboard: {player_name} w {season_id}: total_points={total_points}, worst_score={worst_score}, season_points={season_points}")
                
                # Dodaj punkty do sumy
                players_total[player_name]['total'] += season_points
                players_total[player_name]['seasons'] += 1
                players_total[player_name]['rounds'] += rounds_played
                players_total[player_name]['seasons_data'][season_id] = season_points
                
        except Exception as e:
            logger.error(f"Błąd przetwarzania pliku {file_path}: {e}")
            continue
    
    # Przygotuj listę do sortowania
    leaderboard = []
    for player_name, data in players_total.items():
        leaderboard.append({
            'player_name': player_name,
            'total_points': data['total'],
            'seasons_played': data['seasons'],
            'rounds_played': data['rounds'],
            'seasons_data': data['seasons_data']
        })
    
    # Sortuj po sumie punktów (malejąco)
    leaderboard.sort(key=lambda x: x['total_points'], reverse=True)
    
    return leaderboard


def main():
    """Główna funkcja aplikacji typera"""
    # Sprawdź autentykację
    if not check_authentication():
        login_page()
        return
    
    # Pobierz nazwę użytkownika z sesji
    username = st.session_state.get('username', 'Użytkownik')
    
    st.title("🎯 Hattrick Typer")
    
    # Automatyczne wykrywanie sezonów z plików JSON
    def get_available_seasons():
        """Skanuje katalog w poszukiwaniu plików tipper_data_season_*.json i zwraca listę sezonów"""
        import glob
        import re
        
        seasons = []
        
        # Szukaj plików tipper_data_season_*.json
        pattern = os.path.join(os.getcwd(), "tipper_data_season_*.json")
        files = glob.glob(pattern)
        
        # Wyciągnij numery sezonów z nazw plików
        for file_path in files:
            filename = os.path.basename(file_path)
            match = re.search(r'tipper_data_season_(\d+)\.json', filename)
            if match:
                season_num = int(match.group(1))
                seasons.append(season_num)
        
        # Sortuj malejąco (najnowszy pierwszy)
        seasons.sort(reverse=True)
        
        # Zwróć jako listę stringów "season_XX"
        return [f"season_{s}" for s in seasons]
    
    # Pobierz dostępne sezony
    available_seasons = get_available_seasons()
    
    # Jeśli nie znaleziono żadnych sezonów, użyj domyślnych
    if not available_seasons:
        available_seasons = ["current_season"]
        current_season_id = "current_season"
    else:
        # Najwyższy numer sezonu to current_season
        current_season_num = max([int(s.replace("season_", "")) for s in available_seasons])
        current_season_id = f"season_{current_season_num}"
    
    # Przygotuj opcje dla dropdown (current_season + dostępne sezony)
    season_options = [current_season_id] + [s for s in available_seasons if s != current_season_id]
    season_display = []
    for s in season_options:
        if s == current_season_id:
            season_display.append(f"Sezon {current_season_num} (obecny)")
        else:
            season_num = s.replace("season_", "")
            season_display.append(f"Sezon {season_num}")
    
    # Domyślnie wybierz current_season (pierwszy w liście)
    default_season_idx = 0
    
    selected_season_idx = st.selectbox(
        "📅 Wybierz sezon:",
        range(len(season_options)),
        index=default_season_idx,
        format_func=lambda x: season_display[x],
        key="selected_season"
    )
    selected_season_id = season_options[selected_season_idx]
    # Zapisz wybrany sezon w session_state dla użycia w sidebarze
    st.session_state["selected_season_id"] = selected_season_id
    
    # Przycisk dodawania nowego sezonu
    with st.expander("➕ Dodaj nowy sezon", expanded=False):
        new_season_num = st.number_input(
            "Numer sezonu:",
            value=int(selected_season_id.replace("season_", "")) + 1 if selected_season_id.startswith("season_") else 81,
            min_value=1,
            step=1,
            key="new_season_num"
        )
        copy_players = st.checkbox(
            "📋 Kopiuj graczy z poprzedniego sezonu",
            value=True,
            help="Jeśli zaznaczone, gracze z poprzedniego sezonu zostaną automatycznie dodani do nowego sezonu",
            key="copy_players_checkbox"
        )
        if st.button("➕ Utwórz nowy sezon", type="primary", key="create_new_season"):
            # Utwórz storage dla nowego sezonu (tylko do utworzenia pliku)
            new_season_id = f"season_{new_season_num}"
            temp_storage = TipperStorage(season_id=new_season_id)
            if temp_storage.create_new_season(new_season_num):
                # Jeśli zaznaczono kopiowanie graczy, skopiuj ich z poprzedniego sezonu
                if copy_players and available_seasons:
                    # Znajdź poprzedni sezon (najwyższy numer przed nowym)
                    # available_seasons to lista stringów "season_XX", więc konwertuj na numery
                    previous_seasons = [int(s.replace("season_", "")) for s in available_seasons if int(s.replace("season_", "")) < new_season_num]
                    if previous_seasons:
                        previous_season_num = max(previous_seasons)
                        previous_season_id = f"season_{previous_season_num}"
                        
                        # Załaduj poprzedni sezon i skopiuj graczy
                        previous_storage = TipperStorage(season_id=previous_season_id)
                        previous_players = previous_storage.get_season_players_list(season_id=previous_season_id)
                        
                        if previous_players:
                            copied_count = 0
                            for player_name in previous_players:
                                if temp_storage.add_player(player_name, season_id=new_season_id):
                                    copied_count += 1
                            
                            if copied_count > 0:
                                temp_storage.flush_save()
                                st.success(f"✅ Utworzono nowy sezon {new_season_num} i skopiowano {copied_count} graczy z sezonu {previous_season_num}")
                            else:
                                st.success(f"✅ Utworzono nowy sezon {new_season_num}")
                        else:
                            st.success(f"✅ Utworzono nowy sezon {new_season_num} (brak graczy w poprzednim sezonie)")
                    else:
                        st.success(f"✅ Utworzono nowy sezon {new_season_num}")
                else:
                    st.success(f"✅ Utworzono nowy sezon {new_season_num}")
                st.rerun()
            else:
                st.error(f"❌ Sezon {new_season_num} już istnieje lub wystąpił błąd")
    
    # Inicjalizacja storage dla wybranego sezonu (używany w całej aplikacji)
    storage = TipperStorage(season_id=selected_season_id)
    
    st.markdown("---")
    
    # Sidebar z konfiguracją
    with st.sidebar:
        # Sekcja użytkownika
        st.header("👤 Użytkownik")
        st.info(f"Zalogowany jako: **{username}**")
        if st.button("🚪 Wyloguj się", width='stretch'):
            logout()
            return
        
        st.markdown("---")
        st.header("⚙️ Konfiguracja")
        
        # ID lig dla typera - per sezon (dynamiczna lista)
        st.subheader(f"🏆 Ligi typera (Sezon {selected_season_id.replace('season_', '')})")
        
        # Pobierz zapisane ligi dla wybranego sezonu
        saved_leagues = storage.get_selected_leagues(season_id=selected_season_id)
        
        # Jeśli nie ma zapisanych lig, użyj domyślnych
        if not saved_leagues:
            saved_leagues = [32612, 9399]
        
        # Inicjalizuj session_state dla lig (jeśli nie istnieje)
        leagues_key = f"leagues_list_{selected_season_id}"
        if leagues_key not in st.session_state:
            st.session_state[leagues_key] = saved_leagues.copy()
        
        # Wyświetl listę lig z możliwością edycji
        st.markdown("**Lista lig:**")
        leagues_to_remove = []
        
        for idx, league_id in enumerate(st.session_state[leagues_key]):
            col_league, col_remove = st.columns([4, 1])
            with col_league:
                new_league_id = st.number_input(
                    f"Liga {idx + 1} (LeagueLevelUnitID):",
                    value=league_id,
            min_value=1,
                    key=f"league_{selected_season_id}_{idx}",
                    label_visibility="collapsed"
                )
                st.write(f"Liga {idx + 1}: {new_league_id}")
                # Aktualizuj wartość w session_state
                st.session_state[leagues_key][idx] = new_league_id
            with col_remove:
                if st.button("🗑️", key=f"remove_league_{selected_season_id}_{idx}", help="Usuń ligę"):
                    leagues_to_remove.append(idx)
        
        # Usuń zaznaczone ligi (od końca, aby nie zmieniać indeksów)
        for idx in sorted(leagues_to_remove, reverse=True):
            st.session_state[leagues_key].pop(idx)
            st.rerun()
        
        # Przycisk dodawania nowej ligi
        col_add, col_save = st.columns(2)
        with col_add:
            if st.button("➕ Dodaj ligę", key=f"add_league_{selected_season_id}", width='stretch'):
                # Dodaj domyślną ligę (najwyższe ID + 1 lub 1)
                if st.session_state[leagues_key]:
                    new_league_id = max(st.session_state[leagues_key]) + 1
                else:
                    new_league_id = 32612
                st.session_state[leagues_key].append(new_league_id)
                st.rerun()
        
        with col_save:
            # Przycisk zapisu lig
            if st.button("💾 Zapisz ligi", type="primary", key=f"save_leagues_{selected_season_id}", width='stretch'):
                TIPPER_LEAGUES = st.session_state[leagues_key].copy()
                storage.set_selected_leagues(TIPPER_LEAGUES, season_id=selected_season_id)
                storage.flush_save()  # Wymuś natychmiastowy zapis przed rerun
                st.success(f"✅ Zapisano {len(TIPPER_LEAGUES)} lig dla sezonu {selected_season_id.replace('season_', '')}")
                st.rerun()
        
        # Użyj aktualnej listy lig
        TIPPER_LEAGUES = st.session_state[leagues_key].copy()
        
        # Informacje o zapisanych ligach
        if saved_leagues:
            st.info(f"**Zapisane ligi:** {', '.join(map(str, saved_leagues))}")
        
        st.markdown("---")
        
        # Status archiwalny sezonu
        st.subheader(f"📦 Status sezonu (Sezon {selected_season_id.replace('season_', '')})")
        is_archived = storage.is_season_archived(season_id=selected_season_id)
        
        archived_status = st.checkbox(
            "Oznacz jako archiwalny",
            value=is_archived,
            help="Archiwalne sezony nie wykonują zapytań do API - używają tylko danych z pliku",
            key=f"archived_checkbox_{selected_season_id}"
        )
        
        if archived_status != is_archived:
            if st.button("💾 Zapisz status", type="primary", key=f"save_archived_{selected_season_id}", width='stretch'):
                storage.set_season_archived(archived_status, season_id=selected_season_id)
                storage.flush_save()
                if archived_status:
                    st.success(f"✅ Sezon {selected_season_id.replace('season_', '')} oznaczony jako archiwalny")
                else:
                    st.success(f"✅ Sezon {selected_season_id.replace('season_', '')} oznaczony jako aktywny")
                st.rerun()
        
        if is_archived:
            st.info("📦 Ten sezon jest archiwalny - nie wykonuje zapytań do API")
        
        st.markdown("---")
        
        # Przycisk odświeżania danych
        if st.button("🔄 Odśwież dane", type="primary"):
            st.cache_data.clear()
            st.rerun()
        
        st.markdown("---")
        st.subheader("💾 Import/Eksport danych")
        
        # Storage jest już utworzony w głównym widoku - użyj go
        
        # Eksport danych
        if st.button("📥 Pobierz backup danych", width='stretch', help="Pobierz aktualny plik tipper_data.json"):
            import json
            data_str = json.dumps(storage.data, ensure_ascii=False, indent=2)
            st.download_button(
                label="⬇️ Pobierz plik JSON",
                data=data_str,
                file_name="tipper_data.json",
                mime="application/json",
                width='stretch'
            )
        
        # Import danych
        with st.expander("📤 Import danych z pliku", expanded=False):
            st.markdown("**Wgraj plik tipper_data.json aby zaimportować dane:**")
            uploaded_file = st.file_uploader(
                "Wybierz plik JSON",
                type=['json'],
                help="Wgraj plik tipper_data.json z zapisanymi danymi"
            )
            
            if uploaded_file is not None:
                try:
                    # Wczytaj dane z pliku
                    import json
                    uploaded_data = json.load(uploaded_file)
                    
                    # Walidacja struktury danych
                    required_keys = ['players', 'rounds', 'seasons', 'leagues', 'settings']
                    if all(key in uploaded_data for key in required_keys):
                        st.success("✅ Plik został poprawnie wczytany!")
                        
                        # Pokaż podsumowanie danych
                        players_count = len(uploaded_data.get('players', {}))
                        rounds_count = len(uploaded_data.get('rounds', {}))
                        
                        st.info(f"📊 Dane w pliku:\n- Gracze: {players_count}\n- Rundy: {rounds_count}")
                        
                        # Przycisk importu
                        if st.button("💾 Zaimportuj dane", type="primary", width='stretch'):
                            # Zrób backup przed importem
                            backup_data = storage.data.copy()
                            
                            # Zaimportuj dane
                            storage.data = uploaded_data
                            storage._save_data()
                            
                            st.success("✅ Dane zostały zaimportowane pomyślnie!")
                            st.info("🔄 Odśwież stronę aby zobaczyć zmiany")
                            st.rerun()
                    else:
                        st.error("❌ Nieprawidłowy format pliku. Brakuje wymaganych kluczy.")
                except json.JSONDecodeError:
                    st.error("❌ Błąd parsowania JSON. Sprawdź czy plik jest poprawny.")
                except Exception as e:
                    st.error(f"❌ Błąd importu danych: {str(e)}")
    
    # Inicjalizacja tipper
    tipper = Tipper()
    
    # Pobierz dane z API
    try:
        load_dotenv()
        
        # Pobierz klucze OAuth z zmiennych środowiskowych
        consumer_key = os.getenv('HATTRICK_CONSUMER_KEY')
        consumer_secret = os.getenv('HATTRICK_CONSUMER_SECRET')
        access_token = os.getenv('HATTRICK_ACCESS_TOKEN')
        access_token_secret = os.getenv('HATTRICK_ACCESS_TOKEN_SECRET')
        
        if not all([consumer_key, consumer_secret, access_token, access_token_secret]):
            st.error("❌ Brak kluczy OAuth. Uruchom: python get_oauth_simple.py")
            st.info("💡 Aby uzyskać klucze OAuth, uruchom skrypt `get_oauth_simple.py`")
            return
        
        # Sprawdź czy sezon jest archiwalny
        is_archived = storage.is_season_archived(season_id=selected_season_id)
        
        # Dla archiwalnych sezonów nie pobieramy danych z API - używamy tylko danych z pliku
        if is_archived:
            st.info("📦 Sezon archiwalny - używam tylko danych z pliku (bez zapytań do API)")
            # Pobierz mecze z zapisanych rund
            all_fixtures = []
            for round_id, round_data in storage.data.get('rounds', {}).items():
                if round_data.get('season_id') == selected_season_id:
                    matches = round_data.get('matches', [])
                    all_fixtures.extend(matches)
            
            # Sprawdź czy są gracze z wynikami - bezpośrednio z danych
            has_players_with_scores = False
            players_data_check = {}
            
            # Sprawdź w strukturze sezonu
            if selected_season_id in storage.data.get('seasons', {}):
                season_data = storage.data['seasons'][selected_season_id]
                if 'players' in season_data and season_data['players']:
                    players_data_check = season_data['players']
            
            # Jeśli nie ma w sezonie, sprawdź starą strukturę (kompatybilność wsteczna)
            if not players_data_check and 'players' in storage.data and storage.data['players']:
                players_data_check = storage.data['players']
            
            # Sprawdź czy są gracze z wynikami
            for player_name, player_data in players_data_check.items():
                if player_data.get('total_points', 0) > 0:
                    has_players_with_scores = True
                    break
            
            # Jeśli nie ma meczów, ale są gracze z wynikami - wyświetl tylko ranking
            if not all_fixtures and has_players_with_scores:
                st.info("📊 Sezon archiwalny - wyświetlam tylko podsumowania (brak szczegółowych danych o meczach)")
                
                # Przeładuj dane z pliku
                storage.reload_data()
                
                # Wyświetl tylko ranking
                st.markdown("---")
                st.subheader("🏆 Ranking")
                
                exclude_worst = st.checkbox("Odrzuć najgorszy wynik każdego gracza", value=True, key="exclude_worst_overall_archived")
                
                # Pobierz graczy bezpośrednio z danych sezonu (dla archiwalnych sezonów)
                # Najpierw sprawdź w seasons[season_id]['players'], potem w players (kompatybilność wsteczna)
                players_data = {}
                
                # Sprawdź w strukturze sezonu
                if selected_season_id in storage.data.get('seasons', {}):
                    season_data = storage.data['seasons'][selected_season_id]
                    if 'players' in season_data and season_data['players']:
                        players_data = season_data['players']
                
                # Jeśli nie ma w sezonie, sprawdź starą strukturę (kompatybilność wsteczna)
                if not players_data and 'players' in storage.data and storage.data['players']:
                    players_data = storage.data['players']
                
                if players_data:
                    # Przygotuj ranking z podziałem na rundy
                    leaderboard_data = []
                    for player_name, player_data in players_data.items():
                        round_scores = player_data.get('round_scores', {})
                        total_points = player_data.get('total_points', 0)
                        worst_score = player_data.get('worst_score', 0)
                        rounds_played = player_data.get('rounds_played', 0)
                        
                        # Pobierz punkty z rund w kolejności (round_1, round_2, ...)
                        round_points_list = []
                        for i in range(1, rounds_played + 1):
                            round_key = f"round_{i}"
                            points = round_scores.get(round_key, 0)
                            round_points_list.append(points)
                        
                        # Oblicz sumę przed odrzuceniem najgorszego
                        # Jeśli mamy round_scores, użyj sumy z listy, w przeciwnym razie użyj total_points
                        if round_points_list and any(p > 0 for p in round_points_list):
                            # Mamy szczegółowe dane z rund
                            original_total = sum(round_points_list)
                        else:
                            # Nie mamy szczegółowych danych lub same zera - użyj total_points
                            original_total = total_points
                            # Jeśli nie ma round_scores w ogóle, stwórz pustą listę dla wyświetlania
                            if not round_scores:
                                round_points_list = []
                        
                        # Odrzuć najgorszy wynik jeśli exclude_worst=True
                        final_total = original_total
                        if exclude_worst and len(round_points_list) > 1 and worst_score > 0:
                            final_total = original_total - worst_score
                        elif exclude_worst and worst_score > 0 and original_total == total_points:
                            # Jeśli używamy total_points, odrzuć worst_score
                            final_total = original_total - worst_score
                        
                        # Formatuj punkty: 26 + 38 + 40 + ... = 477 - 13 = 464
                        if round_points_list and any(p > 0 for p in round_points_list):
                            # Mamy szczegółowe dane - pokaż podział na rundy
                            points_str = ' + '.join(str(p) for p in round_points_list)
                            if exclude_worst and worst_score > 0:
                                summary = f"{points_str} = {original_total} - {worst_score} = {final_total}"
                            else:
                                summary = f"{points_str} = {final_total}"
                        else:
                            # Nie mamy szczegółowych danych - pokaż tylko sumę
                            if exclude_worst and worst_score > 0:
                                summary = f"{total_points} - {worst_score} = {final_total}"
                            else:
                                summary = str(final_total)
                        
                        leaderboard_data.append({
                            'Pozycja': 0,  # Zostanie ustawione po sortowaniu
                            'Gracz': player_name,
                            'Punkty': summary,
                            'Suma': final_total,
                            'Rundy': rounds_played
                        })
                    
                    # Sortuj po sumie (malejąco)
                    leaderboard_data.sort(key=lambda x: x['Suma'], reverse=True)
                    
                    # Ustaw pozycje
                    for idx, item in enumerate(leaderboard_data, 1):
                        item['Pozycja'] = idx
                    
                    if leaderboard_data:
                        df_leaderboard = pd.DataFrame(leaderboard_data)
                        st.dataframe(df_leaderboard[['Pozycja', 'Gracz', 'Punkty', 'Suma', 'Rundy']], width='stretch', hide_index=True)
                    else:
                        st.info("📊 Brak danych rankingowych")
                else:
                    st.info("📊 Brak danych rankingowych")
                
                return
            
            # Jeśli nie ma ani meczów, ani graczy - wyświetl komunikat
            if not all_fixtures and not has_players_with_scores:
                st.warning("⚠️ Brak danych w archiwalnym sezonie")
                return
            
            # Pobierz wszystkie unikalne nazwy drużyn z meczów
            all_team_names = set()
            for fixture in all_fixtures:
                home_team = fixture.get('home_team_name', '').strip()
                away_team = fixture.get('away_team_name', '').strip()
                if home_team:
                    all_team_names.add(home_team)
                if away_team:
                    all_team_names.add(away_team)
            
            all_team_names = sorted(list(all_team_names))
            team_metadata = storage.get_team_metadata(season_id=selected_season_id)
            
            # Grupuj mecze według rund (na podstawie daty)
            rounds = defaultdict(list)
            
            for fixture in all_fixtures:
                match_date = fixture.get('match_date')
                if match_date:
                    try:
                        # Parsuj datę i utwórz klucz rundy (np. "2024-10-26")
                        dt = datetime.strptime(match_date, "%Y-%m-%d %H:%M:%S")
                        round_key = dt.strftime("%Y-%m-%d")
                        rounds[round_key].append(fixture)
                    except ValueError:
                        continue
            
            # Sortuj rundy po dacie (najstarsza pierwsza) dla numeracji
            sorted_rounds_asc = sorted(rounds.items(), key=lambda x: x[0])
            
            # Jeśli nie ma meczów, ale są gracze - już obsłużyliśmy to wyżej
            if not sorted_rounds_asc:
                # To nie powinno się zdarzyć, ale na wszelki wypadek
                return
        else:
            # Dla niearchiwalnych sezonów pobieramy dane z API
            # Pobierz mecze z obu lig
            all_fixtures = []
            with st.spinner("Pobieranie meczów z lig..."):
                for league_id in TIPPER_LEAGUES:
                    try:
                        fixtures = get_cached_league_fixtures(
                            consumer_key,
                            consumer_secret,
                            access_token,
                            access_token_secret,
                            league_id
                        )
                        if fixtures:
                            all_fixtures.extend(fixtures)
                            logger.info(f"Pobrano {len(fixtures)} meczów z ligi {league_id}")
                    except Exception as e:
                        logger.error(f"Błąd pobierania meczów z ligi {league_id}: {e}")
                        st.warning(f"⚠️ Nie udało się pobrać meczów z ligi {league_id}: {e}")
            
            if not all_fixtures:
                st.error("❌ Nie udało się pobrać meczów z API")
                return
            
            # Grupuj mecze według rund (na podstawie daty)
            rounds = defaultdict(list)
            
            for fixture in all_fixtures:
                match_date = fixture.get('match_date')
                if match_date:
                    try:
                        # Parsuj datę i utwórz klucz rundy (np. "2024-10-26")
                        dt = datetime.strptime(match_date, "%Y-%m-%d %H:%M:%S")
                        round_key = dt.strftime("%Y-%m-%d")
                        rounds[round_key].append(fixture)
                    except ValueError:
                        continue
            
            # Sortuj rundy po dacie (najstarsza pierwsza) dla numeracji
            sorted_rounds_asc = sorted(rounds.items(), key=lambda x: x[0])
            
            if not sorted_rounds_asc:
                st.warning("⚠️ Brak meczów do wyświetlenia")
                return
            
            # Pobierz wszystkie unikalne nazwy drużyn z meczów
            all_team_names = set()
            for _, matches in sorted_rounds_asc:
                for match in matches:
                    home_team = match.get('home_team_name', '').strip()
                    away_team = match.get('away_team_name', '').strip()
                    if home_team:
                        all_team_names.add(home_team)
                    if away_team:
                        all_team_names.add(away_team)
            
            all_team_names = sorted(list(all_team_names))
            
            # Przeładuj dane z pliku (aby mieć aktualne dane po restarcie)
            storage.reload_data()
            
            # Pobierz zapisane ustawienia dla wybranego sezonu
            selected_teams = storage.get_selected_teams(season_id=selected_season_id)
            team_metadata = storage.get_team_metadata(season_id=selected_season_id)

            season_leagues = storage.get_selected_leagues(season_id=selected_season_id) or TIPPER_LEAGUES
            league_names = {}

            for league_id in season_leagues:
                stored_league = storage.data.get('leagues', {}).get(str(league_id), {})
                stored_name = stored_league.get('name')

                if stored_name:
                    league_names[league_id] = stored_name
                else:
                    league_names[league_id] = get_cached_league_name(
                        consumer_key,
                        consumer_secret,
                        access_token,
                        access_token_secret,
                        league_id
                    )
                    storage.add_league(league_id, league_names[league_id])

            current_team_metadata = build_team_metadata_from_fixtures(all_fixtures, league_names)
            if current_team_metadata:
                merged_team_metadata = team_metadata.copy()
                merged_team_metadata.update(current_team_metadata)
                if merged_team_metadata != team_metadata:
                    team_metadata = merged_team_metadata
                    storage.set_team_metadata(team_metadata, season_id=selected_season_id, merge=False)
        
        # Jeśli nie ma zapisanych ustawień dla tego sezonu, wybierz wszystkie drużyny domyślnie
        if not selected_teams:
            selected_teams = all_team_names.copy()

        team_labels = {}
        for team_name in all_team_names:
            team_labels[team_name] = team_metadata.get(team_name, {}).get('label', team_name)
        
        # Wybór drużyn do typowania - w sidebarze
        with st.sidebar:
            st.markdown("---")
            st.subheader(f"⚙️ Wybór drużyn do typowania (Sezon {selected_season_id.replace('season_', '')})")
            st.markdown("*Zaznacz drużyny, które chcesz uwzględnić w typerze*")
            
            # Użyj checkboxów dla wyboru drużyn
            new_selected_teams = []
            
            for team_name in all_team_names:
                if st.checkbox(team_labels.get(team_name, team_name), value=team_name in selected_teams, key=f"team_select_{selected_season_id}_{team_name}"):
                    new_selected_teams.append(team_name)
            
            # Przycisk zapisu ustawień
            if st.button("💾 Zapisz wybór drużyn", type="primary", width='stretch'):
                storage.set_selected_teams(new_selected_teams, season_id=selected_season_id)
                storage.flush_save()  # Wymuś natychmiastowy zapis przed rerun
                st.success(f"✅ Zapisano wybór {len(new_selected_teams)} drużyn dla sezonu {selected_season_id.replace('season_', '')}")
                st.rerun()
            
            # Użyj aktualnie wybranych drużyn
            selected_teams = new_selected_teams if new_selected_teams else selected_teams
        
        # Filtruj mecze - tylko te, w których uczestniczą wybrane drużyny
        def filter_matches_by_teams(matches: List[Dict], team_names: List[str]) -> List[Dict]:
            """Filtruje mecze, pozostawiając tylko te z wybranymi drużynami"""
            if not team_names:
                return matches  # Jeśli nie wybrano drużyn, zwróć wszystkie
            
            filtered = []
            for match in matches:
                home_team = match.get('home_team_name', '').strip()
                away_team = match.get('away_team_name', '').strip()
                
                # Mecz jest uwzględniony, jeśli przynajmniej jedna drużyna jest wybrana
                if home_team in team_names or away_team in team_names:
                    filtered.append(match)
            
            return filtered
        
        # Filtruj rundy (według daty asc dla numeracji)
        filtered_rounds_asc = []
        for date, matches in sorted_rounds_asc:
            filtered_matches = filter_matches_by_teams(matches, selected_teams)
            if filtered_matches:  # Tylko jeśli są jakieś mecze po filtrowaniu
                filtered_rounds_asc.append((date, filtered_matches))
        
        if not filtered_rounds_asc:
            st.warning(f"⚠️ Brak meczów dla wybranych drużyn ({len(selected_teams)} drużyn)")
            st.info(f"Wybrane drużyny: {', '.join(selected_teams[:5])}{'...' if len(selected_teams) > 5 else ''}")
            return
        
        # Stwórz mapę data -> numer kolejki (według daty asc: najstarsza = 1)
        date_to_round_number = {}
        for idx, (date, _) in enumerate(filtered_rounds_asc, 1):
            date_to_round_number[date] = idx  # Numer 1 = najstarsza
        
        # Sortuj rundy po dacie desc (najnowsza pierwsza) dla wyświetlania
        filtered_rounds = sorted(filtered_rounds_asc, key=lambda x: x[0], reverse=True)
        
        # Ranking - na samą górę
        st.markdown("---")
        st.subheader("🏆 Ranking")
        
        # Tabs dla rankingu per kolejka, całości i wszechczasów - domyślnie ranking całości (pierwszy tab)
        ranking_tab1, ranking_tab2, ranking_tab3 = st.tabs(["🏆 Ranking całości", "📊 Ranking per kolejka", "🌟 Ranking wszechczasów"])
        
        # Dla rankingu całości nie potrzebujemy wyboru rundy
        with ranking_tab1:
            st.markdown("### 🏆 Ranking całości")
            
            exclude_worst = st.checkbox("Odrzuć najgorszy wynik każdego gracza", value=True, key="exclude_worst_overall")
            # Przelicz punkty przed pobraniem rankingu (aby mieć aktualne dane)
            storage._recalculate_player_totals(season_id=selected_season_id)
            leaderboard = storage.get_leaderboard(exclude_worst=exclude_worst, season_id=selected_season_id)
            
            if leaderboard:
                # Przygotuj dane do wyświetlenia
                leaderboard_data = []
                for idx, player in enumerate(leaderboard, 1):
                    # Formatuj punkty z każdej kolejki: 26 + 37 + 32 + ... = 393 - 23
                    round_points = player.get('round_points', [])
                    original_total = player.get('original_total', player['total_points'])
                    
                    if round_points:
                        # Formatuj punkty: 26 + 37 + 32 + ...
                        points_str = ' + '.join(str(p) for p in round_points)
                        
                        # Dodaj sumę i odjęcie najgorszego jeśli włączone
                        if exclude_worst and player['excluded_worst']:
                            worst = player['worst_score']
                            points_summary = f"{points_str} = {original_total} - {worst}"
                        else:
                            points_summary = f"{points_str} = {original_total}"
                    else:
                        points_summary = str(player['total_points'])
                    
                    leaderboard_data.append({
                        'Miejsce': idx,
                        'Gracz': player['player_name'],
                        'Punkty': points_summary,
                        'Suma': player['total_points'],
                        'Rundy': player['rounds_played'],
                        'Najlepszy': player['best_score'],
                        'Najgorszy': player['worst_score'] if not player['excluded_worst'] else f"{player['worst_score']} (odrzucony)"
                    })
                
                df_leaderboard = pd.DataFrame(leaderboard_data)
                st.dataframe(df_leaderboard, width='stretch', hide_index=True)
                
                # Wykres rankingu całości
                if len(leaderboard) > 0:
                    fig = px.bar(
                        df_leaderboard.head(10),
                        x='Gracz',
                        y='Suma',
                        title="Top 10 - Ranking całości",
                        labels={'Suma': 'Punkty', 'Gracz': 'Gracz'},
                        color='Suma',
                        color_continuous_scale='plasma'
                    )
                    fig.update_layout(xaxis_tickangle=-45, height=400)
                    st.plotly_chart(fig, use_container_width=True, key="ranking_overall_chart_main")
                    
                    # Statystyki
                    col1, col2, col3, col4 = st.columns(4)
                    with col1:
                        st.metric("Liczba graczy", len(leaderboard))
                    with col2:
                        if leaderboard:
                            st.metric("Najwięcej punktów", leaderboard[0]['total_points'])
                    with col3:
                        if leaderboard:
                            avg_points = sum(p['total_points'] for p in leaderboard) / len(leaderboard)
                            st.metric("Średnia punktów", f"{avg_points:.1f}")
                    with col4:
                        if leaderboard:
                            total_rounds = sum(p['rounds_played'] for p in leaderboard)
                            st.metric("Łącznie rund", total_rounds)
            else:
                st.info("📊 Brak danych do wyświetlenia")
        
        # Dla rankingu per kolejka potrzebujemy wyboru rundy
        with ranking_tab2:
            st.markdown("### 📊 Ranking per kolejka")
            
            # Wybór rundy - pod Rankingiem
            st.markdown("---")
            st.subheader("📅 Wybór rundy")
            
            # Znajdź pierwszą nie rozegraną kolejkę (najstarszą nie rozegraną - domyślnie po zalogowaniu)
            default_round_idx = 0
            # Przeszukaj od końca (od najstarszej do najnowszej), aby znaleźć najstarszą nie rozegraną
            for idx in range(len(filtered_rounds) - 1, -1, -1):
                date, matches = filtered_rounds[idx]
                # Sprawdź czy kolejka ma rozegrane mecze
                has_played = any(m.get('home_goals') is not None and m.get('away_goals') is not None for m in matches)
                if not has_played:
                    default_round_idx = idx
                    break  # Weź najstarszą nie rozegraną kolejkę
            
            # Sprawdź czy jest zapisany wybór rundy w session_state
            if 'selected_round_idx' in st.session_state:
                default_round_idx = st.session_state.selected_round_idx
            
            # Numeruj kolejki według daty asc (numer 1 = najstarsza), ale wyświetlaj sort desc (najnowsza pierwsza)
            round_options = []
            for date, matches in filtered_rounds:
                round_number = date_to_round_number[date]  # Numer według daty asc
                round_options.append(f"Kolejka {round_number} - {date} ({len(matches)} meczów)")
            
            selected_round_idx = st.selectbox("Wybierz rundę:", range(len(round_options)), index=default_round_idx, format_func=lambda x: round_options[x], key="ranking_round_select")
            
            # Zapisz wybór rundy w session_state
            st.session_state.selected_round_idx = selected_round_idx
            
            if selected_round_idx is not None:
                selected_round_date, selected_matches = filtered_rounds[selected_round_idx]
                round_number = date_to_round_number[selected_round_date]  # Numer kolejki według daty asc (1 = najstarsza)
                round_id = f"round_{selected_round_date}"
                
                # Dodaj rundę do storage jeśli nie istnieje
                if round_id not in storage.data['rounds']:
                    # Sezon zostanie automatycznie utworzony w add_round jeśli nie istnieje
                    storage.add_round(selected_season_id, round_id, selected_matches, selected_round_date)
                
                # Ranking dla wybranej rundy
                # Przeładuj dane przed pobraniem rankingu, aby mieć aktualne punkty
                storage.reload_data()
                auto_sync_round = should_auto_sync_round(round_id, "ranking")
                
                # Najpierw zaktualizuj wyniki z API do storage
                round_data = storage.data['rounds'].get(round_id, {})
                round_matches = round_data.get('matches', [])
                
                # Stwórz mapę meczów w storage (po match_id)
                storage_matches_map = {}
                for m in round_matches:
                    mid = str(m.get('match_id', ''))
                    storage_matches_map[mid] = m
                
                # Zaktualizuj wyniki meczów z API
                updated_results_count = 0
                if auto_sync_round:
                    logger.info(f"[Ranking per kolejka] Aktualizacja wyników z API: sprawdzam {len(selected_matches)} meczów z API dla rundy {round_id}")
                    for api_match in selected_matches:
                        match_id = str(api_match.get('match_id', ''))
                        api_home_goals = api_match.get('home_goals')
                        api_away_goals = api_match.get('away_goals')
                        
                        # Jeśli mecz z API ma wynik, zaktualizuj go w storage
                        if api_home_goals is not None and api_away_goals is not None:
                            if match_id in storage_matches_map:
                                storage_match = storage_matches_map[match_id]
                                storage_home_goals = storage_match.get('home_goals')
                                storage_away_goals = storage_match.get('away_goals')
                                
                                # Zaktualizuj wynik tylko jeśli się zmienił lub nie był zapisany
                                if storage_home_goals != api_home_goals or storage_away_goals != api_away_goals:
                                    logger.info(f"[Ranking per kolejka] ✅ Aktualizuję wynik meczu {match_id}: {storage_home_goals}-{storage_away_goals} -> {api_home_goals}-{api_away_goals}")
                                    storage_match['home_goals'] = api_home_goals
                                    storage_match['away_goals'] = api_away_goals
                                    storage_match['result_updated'] = datetime.now().isoformat()
                                    updated_results_count += 1
                
                # Zapisz zaktualizowane wyniki
                if updated_results_count > 0:
                    storage._save_data(force=True)
                    logger.info(f"[Ranking per kolejka] Zaktualizowano {updated_results_count} wyników meczów z API")
                    # Przeładuj dane po aktualizacji
                    storage.reload_data()
                    round_data = storage.data['rounds'].get(round_id, {})
                    round_matches = round_data.get('matches', [])
                
                # Teraz przelicz punkty dla wszystkich meczów z wynikami
                round_predictions = round_data.get('predictions', {})
                match_points_dict = round_data.get('match_points', {})
                
                # Sprawdź każdy mecz i przelicz punkty jeśli ma wynik, ale brakuje punktów
                recalculated_matches = 0
                for match in round_matches:
                    match_id = str(match.get('match_id', ''))
                    home_goals = match.get('home_goals')
                    away_goals = match.get('away_goals')
                    
                    # Jeśli mecz ma wynik, sprawdź czy są punkty dla wszystkich graczy z typami
                    if home_goals is not None and away_goals is not None:
                        # Sprawdź czy wszyscy gracze z typami mają punkty
                        needs_recalculation = False
                        players_with_predictions = 0
                        players_with_points = 0
                        
                        for player_name, player_predictions in round_predictions.items():
                            # Sprawdź czy gracz ma typ dla tego meczu
                            has_prediction = (match_id in player_predictions or 
                                            str(match_id) in player_predictions or
                                            (match_id.isdigit() and int(match_id) in player_predictions))
                            
                            if has_prediction:
                                players_with_predictions += 1
                                # Sprawdź czy gracz ma punkty dla tego meczu
                                player_points = match_points_dict.get(player_name, {})
                                has_points = (match_id in player_points or 
                                            str(match_id) in player_points or
                                            (match_id.isdigit() and int(match_id) in player_points))
                                
                                if has_points:
                                    players_with_points += 1
                                else:
                                    needs_recalculation = True
                        
                        # Jeśli brakuje punktów, przelicz je
                        if needs_recalculation or (players_with_predictions > 0 and players_with_points < players_with_predictions):
                            logger.info(f"[Ranking per kolejka] Automatyczne przeliczanie punktów dla meczu {match_id} w rundzie {round_id} (graczy z typami: {players_with_predictions}, z punktami: {players_with_points})")
                            try:
                                storage.update_match_result(
                                    round_id,
                                    match_id,
                                    int(home_goals),
                                    int(away_goals),
                                    save=False,
                                    recalculate_totals=False
                                )
                                recalculated_matches += 1
                            except Exception as e:
                                logger.error(f"[Ranking per kolejka] Błąd automatycznego przeliczania punktów dla meczu {match_id}: {e}")

                if recalculated_matches > 0:
                    storage._recalculate_player_totals(season_id=selected_season_id, save=False)
                    storage._save_data(force=True)
                
                # Przeładuj dane po przeliczeniu
                storage.reload_data()
                round_leaderboard = storage.get_round_leaderboard(round_id)
                
                if round_leaderboard:
                    # Pobierz mecze z rundy dla wyświetlenia typów
                    # Upewnij się, że mamy aktualne dane - pobierz round_data bezpośrednio z storage
                    storage.reload_data()
                    round_data = storage.data['rounds'].get(round_id, {})
                    matches = round_data.get('matches', [])
                    matches_map = {str(m.get('match_id', '')): m for m in matches}
                    
                    # Przygotuj dane do wyświetlenia (bez kolumny Typy)
                    round_leaderboard_data = []
                    for idx, player in enumerate(round_leaderboard, 1):
                        # Formatuj punkty za każdy mecz: 3+7+1+4+8+9=32
                        match_points = player.get('match_points', [])
                        if match_points:
                            points_str = '+'.join(str(p) for p in match_points)
                            if player['total_points'] > 0:
                                points_summary = f"{points_str}={player['total_points']}"
                            else:
                                # Jeśli suma to 0, pokaż tylko 0 (gracz nie typował)
                                points_summary = "0"
                        else:
                            points_summary = "0"
                        
                        round_leaderboard_data.append({
                            'Miejsce': idx,
                            'Gracz': player['player_name'],
                            'Punkty': points_summary,
                            'Suma': player['total_points'],
                            'Mecze': player['matches_count']
                        })
                    
                    df_round_leaderboard = pd.DataFrame(round_leaderboard_data)
                    st.dataframe(df_round_leaderboard, width='stretch', hide_index=True)
                    
                    # Dodaj expandery z typami dla każdego gracza
                    st.markdown("### 📋 Szczegóły typów")
                    for player in round_leaderboard:
                        player_name = player['player_name']
                        player_predictions = storage.get_player_predictions(player_name, round_id)
                        
                        if player_predictions:
                            # Sortuj mecze według daty - użyj matches_map lub selected_matches jako fallback
                            def get_match_date(mid):
                                match = matches_map.get(str(mid), {})
                                if not match or not match.get('match_date'):
                                    # Spróbuj znaleźć w selected_matches
                                    for api_match in selected_matches:
                                        if str(api_match.get('match_id', '')) == str(mid):
                                            return api_match.get('match_date', '')
                                return match.get('match_date', '')
                            
                            sorted_match_ids = sorted(
                                player_predictions.keys(),
                                key=lambda mid: get_match_date(mid)
                            )
                            
                            # Przygotuj dane do tabeli
                            types_table_data = []
                            # Pobierz match_points_dict bezpośrednio z round_data (upewnij się, że mamy aktualne dane)
                            # Pobierz round_data ponownie dla każdego gracza, żeby mieć pewność, że dane są aktualne
                            storage.reload_data()  # Upewnij się, że mamy najnowsze dane
                            current_round_data = storage.data['rounds'].get(round_id, {})
                            match_points_dict = current_round_data.get('match_points', {}).get(player_name, {})
                            
                            logger.info(f"DEBUG Ranking per kolejka: Gracz {player_name}, round_id={round_id}")
                            logger.info(f"  sorted_match_ids={sorted_match_ids} (count={len(sorted_match_ids)})")
                            logger.info(f"  match_points_dict keys={list(match_points_dict.keys())} (count={len(match_points_dict)})")
                            logger.info(f"  match_points_dict={match_points_dict}")
                            logger.info(f"  matches_map keys={list(matches_map.keys())} (count={len(matches_map)})")
                            logger.info(f"  selected_matches count={len(selected_matches)}")
                            
                            # Sprawdź które mecze mają wyniki
                            matches_with_results = []
                            for m in matches:
                                mid = str(m.get('match_id', ''))
                                if m.get('home_goals') is not None and m.get('away_goals') is not None:
                                    matches_with_results.append(mid)
                            logger.info(f"  Mecze z wynikami: {matches_with_results}")
                            logger.info(f"  Mecze z punktami w dict: {list(match_points_dict.keys())}")
                            
                            # Sprawdź które mecze z predictions nie są w matches_map
                            missing_matches = []
                            for match_id in sorted_match_ids:
                                match_id_str = str(match_id)
                                if match_id_str not in matches_map:
                                    # Sprawdź czy jest w selected_matches
                                    found_in_api = False
                                    for api_match in selected_matches:
                                        if str(api_match.get('match_id', '')) == match_id_str:
                                            found_in_api = True
                                            break
                                    if not found_in_api:
                                        missing_matches.append(match_id_str)
                            if missing_matches:
                                logger.warning(f"  UWAGA: Mecze z predictions nie znalezione w matches_map ani selected_matches: {missing_matches}")
                            
                            for match_id in sorted_match_ids:
                                # Spróbuj znaleźć mecz w matches_map
                                match = matches_map.get(str(match_id), {})
                                
                                # Jeśli nie znaleziono w matches_map lub brak nazw drużyn, spróbuj znaleźć w selected_matches z API
                                if not match or match.get('home_team_name') in [None, '?', ''] or match.get('away_team_name') in [None, '?', '']:
                                    for api_match in selected_matches:
                                        if str(api_match.get('match_id', '')) == str(match_id):
                                            match = api_match
                                            logger.info(f"Znaleziono mecz {match_id} w selected_matches z API: {match.get('home_team_name')} vs {match.get('away_team_name')}")
                                            break
                                
                                pred = player_predictions[match_id]
                                home_team = match.get('home_team_name', '?')
                                away_team = match.get('away_team_name', '?')
                                pred_home = pred.get('home', 0)
                                pred_away = pred.get('away', 0)
                                
                                # Pobierz punkty dla tego meczu
                                # Sprawdź zarówno string jak i int jako klucz (używamy get z domyślną wartością None, żeby odróżnić 0 od braku klucza)
                                points = None
                                if str(match_id) in match_points_dict:
                                    points = match_points_dict[str(match_id)]
                                elif match_id in match_points_dict:
                                    points = match_points_dict[match_id]
                                elif str(match_id).isdigit() and int(match_id) in match_points_dict:
                                    points = match_points_dict[int(match_id)]
                                else:
                                    points = 0
                                
                                # Sprawdź czy mecz ma wynik - jeśli nie, punkty powinny być 0
                                home_goals = match.get('home_goals')
                                away_goals = match.get('away_goals')
                                has_result = home_goals is not None and away_goals is not None
                                
                                logger.info(f"  match_id={match_id} (type={type(match_id).__name__}), str(match_id)={str(match_id)}, "
                                           f"str(match_id) in dict={str(match_id) in match_points_dict}, "
                                           f"match_id in dict={match_id in match_points_dict}, "
                                           f"has_result={has_result}, points={points}")
                                
                                # Debug: loguj jeśli nie znaleziono punktów dla meczu z wynikiem
                                if points == 0 and has_result and match_id in player_predictions:
                                    logger.warning(f"WARNING: Gracz {player_name}, match_id={match_id} (type={type(match_id).__name__}), "
                                                 f"match ma wynik {home_goals}-{away_goals} ale brak punktów! "
                                                 f"match_points_dict keys={list(match_points_dict.keys())}, "
                                                 f"match_points_dict={match_points_dict}")
                                
                                # Pobierz wynik meczu jeśli rozegrany
                                home_goals = match.get('home_goals')
                                away_goals = match.get('away_goals')
                                result = f"{home_goals}-{away_goals}" if home_goals is not None and away_goals is not None else "—"
                                
                                types_table_data.append({
                                    'Mecz': f"{home_team} vs {away_team}",
                                    'Typ': f"{pred_home}-{pred_away}",
                                    'Wynik': result,
                                    'Punkty': points
                                })
                            
                            if types_table_data:
                                with st.expander(f"👤 {player_name} - Typy i wyniki", expanded=True):
                                    df_types = pd.DataFrame(types_table_data)
                                    st.dataframe(df_types, width='stretch', hide_index=True)
                                    total_points = sum(row['Punkty'] for row in types_table_data)
                                    st.caption(f"**Suma punktów: {total_points}**")
                                    
                                    # Sekcja ręcznej edycji punktów
                                    st.markdown("---")
                                    st.markdown("### ✏️ Ręczna edycja punktów")
                                    st.caption("💡 Możesz ręcznie ustawić punkty dla każdego meczu (w tym ujemne wartości)")
                                    
                                    # Przygotuj dane do edycji
                                    manual_points_data = {}
                                    for idx, match_id in enumerate(sorted_match_ids):
                                        # Spróbuj znaleźć mecz w matches_map
                                        match = matches_map.get(str(match_id), {})
                                        
                                        # Jeśli nie znaleziono w matches_map lub brak nazw drużyn, spróbuj znaleźć w selected_matches z API
                                        if not match or match.get('home_team_name') in [None, '?', ''] or match.get('away_team_name') in [None, '?', '']:
                                            for api_match in selected_matches:
                                                if str(api_match.get('match_id', '')) == str(match_id):
                                                    match = api_match
                                                    logger.info(f"Ręczna edycja: Znaleziono mecz {match_id} w selected_matches z API: {match.get('home_team_name')} vs {match.get('away_team_name')}")
                                                    break
                                        
                                        home_team = match.get('home_team_name', '?')
                                        away_team = match.get('away_team_name', '?')
                                        
                                        # Pobierz aktualne punkty
                                        current_points = None
                                        if str(match_id) in match_points_dict:
                                            current_points = match_points_dict[str(match_id)]
                                        elif match_id in match_points_dict:
                                            current_points = match_points_dict[match_id]
                                        elif str(match_id).isdigit() and int(match_id) in match_points_dict:
                                            current_points = match_points_dict[int(match_id)]
                                        else:
                                            current_points = 0
                                        
                                        # Sprawdź czy punkty są ręcznie ustawione
                                        is_manual = storage.is_manual_points(round_id, match_id, player_name)
                                        
                                        col_match, col_points, col_manual = st.columns([3, 2, 1])
                                        with col_match:
                                            st.write(f"**{home_team} vs {away_team}**")
                                        with col_points:
                                            new_points = st.number_input(
                                                "Punkty:",
                                                value=int(current_points),
                                                min_value=None,  # Pozwól na ujemne wartości
                                                max_value=None,
                                                step=1,
                                                key=f"manual_points_{player_name}_{round_id}_{match_id}",
                                                label_visibility="collapsed"
                                            )
                                            # Zapisz wartość do słownika
                                            manual_points_data[match_id] = new_points
                                        with col_manual:
                                            if is_manual:
                                                st.caption("✏️ Ręczne")
                                            else:
                                                st.caption("🤖 Auto")
                                    
                                    # Przycisk zapisu wszystkich punktów
                                    if st.button("💾 Zapisz wszystkie punkty", type="primary", key=f"save_all_points_{player_name}_{round_id}", width='stretch'):
                                        saved_count = 0
                                        for match_id, new_points in manual_points_data.items():
                                            # Pobierz aktualne punkty
                                            current_points = None
                                            if str(match_id) in match_points_dict:
                                                current_points = match_points_dict[str(match_id)]
                                            elif match_id in match_points_dict:
                                                current_points = match_points_dict[match_id]
                                            elif str(match_id).isdigit() and int(match_id) in match_points_dict:
                                                current_points = match_points_dict[int(match_id)]
                                            else:
                                                current_points = 0
                                            
                                            # Zapisz tylko jeśli wartość się zmieniła
                                            if new_points != current_points:
                                                storage.set_manual_points(round_id, match_id, player_name, new_points, season_id=selected_season_id)
                                                saved_count += 1
                                        
                                        if saved_count > 0:
                                            storage.flush_save()
                                            st.success(f"✅ Zapisano punkty dla {saved_count} meczów")
                                            # NIE odświeżamy - użytkownik może kontynuować pracę
                                        else:
                                            st.info("ℹ️ Brak zmian do zapisania")
                                    
                                    # Podsumowanie dla logów (wewnątrz bloku gdzie types_table_data jest zdefiniowane)
                                    zero_points_count = sum(1 for row in types_table_data if row['Punkty'] == 0)
                                    matches_with_results = sum(1 for row in types_table_data if row['Wynik'] != '—')
                                    logger.info(f"PODSUMOWANIE dla {player_name} w {round_id}:")
                                    logger.info(f"  Łącznie meczów: {len(types_table_data)}")
                                    logger.info(f"  Mecze z wynikami: {matches_with_results}")
                                    logger.info(f"  Mecze z 0 punktami: {zero_points_count}")
                                    logger.info(f"  Suma punktów: {total_points}")
                                    logger.info(f"  Szczegóły wszystkich meczów:")
                                    for row in types_table_data:
                                        logger.info(f"    {row['Mecz']}: Typ {row['Typ']}, Wynik {row['Wynik']}, Punkty {row['Punkty']}")
                                    if zero_points_count > 0 and matches_with_results < len(types_table_data):
                                        logger.warning(f"  UWAGA: {zero_points_count} meczów ma 0 punktów, ale tylko {matches_with_results} meczów ma wyniki")
                    
                    # Wykres rankingu per kolejka
                    if len(round_leaderboard) > 0:
                        fig = px.bar(
                            df_round_leaderboard.head(10),
                            x='Gracz',
                            y='Suma',
                            title=f"Top 10 - Ranking kolejki {round_number}",
                            labels={'Suma': 'Punkty', 'Gracz': 'Gracz'},
                            color='Suma',
                            color_continuous_scale='viridis'
                        )
                        fig.update_layout(xaxis_tickangle=-45, height=400)
                        st.plotly_chart(fig, use_container_width=True, key=f"ranking_round_{round_number}_chart")
                else:
                    st.info("📊 Brak danych do wyświetlenia dla tej kolejki")
        
        # Ranking wszechczasów
        with ranking_tab3:
            st.markdown("### 🌟 Ranking wszechczasów")
            st.info("💡 Suma punktów ze wszystkich sezonów")
            
            exclude_worst = st.checkbox("Odrzuć najgorszy wynik każdego gracza z każdego sezonu", value=True, key="exclude_worst_alltime")
            
            # Przelicz punkty dla aktywnego sezonu przed pobraniem rankingu wszechczasów
            # (aby mieć aktualne dane dla sezonu 80)
            if selected_season_id and not storage.is_season_archived(season_id=selected_season_id):
                logger.info(f"Przeliczam punkty dla sezonu {selected_season_id} przed wyświetleniem rankingu wszechczasów")
                storage._recalculate_player_totals(season_id=selected_season_id)
                storage._save_data(force=True)  # Zapisz zaktualizowane total_points
                logger.info(f"Zapisano zaktualizowane punkty dla sezonu {selected_season_id}")
            
            all_time_leaderboard = get_all_time_leaderboard(exclude_worst=exclude_worst)
            
            if all_time_leaderboard:
                # Przygotuj dane do wyświetlenia
                leaderboard_data = []
                for idx, player in enumerate(all_time_leaderboard, 1):
                    # Formatuj punkty z sezonów: Sezon 77: 346, Sezon 78: 459, ...
                    seasons_str = ", ".join([f"Sezon {sid.replace('season_', '')}: {pts}" for sid, pts in sorted(player['seasons_data'].items(), key=lambda x: int(x[0].replace('season_', '')))])
                    
                    leaderboard_data.append({
                        'Miejsce': idx,
                        'Gracz': player['player_name'],
                        'Punkty z sezonów': seasons_str,
                        'Suma': player['total_points'],
                        'Sezony': player['seasons_played'],
                        'Rundy': player['rounds_played']
                    })
                
                df_leaderboard = pd.DataFrame(leaderboard_data)
                st.dataframe(df_leaderboard, width='stretch', hide_index=True)
                
                # Wykres rankingu wszechczasów
                if len(all_time_leaderboard) > 0:
                    fig = px.bar(
                        df_leaderboard.head(10),
                        x='Gracz',
                        y='Suma',
                        title="Top 10 - Ranking wszechczasów",
                        labels={'Suma': 'Punkty', 'Gracz': 'Gracz'},
                        color='Suma',
                        color_continuous_scale='YlOrRd'
                    )
                    fig.update_layout(xaxis_tickangle=-45, height=400)
                    st.plotly_chart(fig, use_container_width=True, key="ranking_alltime_chart")
                    
                    # Statystyki
                    col1, col2, col3, col4 = st.columns(4)
                    with col1:
                        st.metric("Liczba graczy", len(all_time_leaderboard))
                    with col2:
                        if all_time_leaderboard:
                            st.metric("Najwięcej punktów", all_time_leaderboard[0]['total_points'])
                    with col3:
                        if all_time_leaderboard:
                            avg_points = sum(p['total_points'] for p in all_time_leaderboard) / len(all_time_leaderboard)
                            st.metric("Średnia punktów", f"{avg_points:.1f}")
                    with col4:
                        if all_time_leaderboard:
                            total_seasons = sum(p['seasons_played'] for p in all_time_leaderboard)
                            st.metric("Łącznie sezonów", total_seasons)
            else:
                st.info("📊 Brak danych do wyświetlenia")
        
        # Wybór rundy - pod Rankingiem (dla sekcji wprowadzania typów)
        st.markdown("---")
        st.subheader("📅 Wybór rundy")
        
        # Znajdź pierwszą nie rozegraną kolejkę (najstarszą nie rozegraną - domyślnie po zalogowaniu)
        default_round_idx = 0
        # Przeszukaj od końca (od najstarszej do najnowszej), aby znaleźć najstarszą nie rozegraną
        for idx in range(len(filtered_rounds) - 1, -1, -1):
            date, matches = filtered_rounds[idx]
            # Sprawdź czy kolejka ma rozegrane mecze
            has_played = any(m.get('home_goals') is not None and m.get('away_goals') is not None for m in matches)
            if not has_played:
                default_round_idx = idx
                break  # Weź najstarszą nie rozegraną kolejkę
        
        # Sprawdź czy jest zapisany wybór rundy w session_state (synchronizacja z rankingiem)
        if 'selected_round_idx' in st.session_state:
            default_round_idx = st.session_state.selected_round_idx
        
        # Numeruj kolejki według daty asc (numer 1 = najstarsza), ale wyświetlaj sort desc (najnowsza pierwsza)
        round_options = []
        for date, matches in filtered_rounds:
            round_number = date_to_round_number[date]  # Numer według daty asc
            round_options.append(f"Kolejka {round_number} - {date} ({len(matches)} meczów)")
        
        selected_round_idx = st.selectbox("Wybierz rundę:", range(len(round_options)), index=default_round_idx, format_func=lambda x: round_options[x], key="round_select_main")
        
        # Zapisz wybór rundy w session_state (synchronizacja z rankingiem)
        st.session_state.selected_round_idx = selected_round_idx
        
        if selected_round_idx is not None:
            selected_round_date, selected_matches = filtered_rounds[selected_round_idx]
            round_number = date_to_round_number[selected_round_date]  # Numer kolejki według daty asc (1 = najstarsza)
            round_id = f"round_{selected_round_date}"
            
            # Dodaj rundę do storage jeśli nie istnieje
            if round_id not in storage.data['rounds']:
                # Sezon zostanie automatycznie utworzony w add_round jeśli nie istnieje
                storage.add_round(selected_season_id, round_id, selected_matches, selected_round_date)
            
            # Wyświetl mecze w rundzie - tabela na górze dla czytelności
            st.subheader(f"⚽ Kolejka {round_number} - {selected_round_date}")
            
            # Przycisk do przeliczania punktów
            col_refresh, col_info = st.columns([1, 4])
            with col_refresh:
                if st.button("🔄 Przelicz punkty", type="primary", width='stretch', key=f"recalculate_{round_id}"):
                    with st.spinner("Pobieranie wyników i przeliczanie punktów..."):
                        # Przeładuj dane
                        storage.reload_data()
                        st.session_state[f"_last_auto_sync_main_{round_id}"] = datetime.now().timestamp()
                        st.session_state[f"_last_auto_sync_ranking_{round_id}"] = datetime.now().timestamp()
                        round_data = storage.data['rounds'].get(round_id, {})
                        round_matches = round_data.get('matches', [])
                        
                        # Stwórz mapę meczów w storage (po match_id)
                        storage_matches_map = {}
                        for match in round_matches:
                            match_id = str(match.get('match_id', ''))
                            storage_matches_map[match_id] = match
                        
                        # Zaktualizuj wyniki meczów z API
                        logger.info(f"Sprawdzam {len(selected_matches)} meczów z API dla rundy {round_id}")
                        updated_count = 0
                        for api_match in selected_matches:
                            match_id = str(api_match.get('match_id', ''))
                            api_home_goals = api_match.get('home_goals')
                            api_away_goals = api_match.get('away_goals')
                            
                            logger.info(f"API mecz {match_id}: home_goals={api_home_goals}, away_goals={api_away_goals}")
                            
                            # Jeśli mecz z API ma wynik, zaktualizuj go w storage
                            if api_home_goals is not None and api_away_goals is not None:
                                if match_id in storage_matches_map:
                                    storage_match = storage_matches_map[match_id]
                                    storage_home_goals = storage_match.get('home_goals')
                                    storage_away_goals = storage_match.get('away_goals')
                                    
                                    logger.info(f"Storage mecz {match_id}: home_goals={storage_home_goals}, away_goals={storage_away_goals}")
                                    
                                    # Zaktualizuj wynik tylko jeśli się zmienił lub nie był zapisany
                                    if storage_home_goals != api_home_goals or storage_away_goals != api_away_goals:
                                        logger.info(f"✅ Aktualizuję wynik meczu {match_id} w rundzie {round_id}: {storage_home_goals}-{storage_away_goals} -> {api_home_goals}-{api_away_goals}")
                                        storage_match['home_goals'] = api_home_goals
                                        storage_match['away_goals'] = api_away_goals
                                        storage_match['result_updated'] = datetime.now().isoformat()
                                        updated_count += 1
                                else:
                                    # Mecz nie jest w storage - sprawdź czy gracze mają typy dla niego
                                    predictions = round_data.get('predictions', {})
                                    has_predictions = False
                                    for player_name, player_predictions in predictions.items():
                                        if match_id in player_predictions or str(match_id) in player_predictions:
                                            has_predictions = True
                                            break
                                    
                                    if has_predictions:
                                        # Dodaj mecz do storage z danymi z API
                                        logger.warning(f"⚠️ Mecz {match_id} z API nie został znaleziony w storage, ale gracze mają typy - dodaję mecz do storage")
                                        new_match = api_match.copy()
                                        new_match['home_goals'] = api_home_goals
                                        new_match['away_goals'] = api_away_goals
                                        new_match['result_updated'] = datetime.now().isoformat()
                                        round_matches.append(new_match)
                                        storage_matches_map[match_id] = new_match
                                        updated_count += 1
                                        logger.info(f"✅ Dodano mecz {match_id} do storage z wynikiem {api_home_goals}-{api_away_goals}")
                                    else:
                                        logger.warning(f"⚠️ Mecz {match_id} z API nie został znaleziony w storage i gracze nie mają typów - pomijam")
                            else:
                                logger.info(f"⏭️ Mecz {match_id} z API nie ma wyniku (home_goals={api_home_goals}, away_goals={api_away_goals})")
                        
                        if updated_count > 0:
                            storage._save_data(force=True)  # Zapisz natychmiast
                            logger.info(f"Zaktualizowano {updated_count} wyników meczów")
                        
                        # Przeładuj dane po aktualizacji wyników
                        storage.reload_data()
                        round_data = storage.data['rounds'].get(round_id, {})
                        round_matches = round_data.get('matches', [])
                        
                        # Przelicz punkty dla wszystkich meczów z wynikami w rundzie
                        # Użyj zarówno meczów z storage jak i z API (aby nie pominąć żadnego)
                        calculated_count = 0
                        logger.info(f"Przeliczanie punktów dla rundy {round_id}: {len(round_matches)} meczów w storage, {len(selected_matches)} meczów w API")
                        
                        # Stwórz zbiór przetworzonych meczów, aby nie przeliczać dwa razy
                        processed_match_ids = set()
                        
                        # Najpierw przelicz mecze z storage
                        for match in round_matches:
                            match_id = str(match.get('match_id', ''))
                            home_goals = match.get('home_goals')
                            away_goals = match.get('away_goals')
                            
                            logger.info(f"Sprawdzam mecz z storage {match_id}: home_goals={home_goals}, away_goals={away_goals}")
                            
                            # Jeśli mecz ma wynik, przelicz punkty (update_match_result sprawdzi czy są typy)
                            if home_goals is not None and away_goals is not None:
                                try:
                                    logger.info(f"Wywołuję update_match_result dla meczu {match_id} z wynikiem {home_goals}-{away_goals}")
                                    storage.update_match_result(
                                        round_id,
                                        match_id,
                                        int(home_goals),
                                        int(away_goals),
                                        save=False,
                                        recalculate_totals=False
                                    )
                                    calculated_count += 1
                                    processed_match_ids.add(match_id)
                                    logger.info(f"✅ Przeliczono punkty dla meczu {match_id} w rundzie {round_id} (wynik: {home_goals}-{away_goals})")
                                except Exception as e:
                                    logger.error(f"❌ Błąd przeliczania punktów dla meczu {match_id}: {e}", exc_info=True)
                            else:
                                logger.info(f"⏭️ Mecz {match_id} nie ma wyniku (home_goals={home_goals}, away_goals={away_goals}) - pomijam")
                        
                        # Teraz przelicz mecze z API, które nie były w storage lub nie zostały jeszcze przeliczone
                        for api_match in selected_matches:
                            match_id = str(api_match.get('match_id', ''))
                            
                            # Pomiń jeśli już przetworzony
                            if match_id in processed_match_ids:
                                continue
                            
                            api_home_goals = api_match.get('home_goals')
                            api_away_goals = api_match.get('away_goals')
                            
                            logger.info(f"Sprawdzam mecz z API {match_id}: home_goals={api_home_goals}, away_goals={api_away_goals}")
                            
                            # Jeśli mecz z API ma wynik, przelicz punkty
                            if api_home_goals is not None and api_away_goals is not None:
                                try:
                                    logger.info(f"Wywołuję update_match_result dla meczu z API {match_id} z wynikiem {api_home_goals}-{api_away_goals}")
                                    storage.update_match_result(
                                        round_id,
                                        match_id,
                                        int(api_home_goals),
                                        int(api_away_goals),
                                        save=False,
                                        recalculate_totals=False
                                    )
                                    calculated_count += 1
                                    processed_match_ids.add(match_id)
                                    logger.info(f"✅ Przeliczono punkty dla meczu z API {match_id} w rundzie {round_id} (wynik: {api_home_goals}-{api_away_goals})")
                                except Exception as e:
                                    logger.error(f"❌ Błąd przeliczania punktów dla meczu z API {match_id}: {e}", exc_info=True)
                            else:
                                logger.info(f"⏭️ Mecz z API {match_id} nie ma wyniku (home_goals={api_home_goals}, away_goals={api_away_goals}) - pomijam")
                        
                        if calculated_count > 0:
                            storage._recalculate_player_totals(season_id=selected_season_id, save=False)
                            storage._save_data(force=True)

                        if calculated_count > 0:
                            st.success(f"✅ Przeliczono punkty dla {calculated_count} meczów")
                        else:
                            st.info("ℹ️ Brak meczów z wynikami do przeliczenia")
                        
                        # Odśwież stronę
                        st.cache_data.clear()
                        st.rerun()
            
            with col_info:
                st.caption("💡 Kliknij, aby pobrać najnowsze wyniki z API i przeliczyć punkty dla tej kolejki")
            
            # Sprawdź czy mecze są już rozegrane
            matches_played = []
            matches_upcoming = []
            
            for match in selected_matches:
                if match.get('home_goals') is not None and match.get('away_goals') is not None:
                    matches_played.append(match)
                else:
                    matches_upcoming.append(match)
            
            if should_auto_sync_round(round_id, "main"):
                # Najpierw zaktualizuj wszystkie wyniki z API do storage
                storage.reload_data()
                round_data = storage.data['rounds'].get(round_id, {})
                round_matches = round_data.get('matches', [])
                
                # Stwórz mapę meczów w storage (po match_id)
                storage_matches_map = {}
                for m in round_matches:
                    mid = str(m.get('match_id', ''))
                    storage_matches_map[mid] = m
                
                # Zaktualizuj wyniki meczów z API
                updated_results_count = 0
                logger.info(f"Aktualizacja wyników z API: sprawdzam {len(selected_matches)} meczów z API dla rundy {round_id}")
                for api_match in selected_matches:
                    match_id = str(api_match.get('match_id', ''))
                    api_home_goals = api_match.get('home_goals')
                    api_away_goals = api_match.get('away_goals')
                    
                    logger.info(f"API mecz {match_id}: home_goals={api_home_goals}, away_goals={api_away_goals}")
                    
                    # Jeśli mecz z API ma wynik, zaktualizuj go w storage
                    if api_home_goals is not None and api_away_goals is not None:
                        if match_id in storage_matches_map:
                            storage_match = storage_matches_map[match_id]
                            storage_home_goals = storage_match.get('home_goals')
                            storage_away_goals = storage_match.get('away_goals')
                            
                            logger.info(f"Storage mecz {match_id}: home_goals={storage_home_goals}, away_goals={storage_away_goals}")
                            
                            # Zaktualizuj wynik tylko jeśli się zmienił lub nie był zapisany
                            if storage_home_goals != api_home_goals or storage_away_goals != api_away_goals:
                                logger.info(f"✅ Aktualizuję wynik meczu {match_id}: {storage_home_goals}-{storage_away_goals} -> {api_home_goals}-{api_away_goals}")
                                storage_match['home_goals'] = api_home_goals
                                storage_match['away_goals'] = api_away_goals
                                storage_match['result_updated'] = datetime.now().isoformat()
                                updated_results_count += 1
                            else:
                                logger.info(f"⏭️ Wynik meczu {match_id} już jest aktualny: {storage_home_goals}-{storage_away_goals}")
                        else:
                            logger.warning(f"⚠️ Mecz {match_id} z API nie został znaleziony w storage_matches_map (keys: {list(storage_matches_map.keys())})")
                    else:
                        logger.info(f"⏭️ Mecz {match_id} z API nie ma wyniku (home_goals={api_home_goals}, away_goals={api_away_goals})")
                
                # Zapisz zaktualizowane wyniki
                if updated_results_count > 0:
                    storage._save_data(force=True)
                    logger.info(f"Zaktualizowano {updated_results_count} wyników meczów z API")
                    # Przeładuj dane po aktualizacji
                    storage.reload_data()
                    round_data = storage.data['rounds'].get(round_id, {})
                    round_matches = round_data.get('matches', [])
                
                # Teraz przelicz punkty dla wszystkich meczów z wynikami
                round_predictions = round_data.get('predictions', {})
                match_points_dict = round_data.get('match_points', {})
                recalculated_matches = 0
                
                for match in round_matches:
                    match_id = str(match.get('match_id', ''))
                    home_goals = match.get('home_goals')
                    away_goals = match.get('away_goals')
                    
                    if home_goals is not None and away_goals is not None:
                        # Sprawdź czy wszyscy gracze z typami mają punkty dla tego meczu
                        needs_recalculation = False
                        players_with_predictions = 0
                        players_with_points = 0
                        
                        for player_name, player_predictions in round_predictions.items():
                            # Sprawdź czy gracz ma typ dla tego meczu
                            has_prediction = (match_id in player_predictions or 
                                            str(match_id) in player_predictions or
                                            (match_id.isdigit() and int(match_id) in player_predictions))
                            
                            if has_prediction:
                                players_with_predictions += 1
                                # Sprawdź czy gracz ma punkty dla tego meczu
                                player_points = match_points_dict.get(player_name, {})
                                has_points = (match_id in player_points or 
                                            str(match_id) in player_points or
                                            (match_id.isdigit() and int(match_id) in player_points))
                                
                                if has_points:
                                    players_with_points += 1
                                else:
                                    needs_recalculation = True
                        
                        # Jeśli nie wszyscy gracze z typami mają punkty, przelicz je
                        if needs_recalculation or (players_with_predictions > 0 and players_with_points < players_with_predictions):
                            logger.info(f"Brak punktów dla meczu {match_id} - przeliczam punkty (graczy z typami: {players_with_predictions}, z punktami: {players_with_points})")
                            try:
                                storage.update_match_result(
                                    round_id,
                                    match_id,
                                    int(home_goals),
                                    int(away_goals),
                                    save=False,
                                    recalculate_totals=False
                                )
                                recalculated_matches += 1
                            except Exception as e:
                                logger.error(f"Błąd przeliczania punktów dla meczu {match_id}: {e}", exc_info=True)

                if recalculated_matches > 0:
                    storage._recalculate_player_totals(season_id=selected_season_id, save=False)
                    storage._save_data(force=True)
            
            # Przygotuj dane do tabeli
            matches_table_data = []
            for match in selected_matches:
                home_team = match.get('home_team_name', 'Unknown')
                away_team = match.get('away_team_name', 'Unknown')
                match_date = match.get('match_date', '')
                home_goals = match.get('home_goals')
                away_goals = match.get('away_goals')
                match_id = str(match.get('match_id', ''))
                
                # Status meczu
                status = "⏳ Oczekuje"
                if home_goals is not None and away_goals is not None:
                    status = f"✅ {home_goals}-{away_goals}"
                else:
                    try:
                        match_dt = datetime.strptime(match_date, "%Y-%m-%d %H:%M:%S")
                        if datetime.now() >= match_dt:
                            status = "⏰ Rozpoczęty"
                    except:
                        pass
                
                matches_table_data.append({
                    'Gospodarz': home_team,
                    'Gość': away_team,
                    'Data': match_date,
                    'Status': status
                })
            
            # Wyświetl tabelę z meczami
            if matches_table_data:
                df_matches = pd.DataFrame(matches_table_data)
                st.dataframe(df_matches, width='stretch', hide_index=True)
            
            
            # Sekcja wprowadzania i korygowania typów - wszystko w jednym miejscu
            st.markdown("---")
            st.subheader("✍️ Wprowadzanie i korygowanie typów")
            
            # Opcja wprowadzania typów historycznych
            allow_historical = st.checkbox("Pozwól na wprowadzanie typów historycznych (dla rozegranych meczów)", 
                                          value=False, 
                                          help="Jeśli zaznaczone, możesz wprowadzać typy dla meczów, które już się odbyły")
            
            # Wybór gracza - wszystko przefiltrowane przez jednego gracza
            col_player1, col_player2 = st.columns([3, 1])
            
            with col_player1:
                # Lista graczy z sezonu
                all_players_list = storage.get_season_players_list(season_id=selected_season_id)
                if all_players_list:
                    selected_player = st.selectbox("Wybierz gracza:", all_players_list, key="tipper_selected_player")
                else:
                    selected_player = None
                    st.info("📊 Brak graczy w sezonie. Dodaj nowego gracza.")
            
            with col_player2:
                st.markdown("<br>", unsafe_allow_html=True)  # Spacing
                col_add, col_remove, col_copy = st.columns(3)
                with col_add:
                    add_new_player = st.button("➕ Dodaj", key="tipper_add_new_player_btn", width='stretch')
                with col_remove:
                    if all_players_list and selected_player:
                        remove_player = st.button("🗑️ Usuń", key="tipper_remove_player_btn", width='stretch')
                    else:
                        remove_player = False
                with col_copy:
                    # Przycisk kopiowania graczy z poprzedniego sezonu
                    copy_players_btn = st.button("📋 Kopiuj", key="tipper_copy_players_btn", width='stretch', help="Kopiuj graczy z poprzedniego sezonu")
            
            # Dodawanie nowego gracza
            if add_new_player:
                with st.expander("➕ Dodaj nowego gracza", expanded=True):
                    new_player_name = st.text_input("Nazwa nowego gracza:", key="tipper_new_player_name")
                    if st.button("💾 Zapisz", key="tipper_save_new_player"):
                        if new_player_name:
                            if storage.add_player(new_player_name, season_id=selected_season_id):
                                storage.flush_save()  # Wymuś natychmiastowy zapis
                                st.success(f"✅ Dodano gracza: {new_player_name} do sezonu {selected_season_id.replace('season_', '')}")
                                st.rerun()
                            else:
                                st.warning("⚠️ Gracz już istnieje w tym sezonie")
            
            # Kopiowanie graczy z poprzedniego sezonu
            if copy_players_btn:
                # Znajdź poprzedni sezon (najwyższy numer przed obecnym)
                current_season_num = int(selected_season_id.replace("season_", "")) if selected_season_id.startswith("season_") else 0
                available_seasons_nums = [int(s.replace("season_", "")) for s in available_seasons if s.startswith("season_")]
                previous_seasons = [s for s in available_seasons_nums if s < current_season_num]
                
                if previous_seasons:
                    previous_season_num = max(previous_seasons)
                    previous_season_id = f"season_{previous_season_num}"
                    
                    # Załaduj poprzedni sezon i skopiuj graczy
                    previous_storage = TipperStorage(season_id=previous_season_id)
                    previous_players = previous_storage.get_season_players_list(season_id=previous_season_id)
                    
                    if previous_players:
                        copied_count = 0
                        skipped_count = 0
                        for player_name in previous_players:
                            if storage.add_player(player_name, season_id=selected_season_id):
                                copied_count += 1
                            else:
                                skipped_count += 1  # Gracz już istnieje
                        
                        if copied_count > 0:
                            storage.flush_save()
                            if skipped_count > 0:
                                st.success(f"✅ Skopiowano {copied_count} graczy z sezonu {previous_season_num} ({skipped_count} już istnieje)")
                            else:
                                st.success(f"✅ Skopiowano {copied_count} graczy z sezonu {previous_season_num}")
                            st.rerun()
                        else:
                            st.warning(f"⚠️ Wszyscy gracze z sezonu {previous_season_num} już istnieją w tym sezonie")
                    else:
                        st.warning(f"⚠️ Brak graczy w sezonie {previous_season_num}")
                else:
                    st.warning("⚠️ Nie znaleziono poprzedniego sezonu")
            
            # Usuwanie gracza
            if remove_player and selected_player:
                if storage.remove_player(selected_player, season_id=selected_season_id):
                    storage.flush_save()  # Wymuś natychmiastowy zapis
                    st.success(f"✅ Usunięto gracza: {selected_player} z sezonu {selected_season_id.replace('season_', '')}")
                    st.rerun()
                else:
                    st.error("❌ Nie udało się usunąć gracza")
            
            if selected_player:
                # Upewnij się, że runda istnieje w storage (ważne dla nowych sezonów)
                if round_id not in storage.data.get('rounds', {}):
                    storage.add_round(selected_season_id, round_id, selected_matches, selected_round_date)
                    storage.reload_data()
                
                # Sprawdź czy trzeba odświeżyć dane
                needs_refresh = st.session_state.get('_refresh_predictions', False)
                if needs_refresh:
                    storage.reload_data()
                
                # Sprawdź czy trzeba odświeżyć dane (po zapisie typów)
                needs_refresh = st.session_state.get('_refresh_predictions', False)
                if needs_refresh:
                    # Przeładuj dane przed pobraniem typów (aby mieć aktualne dane po zapisie)
                    storage.reload_data()
                    logger.info("Odświeżam dane po zapisie typów")
                    # Wyczyść flagę po użyciu
                    st.session_state['_refresh_predictions'] = False
                else:
                    # Przeładuj dane przed pobraniem typów (aby mieć aktualne dane)
                    storage.reload_data()
                
                # Pobierz istniejące typy gracza dla tej rundy
                existing_predictions = storage.get_player_predictions(selected_player, round_id, season_id=selected_season_id)
                
                st.markdown(f"### Typy dla: **{selected_player}**")
                
                # Tryb wprowadzania: pojedyncze i bulk obok siebie
                col_single, col_bulk = st.columns(2)
                
                with col_single:
                    st.markdown("### Pojedyncze mecze")
                    # Wyświetl formularz dla każdego meczu
                    st.markdown("**Wprowadź typy dla każdego meczu:**")
                    
                    for idx, match in enumerate(selected_matches):
                        match_id = str(match.get('match_id', ''))
                        home_team = match.get('home_team_name', 'Unknown')
                        away_team = match.get('away_team_name', 'Unknown')
                        match_date = match.get('match_date', '')
                        home_goals = match.get('home_goals')
                        away_goals = match.get('away_goals')
                        
                        # Sprawdź czy mecz już się rozpoczął
                        can_edit = True
                        is_historical = False
                        if match_date:
                            try:
                                match_dt = datetime.strptime(match_date, "%Y-%m-%d %H:%M:%S")
                                if datetime.now() >= match_dt:
                                    is_historical = True
                                    can_edit = allow_historical
                            except:
                                pass
                        
                        # Pobierz istniejący typ
                        has_existing = match_id in existing_predictions
                        if has_existing:
                            existing_pred = existing_predictions[match_id]
                            default_value = f"{existing_pred.get('home', 0)}-{existing_pred.get('away', 0)}"
                        else:
                            default_value = "0-0"
                        
                        # Oblicz punkty jeśli mecz rozegrany
                        points_display = ""
                        if home_goals is not None and away_goals is not None and has_existing:
                            pred_home = existing_pred.get('home', 0)
                            pred_away = existing_pred.get('away', 0)
                            points = tipper.calculate_points((pred_home, pred_away), (int(home_goals), int(away_goals)))
                            points_display = f" | **Punkty: {points}**"
                        
                        col1, col2, col3 = st.columns([3, 1.5, 1])
                        with col1:
                            status_icon = "✅" if has_existing else "❌"
                            status_text = "Typ istnieje" if has_existing else "Brak typu"
                            result_text = f" ({home_goals}-{away_goals})" if home_goals is not None and away_goals is not None else ""
                            st.write(f"{status_icon} **{home_team}** vs **{away_team}**{result_text} {points_display}")
                        with col2:
                            if can_edit:
                                input_key = f"tipper_pred_{selected_player}_{match_id}"
                                
                                # Sprawdź czy są dane z bulk do wypełnienia
                                bulk_fill_key = f"bulk_fill_{selected_player}_{round_id}"
                                bulk_fill_data = st.session_state.get(bulk_fill_key, {})
                                
                                # Określ wartość początkową - priorytet: bulk > istniejąca wartość > domyślna
                                initial_value = default_value
                                
                                # Sprawdź czy są dane z bulk dla tego meczu (sprawdź zarówno string jak i int)
                                match_id_str = str(match_id)
                                bulk_value = None
                                if match_id_str in bulk_fill_data:
                                    bulk_value = bulk_fill_data[match_id_str]
                                elif match_id in bulk_fill_data:
                                    bulk_value = bulk_fill_data[match_id]
                                
                                if bulk_value:
                                    # Użyj wartości z bulk (nadpisuje wszystko)
                                    initial_value = bulk_value
                                    logger.info(f"Bulk fill: Użyję wartość '{bulk_value}' dla meczu {match_id_str}")
                                    # Zapisuj wartość do session_state PRZED utworzeniem widgetu
                                    # To zapewni, że widget będzie miał poprawną wartość
                                    st.session_state[input_key] = bulk_value
                                    # NIE usuwaj danych z bulk tutaj - zostaną użyte do wypełnienia wszystkich pól
                                    # Dane będą usunięte po wyświetleniu wszystkich pól (na końcu sekcji)
                                elif input_key in st.session_state:
                                    # Jeśli nie ma bulk, użyj istniejącej wartości z session_state
                                    initial_value = st.session_state[input_key]
                                # Jeśli flaga odświeżenia jest ustawiona, użyj wartości domyślnej
                                elif needs_refresh:
                                    initial_value = default_value
                                    # Usuń wartość z session_state jeśli istnieje
                                    if input_key in st.session_state:
                                        del st.session_state[input_key]
                                
                                # Użyj value w st.text_input - Streamlit automatycznie zsynchronizuje to z session_state
                                # Jeśli wartość jest w session_state (np. z bulk), użyj jej zamiast initial_value
                                if input_key in st.session_state:
                                    # Użyj wartości z session_state (może być z bulk lub z poprzedniego wprowadzenia)
                                    pred_input = st.text_input(
                                        f"Typ:",
                                        value=st.session_state[input_key],
                                        key=input_key,
                                        label_visibility="collapsed"
                                    )
                                else:
                                    # Użyj initial_value (domyślna wartość)
                                    pred_input = st.text_input(
                                        f"Typ:",
                                        value=initial_value,
                                        key=input_key,
                                        label_visibility="collapsed"
                                    )
                                
                                # Streamlit automatycznie aktualizuje session_state[input_key] gdy użytkownik zmienia wartość
                                # Wartość zwracana przez st.text_input jest zawsze zsynchronizowana z session_state[input_key]
                            else:
                                if is_historical:
                                    st.info("⏰ Rozegrany")
                                else:
                                    st.warning("⏰ Rozpoczęty")
                                pred_input = default_value
                        with col3:
                            if has_existing and home_goals is not None and away_goals is not None:
                                pred_data = existing_predictions[match_id]
                                pred_home = pred_data.get('home', 0)
                                pred_away = pred_data.get('away', 0)
                                points = tipper.calculate_points((pred_home, pred_away), (int(home_goals), int(away_goals)))
                                st.metric("Punkty", points)
                            else:
                                st.empty()
                
                    # Wyczyść dane z bulk po wyświetleniu wszystkich pól
                    bulk_fill_key = f"bulk_fill_{selected_player}_{round_id}"
                    if bulk_fill_key in st.session_state:
                        bulk_fill_data = st.session_state[bulk_fill_key]
                        # Sprawdź które mecze zostały już wyświetlone i użyte
                        used_match_ids = set()
                        for match in selected_matches:
                            match_id_str = str(match.get('match_id', ''))
                            if match_id_str in bulk_fill_data:
                                used_match_ids.add(match_id_str)
                        
                        # Usuń użyte klucze z bulk_fill_data
                        for match_id in used_match_ids:
                            if match_id in bulk_fill_data:
                                del bulk_fill_data[match_id]
                        
                        # Jeśli bulk_fill_data jest puste, usuń klucz
                        if not bulk_fill_data:
                            del st.session_state[bulk_fill_key]
                            logger.info(f"Bulk fill: Usunięto dane z bulk po wypełnieniu wszystkich pól")
                        else:
                            # Zaktualizuj session_state z pozostałymi danymi (jeśli jakieś zostały)
                            st.session_state[bulk_fill_key] = bulk_fill_data
                    
                    # Wyczyść flagę odświeżenia po zaktualizowaniu wszystkich wartości
                    if needs_refresh:
                        st.session_state['_refresh_predictions'] = False
                    
                    # Przyciski zapisu i usuwania pod wszystkimi meczami
                    col_save_single, col_delete_single = st.columns(2)
                    with col_save_single:
                        # Użyj unikalnego klucza z round_id i selected_player, aby uniknąć duplikatów
                        save_button_key = f"tipper_save_all_{selected_player}_{round_id}"
                        if st.button("💾 Zapisz typy", type="primary", key=save_button_key, width='stretch'):
                            saved_count = 0
                            updated_count = 0
                            errors = []
                            
                            # Pobierz wszystkie istniejące typy przed zapisem (aby nie stracić tych, które nie są w session_state)
                            # NIE przeładowujemy danych - używamy aktualnych danych z storage
                            existing_predictions_before = storage.get_player_predictions(selected_player, round_id, season_id=selected_season_id)
                            
                            logger.info(f"Zapis typów: Sprawdzam {len(selected_matches)} meczów dla gracza {selected_player}")
                            
                            # Loguj wszystkie klucze w session_state związane z typami
                            all_prediction_keys = [k for k in st.session_state.keys() if k.startswith(f"tipper_pred_{selected_player}_")]
                            logger.info(f"Zapis typów: Znaleziono {len(all_prediction_keys)} kluczy w session_state: {all_prediction_keys}")
                            
                            # Loguj wartości dla każdego klucza
                            for key in all_prediction_keys:
                                logger.info(f"Zapis typów: Klucz '{key}' ma wartość: '{st.session_state.get(key, 'BRAK')}'")
                            
                            for match in selected_matches:
                                match_id = str(match.get('match_id', ''))
                                match_id_int = match.get('match_id', '')
                                
                                # Spróbuj znaleźć klucz w session_state (może być jako string lub int)
                                input_key = f"tipper_pred_{selected_player}_{match_id}"
                                input_key_int = f"tipper_pred_{selected_player}_{match_id_int}" if isinstance(match_id_int, int) else None
                                
                                # Sprawdź czy jest wartość w session_state (z trybu pojedynczego)
                                pred_input = None
                                if input_key in st.session_state:
                                    pred_input = st.session_state[input_key]
                                elif input_key_int and input_key_int in st.session_state:
                                    pred_input = st.session_state[input_key_int]
                                    # Znormalizuj klucz do string
                                    st.session_state[input_key] = pred_input
                                    if input_key_int != input_key:
                                        del st.session_state[input_key_int]
                                
                                if pred_input is not None:
                                    logger.info(f"Zapis typów: Mecz {match_id} ({match.get('home_team_name')} vs {match.get('away_team_name')}), wartość w session_state: '{pred_input}'")
                                    
                                    # Pomiń puste wartości lub "0-0" jeśli typ już istnieje (chroni przed przypadkowym zerowaniem)
                                    if not pred_input or pred_input.strip() == "":
                                        # Puste pole - pomiń (zachowaj istniejący typ jeśli istnieje)
                                        if match_id in existing_predictions_before or str(match_id) in existing_predictions_before:
                                            logger.info(f"Zapis typów: Puste pole dla meczu {match_id}, zachowuję istniejący typ")
                                            continue  # Zachowaj istniejący typ
                                        else:
                                            logger.info(f"Zapis typów: Puste pole dla meczu {match_id}, pomijam")
                                            continue  # Pomiń puste pole
                                    
                                    parsed = tipper.parse_prediction(pred_input)
                                    logger.info(f"Zapis typów: Sparsowano '{pred_input}' -> {parsed}")
                                    
                                    if parsed:
                                        # Sprawdź czy to nie jest "0-0" dla istniejącego typu (chroni przed przypadkowym zerowaniem)
                                        if parsed == (0, 0):
                                            # Sprawdź czy typ już istnieje - jeśli tak, pomiń (nie zeruj)
                                            if match_id in existing_predictions_before or str(match_id) in existing_predictions_before:
                                                existing_pred = existing_predictions_before.get(match_id) or existing_predictions_before.get(str(match_id))
                                                if existing_pred and (existing_pred.get('home', 0) != 0 or existing_pred.get('away', 0) != 0):
                                                    # Istniejący typ nie jest "0-0" - nie zeruj go
                                                    logger.info(f"Pomijam zapis '0-0' dla meczu {match_id} - istnieje typ {existing_pred.get('home', 0)}-{existing_pred.get('away', 0)}")
                                                    continue
                                        
                                        # Sprawdź czy mecz już się rozpoczął
                                        match_date = match.get('match_date')
                                        can_add = True
                                        
                                        if match_date:
                                            try:
                                                match_dt = datetime.strptime(match_date, "%Y-%m-%d %H:%M:%S")
                                                if datetime.now() >= match_dt:
                                                    can_add = allow_historical
                                                    if not can_add:
                                                        errors.append(f"Mecz {match.get('home_team_name')} vs {match.get('away_team_name')} już rozegrany")
                                            except:
                                                pass
                                        
                                        if can_add:
                                            # Sprawdź czy typ już istnieje
                                            is_update = (match_id in existing_predictions_before or 
                                                       str(match_id) in existing_predictions_before or
                                                       (match_id.isdigit() and int(match_id) in existing_predictions_before))
                                            
                                            logger.info(f"Zapis typów: Zapisuję typ {parsed} dla meczu {match_id}, is_update={is_update}")
                                            result = storage.add_prediction(round_id, selected_player, match_id, parsed)
                                            
                                            if result:
                                                if is_update:
                                                    updated_count += 1
                                                else:
                                                    saved_count += 1
                                                    logger.info(f"Zapis typów: ✅ Zapisano typ dla meczu {match_id}")
                                            else:
                                                errors.append(f"Błąd zapisu dla {match.get('home_team_name')} vs {match.get('away_team_name')}")
                                                logger.error(f"Zapis typów: ❌ Błąd zapisu dla meczu {match_id}")
                                    else:
                                        errors.append(f"Nieprawidłowy format dla {match.get('home_team_name')} vs {match.get('away_team_name')}")
                                        logger.warning(f"Zapis typów: Nieprawidłowy format '{pred_input}' dla meczu {match_id}")
                                else:
                                    # Jeśli nie ma wartości w session_state, ale istnieje typ w danych, zachowaj go
                                    # (to chroni przed utratą typów z bulk, które nie są w session_state)
                                    if match_id in existing_predictions_before or str(match_id) in existing_predictions_before:
                                        # Typ istnieje, ale nie ma wartości w session_state - nie rób nic (zachowaj istniejący)
                                        logger.info(f"Zapis typów: Mecz {match_id} nie ma wartości w session_state, ale typ istnieje - zachowuję")
                                        pass
                                    else:
                                        logger.info(f"Zapis typów: Mecz {match_id} nie ma wartości w session_state i nie ma istniejącego typu - pomijam")
                                
                            total_saved = saved_count + updated_count
                            if total_saved > 0:
                                # Przelicz punkty dla wszystkich meczów z wynikami w tej rundzie
                                # NIE przeładowujemy danych - używamy aktualnych danych z storage
                                round_data = storage.data['rounds'].get(round_id, {})
                                round_matches = round_data.get('matches', [])
                                for match in round_matches:
                                    match_id = str(match.get('match_id', ''))
                                    home_goals = match.get('home_goals')
                                    away_goals = match.get('away_goals')
                                    if home_goals is not None and away_goals is not None:
                                        # Przelicz punkty dla tego meczu (dla wszystkich graczy z typami)
                                        try:
                                            storage.update_match_result(round_id, match_id, int(home_goals), int(away_goals))
                                        except Exception as e:
                                            logger.error(f"Błąd przeliczania punktów dla meczu {match_id}: {e}")
                                
                                if updated_count > 0 and saved_count > 0:
                                    st.success(f"✅ Zapisano {saved_count} nowych typów, zaktualizowano {updated_count} typów")
                                elif updated_count > 0:
                                    st.success(f"✅ Zaktualizowano {updated_count} typów")
                                else:
                                    st.success(f"✅ Zapisano {saved_count} typów")
                                
                                if errors:
                                    st.warning(f"⚠️ {len(errors)} typów nie zostało zapisanych:\n" + "\n".join(errors[:5]))
                                
                                # Wymuś natychmiastowy zapis
                                logger.info("Zapis typów (pojedyncze): Wymuszam zapis danych")
                                storage.flush_save()
                                
                                # Ustaw flagę odświeżenia w session_state (będzie użyta przy następnym renderowaniu)
                                st.session_state['_refresh_predictions'] = True
                                
                                # Odśwież ekran, aby zaktualizować ikony statusu (✅/❌)
                                st.rerun()
                            else:
                                if errors:
                                    st.error("❌ Nie udało się zapisać typów:\n" + "\n".join(errors[:5]))
                                else:
                                    st.warning("⚠️ Wprowadź typy przed zapisem")
                    
                    with col_delete_single:
                        # Użyj unikalnego klucza z round_id i selected_player, aby uniknąć duplikatów
                        delete_button_key = f"tipper_delete_all_{selected_player}_{round_id}"
                        if st.button("🗑️ Usuń typy", key=delete_button_key, width='stretch'):
                            if storage.delete_player_predictions(round_id, selected_player):
                                storage.flush_save()  # Wymuś natychmiastowy zapis
                                st.success("✅ Usunięto wszystkie typy")
                                # NIE odświeżamy - użytkownik może kontynuować pracę
                            else:
                                st.error("❌ Nie udało się usunąć typów")
                
                with col_bulk:  # Bulk mode
                    st.markdown("### Wklej wszystkie (bulk)")
                    st.markdown("**Wklej typy w formacie:**")
                    st.markdown("*Format: Nazwa drużyny1 - Nazwa drużyny2 Wynik*")
                    st.markdown("*Przykład: Borciuchy International - WKS BRONEK 50 7:0*")
                    
                    predictions_text = st.text_area(
                        "Typy:",
                        height=300,
                        help="Wklej typy w formacie:\nBorciuchy International - WKS BRONEK 50 7:0\nMoli Team - Szmacianka Szynwałdzian 1:1\nLegiaWawa - ks Jastrowie 2:1",
                        key="tipper_bulk_text"
                    )
                    
                    # Przycisk do wypełnienia pól pojedynczych meczów z bulk (bez zapisu)
                    if st.button("📋 Wypełnij pola z bulk", key="tipper_bulk_fill"):
                        if not predictions_text:
                            st.warning("⚠️ Wprowadź typy")
                        else:
                            # Parsuj typy z dopasowaniem do meczów
                            parsed = tipper.parse_match_predictions(predictions_text, selected_matches)
                            
                            logger.info(f"Bulk mode: Sparsowano {len(parsed)} typów z {len(selected_matches)} dostępnych meczów")
                            logger.info(f"Bulk mode: Sparsowane typy: {list(parsed.keys())}")
                            
                            # Wyświetl dostępne mecze dla debugowania
                            if len(parsed) < len(selected_matches):
                                st.info("💡 **Dostępne mecze w tej kolejce:**")
                                matches_list = []
                                for match in selected_matches:
                                    home = match.get('home_team_name', '?')
                                    away = match.get('away_team_name', '?')
                                    match_id = match.get('match_id', '?')
                                    matches_list.append(f"- {home} vs {away} (ID: {match_id})")
                                with st.expander("📋 Zobacz wszystkie mecze", expanded=False):
                                    st.markdown("\n".join(matches_list))
                            
                            if parsed:
                                # Zapisz typy do specjalnego klucza w session_state, który będzie użyty przy następnym rerun
                                bulk_fill_key = f"bulk_fill_{selected_player}_{round_id}"
                                bulk_fill_data = {}
                                
                                filled_count = 0
                                for match_id, prediction in parsed.items():
                                    match_id_str = str(match_id)
                                    pred_text = f"{prediction[0]}-{prediction[1]}"
                                    bulk_fill_data[match_id_str] = pred_text
                                    
                                    filled_count += 1
                                    logger.info(f"Bulk mode: Przygotowano wypełnienie pola dla meczu {match_id_str} wartością {pred_text}")
                                
                                # Zapisz dane do session_state (będą użyte przy następnym rerun do wypełnienia pól)
                                st.session_state[bulk_fill_key] = bulk_fill_data
                                
                                if filled_count > 0:
                                    st.success(f"✅ Przygotowano {filled_count} pól. Kliknij '💾 Zapisz typy' aby zapisać.")
                                    # Odśwież ekran, aby pola zostały wypełnione wartościami z bulk
                                    st.rerun()
                                else:
                                    st.warning("⚠️ Nie znaleziono dopasowanych meczów")
                            else:
                                st.warning("⚠️ Nie udało się sparsować typów. Sprawdź format.")
                
                # Sekcja korekty punktów (dla wybranego gracza i rundy)
                st.markdown("---")
                st.markdown("### ✏️ Korekta punktów")
                st.caption("💡 Możesz ręcznie ustawić punkty dla każdego meczu (w tym ujemne wartości)")
                
                # Pobierz aktualne punkty dla gracza w tej rundzie
                storage.reload_data()
                round_data = storage.data['rounds'].get(round_id, {})
                match_points_dict = round_data.get('match_points', {}).get(selected_player, {})
                player_predictions = storage.get_player_predictions(selected_player, round_id, season_id=selected_season_id)
                
                if player_predictions:
                    # Sortuj mecze według daty
                    matches_map = {str(m.get('match_id', '')): m for m in selected_matches}
                    sorted_match_ids = sorted(
                        player_predictions.keys(),
                        key=lambda mid: matches_map.get(str(mid), {}).get('match_date', '')
                    )
                    
                    # Przygotuj dane do edycji
                    manual_points_data = {}
                    for match_id in sorted_match_ids:
                        match = matches_map.get(str(match_id), {})
                        home_team = match.get('home_team_name', '?')
                        away_team = match.get('away_team_name', '?')
                        
                        # Pobierz aktualne punkty
                        current_points = None
                        match_id_str = str(match_id)
                        
                        # Sprawdź różne warianty klucza
                        if match_id_str in match_points_dict:
                            current_points = match_points_dict[match_id_str]
                        elif match_id in match_points_dict:
                            current_points = match_points_dict[match_id]
                        elif match_id_str.isdigit() and int(match_id_str) in match_points_dict:
                            current_points = match_points_dict[int(match_id_str)]
                        else:
                            # Jeśli brak punktów, ale mecz ma wynik i typ, oblicz punkty
                            home_goals = match.get('home_goals')
                            away_goals = match.get('away_goals')
                            if home_goals is not None and away_goals is not None:
                                # Pobierz typ (sprawdź różne warianty klucza)
                                pred = None
                                if match_id in player_predictions:
                                    pred = player_predictions[match_id]
                                elif match_id_str in player_predictions:
                                    pred = player_predictions[match_id_str]
                                elif match_id_str.isdigit() and int(match_id_str) in player_predictions:
                                    pred = player_predictions[int(match_id_str)]
                                
                                if pred:
                                    pred_home = pred.get('home', 0)
                                    pred_away = pred.get('away', 0)
                                    # Oblicz punkty
                                    calculated_points = tipper.calculate_points((pred_home, pred_away), (int(home_goals), int(away_goals)))
                                    current_points = calculated_points
                                    logger.info(f"Korekta punktów: Obliczono punkty dla meczu {match_id_str}: typ={pred_home}-{pred_away}, wynik={home_goals}-{away_goals}, punkty={calculated_points}")
                                else:
                                    current_points = 0
                            else:
                                current_points = 0
                        
                        # Sprawdź czy punkty są ręcznie ustawione
                        is_manual = storage.is_manual_points(round_id, match_id, selected_player)
                        
                        # Pobierz typ i wynik (sprawdź różne warianty klucza)
                        pred = None
                        if match_id in player_predictions:
                            pred = player_predictions[match_id]
                        elif match_id_str in player_predictions:
                            pred = player_predictions[match_id_str]
                        elif match_id_str.isdigit() and int(match_id_str) in player_predictions:
                            pred = player_predictions[int(match_id_str)]
                        
                        if not pred:
                            # Jeśli nie ma typu, pomiń ten mecz
                            continue
                        
                        pred_home = pred.get('home', 0)
                        pred_away = pred.get('away', 0)
                        home_goals = match.get('home_goals')
                        away_goals = match.get('away_goals')
                        result = f"{home_goals}-{away_goals}" if home_goals is not None and away_goals is not None else "—"
                        
                        col_match, col_type, col_result, col_points, col_manual = st.columns([3, 1.5, 1.5, 2, 1])
                        with col_match:
                            st.write(f"**{home_team} vs {away_team}**")
                        with col_type:
                            st.caption(f"Typ: {pred_home}-{pred_away}")
                        with col_result:
                            st.caption(f"Wynik: {result}")
                        with col_points:
                            new_points = st.number_input(
                                "Punkty:",
                                value=int(current_points),
                                min_value=None,  # Pozwól na ujemne wartości
                                max_value=None,
                                step=1,
                                key=f"manual_points_correction_{selected_player}_{round_id}_{match_id}",
                                label_visibility="collapsed"
                            )
                            # Zapisz wartość do słownika
                            manual_points_data[match_id] = new_points
                        with col_manual:
                            if is_manual:
                                st.caption("✏️")
                            else:
                                st.caption("🤖")
                    
                    # Przycisk zapisu wszystkich punktów
                    if st.button("💾 Zapisz wszystkie punkty", type="primary", key=f"save_all_points_correction_{selected_player}_{round_id}", width='stretch'):
                        saved_count = 0
                        for match_id, new_points in manual_points_data.items():
                            # Pobierz aktualne punkty
                            current_points = None
                            if str(match_id) in match_points_dict:
                                current_points = match_points_dict[str(match_id)]
                            elif match_id in match_points_dict:
                                current_points = match_points_dict[match_id]
                            elif str(match_id).isdigit() and int(match_id) in match_points_dict:
                                current_points = match_points_dict[int(match_id)]
                            else:
                                current_points = 0
                            
                            # Zapisz tylko jeśli wartość się zmieniła
                            if new_points != current_points:
                                storage.set_manual_points(round_id, match_id, selected_player, new_points, season_id=selected_season_id)
                                saved_count += 1
                        
                        if saved_count > 0:
                            storage.flush_save()
                            st.success(f"✅ Zapisano punkty dla {saved_count} meczów")
                            # NIE odświeżamy - użytkownik może kontynuować pracę
                        else:
                            st.info("ℹ️ Brak zmian do zapisania")
                else:
                    st.info("ℹ️ Brak typów dla tego gracza w tej rundzie")
            
    
    except Exception as e:
        st.error(f"❌ Błąd: {str(e)}")
        logger.error(f"Błąd typera: {e}", exc_info=True)


if __name__ == "__main__":
    main()
