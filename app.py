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
        if st.button("➕ Utwórz nowy sezon", type="primary", key="create_new_season"):
            # Utwórz storage dla nowego sezonu (tylko do utworzenia pliku)
            new_season_id = f"season_{new_season_num}"
            temp_storage = TipperStorage(season_id=new_season_id)
            if temp_storage.create_new_season(new_season_num):
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
        if st.button("🚪 Wyloguj się", use_container_width=True):
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
            if st.button("➕ Dodaj ligę", key=f"add_league_{selected_season_id}", use_container_width=True):
                # Dodaj domyślną ligę (najwyższe ID + 1 lub 1)
                if st.session_state[leagues_key]:
                    new_league_id = max(st.session_state[leagues_key]) + 1
                else:
                    new_league_id = 32612
                st.session_state[leagues_key].append(new_league_id)
                st.rerun()
        
        with col_save:
            # Przycisk zapisu lig
            if st.button("💾 Zapisz ligi", type="primary", key=f"save_leagues_{selected_season_id}", use_container_width=True):
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
            if st.button("💾 Zapisz status", type="primary", key=f"save_archived_{selected_season_id}", use_container_width=True):
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
        if st.button("📥 Pobierz backup danych", use_container_width=True, help="Pobierz aktualny plik tipper_data.json"):
            import json
            data_str = json.dumps(storage.data, ensure_ascii=False, indent=2)
            st.download_button(
                label="⬇️ Pobierz plik JSON",
                data=data_str,
                file_name="tipper_data.json",
                mime="application/json",
                use_container_width=True
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
                        if st.button("💾 Zaimportuj dane", type="primary", use_container_width=True):
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
                        st.dataframe(df_leaderboard[['Pozycja', 'Gracz', 'Punkty', 'Suma', 'Rundy']], use_container_width=True, hide_index=True)
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
            # Inicjalizuj klienta OAuth
            client = HattrickOAuthSimple(consumer_key, consumer_secret)
            client.set_access_tokens(access_token, access_token_secret)
            
            # Pobierz mecze z obu lig
            all_fixtures = []
            with st.spinner("Pobieranie meczów z lig..."):
                for league_id in TIPPER_LEAGUES:
                    try:
                        fixtures = client.get_league_fixtures(league_id)
                        if fixtures:
                            # Dodaj informację o lidze
                            for fixture in fixtures:
                                fixture['league_id'] = league_id
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
        
        # Jeśli nie ma zapisanych ustawień dla tego sezonu, wybierz wszystkie drużyny domyślnie
        if not selected_teams:
            selected_teams = all_team_names.copy()
        
        # Wybór drużyn do typowania - w sidebarze
        with st.sidebar:
            st.markdown("---")
            st.subheader(f"⚙️ Wybór drużyn do typowania (Sezon {selected_season_id.replace('season_', '')})")
            st.markdown("*Zaznacz drużyny, które chcesz uwzględnić w typerze*")
            
            # Użyj checkboxów dla wyboru drużyn
            new_selected_teams = []
            
            for team_name in all_team_names:
                if st.checkbox(team_name, value=team_name in selected_teams, key=f"team_select_{selected_season_id}_{team_name}"):
                    new_selected_teams.append(team_name)
            
            # Przycisk zapisu ustawień
            if st.button("💾 Zapisz wybór drużyn", type="primary", use_container_width=True):
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
                st.dataframe(df_leaderboard, use_container_width=True, hide_index=True)
                
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
                                storage.update_match_result(round_id, match_id, int(home_goals), int(away_goals))
                            except Exception as e:
                                logger.error(f"[Ranking per kolejka] Błąd automatycznego przeliczania punktów dla meczu {match_id}: {e}")
                
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
                    st.dataframe(df_round_leaderboard, use_container_width=True, hide_index=True)
                    
                    # Dodaj expandery z typami dla każdego gracza
                    st.markdown("### 📋 Szczegóły typów")
                    for player in round_leaderboard:
                        player_name = player['player_name']
                        player_predictions = storage.get_player_predictions(player_name, round_id)
                        
                        if player_predictions:
                            # Sortuj mecze według daty
                            sorted_match_ids = sorted(
                                player_predictions.keys(),
                                key=lambda mid: matches_map.get(str(mid), {}).get('match_date', '')
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
                            
                            # Sprawdź które mecze mają wyniki
                            matches_with_results = []
                            for m in matches:
                                mid = str(m.get('match_id', ''))
                                if m.get('home_goals') is not None and m.get('away_goals') is not None:
                                    matches_with_results.append(mid)
                            logger.info(f"  Mecze z wynikami: {matches_with_results}")
                            logger.info(f"  Mecze z punktami w dict: {list(match_points_dict.keys())}")
                            
                            for match_id in sorted_match_ids:
                                match = matches_map.get(str(match_id), {})
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
                                with st.expander(f"👤 {player_name} - Typy i wyniki", expanded=False):
                                    df_types = pd.DataFrame(types_table_data)
                                    st.dataframe(df_types, use_container_width=True, hide_index=True)
                                    total_points = sum(row['Punkty'] for row in types_table_data)
                                    st.caption(f"**Suma punktów: {total_points}**")
                                    
                                    # Podsumowanie dla logów
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
                st.dataframe(df_leaderboard, use_container_width=True, hide_index=True)
                
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
                if st.button("🔄 Przelicz punkty", type="primary", use_container_width=True, key=f"recalculate_{round_id}"):
                    with st.spinner("Pobieranie wyników i przeliczanie punktów..."):
                        # Przeładuj dane
                        storage.reload_data()
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
                                    logger.warning(f"⚠️ Mecz {match_id} z API nie został znaleziony w storage_matches_map")
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
                        calculated_count = 0
                        logger.info(f"Przeliczanie punktów dla rundy {round_id}: {len(round_matches)} meczów w rundzie")
                        for match in round_matches:
                            match_id = str(match.get('match_id', ''))
                            home_goals = match.get('home_goals')
                            away_goals = match.get('away_goals')
                            
                            logger.info(f"Sprawdzam mecz {match_id}: home_goals={home_goals}, away_goals={away_goals}")
                            
                            # Jeśli mecz ma wynik, przelicz punkty (update_match_result sprawdzi czy są typy)
                            if home_goals is not None and away_goals is not None:
                                try:
                                    logger.info(f"Wywołuję update_match_result dla meczu {match_id} z wynikiem {home_goals}-{away_goals}")
                                    storage.update_match_result(round_id, match_id, int(home_goals), int(away_goals))
                                    calculated_count += 1
                                    logger.info(f"✅ Przeliczono punkty dla meczu {match_id} w rundzie {round_id} (wynik: {home_goals}-{away_goals})")
                                except Exception as e:
                                    logger.error(f"❌ Błąd przeliczania punktów dla meczu {match_id}: {e}", exc_info=True)
                            else:
                                logger.info(f"⏭️ Mecz {match_id} nie ma wyniku (home_goals={home_goals}, away_goals={away_goals}) - pomijam")
                        
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
                            storage.update_match_result(round_id, match_id, int(home_goals), int(away_goals))
                        except Exception as e:
                            logger.error(f"Błąd przeliczania punktów dla meczu {match_id}: {e}", exc_info=True)
            
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
                st.dataframe(df_matches, use_container_width=True, hide_index=True)
            
            
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
                col_add, col_remove = st.columns(2)
                with col_add:
                    add_new_player = st.button("➕ Dodaj", key="tipper_add_new_player_btn", use_container_width=True)
                with col_remove:
                    if all_players_list and selected_player:
                        remove_player = st.button("🗑️ Usuń", key="tipper_remove_player_btn", use_container_width=True)
                    else:
                        remove_player = False
            
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
            
            # Usuwanie gracza
            if remove_player and selected_player:
                if storage.remove_player(selected_player, season_id=selected_season_id):
                    storage.flush_save()  # Wymuś natychmiastowy zapis
                    st.success(f"✅ Usunięto gracza: {selected_player} z sezonu {selected_season_id.replace('season_', '')}")
                    st.rerun()
                else:
                    st.error("❌ Nie udało się usunąć gracza")
            
            if selected_player:
                # Sprawdź czy trzeba odświeżyć dane
                needs_refresh = st.session_state.get('_refresh_predictions', False)
                if needs_refresh:
                    storage.reload_data()
                
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
                                
                                # Jeśli flaga odświeżenia jest ustawiona, usuń klucz z session_state
                                # aby wymusić użycie nowej wartości default_value
                                if needs_refresh and input_key in st.session_state:
                                    del st.session_state[input_key]
                                
                                # Użyj tylko default_value - Streamlit automatycznie zarządza stanem przez key
                                pred_input = st.text_input(
                                    f"Typ:",
                                    value=default_value,
                                    key=input_key,
                                    label_visibility="collapsed"
                                )
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
                    
                    # Wyczyść flagę odświeżenia po zaktualizowaniu wszystkich wartości
                    if needs_refresh:
                        st.session_state['_refresh_predictions'] = False
                    
                    # Przyciski zapisu i usuwania pod wszystkimi meczami
                    col_save_single, col_delete_single = st.columns(2)
                    with col_save_single:
                        if st.button("💾 Zapisz typy", type="primary", key="tipper_save_all", use_container_width=True):
                            saved_count = 0
                            updated_count = 0
                            errors = []
                            
                            for match in selected_matches:
                                match_id = str(match.get('match_id', ''))
                                input_key = f"tipper_pred_{selected_player}_{match_id}"
                                
                                if input_key in st.session_state:
                                    pred_input = st.session_state[input_key]
                                    parsed = tipper.parse_prediction(pred_input)
                                    
                                    if parsed:
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
                                            is_update = match_id in existing_predictions
                                            
                                            storage.add_prediction(round_id, selected_player, match_id, parsed)
                                            
                                            if is_update:
                                                updated_count += 1
                                            else:
                                                saved_count += 1
                                    else:
                                        errors.append(f"Nieprawidłowy format dla {match.get('home_team_name')} vs {match.get('away_team_name')}")
                            
                            total_saved = saved_count + updated_count
                            if total_saved > 0:
                                if updated_count > 0 and saved_count > 0:
                                    st.success(f"✅ Zapisano {saved_count} nowych typów, zaktualizowano {updated_count} typów")
                                elif updated_count > 0:
                                    st.success(f"✅ Zaktualizowano {updated_count} typów")
                                else:
                                    st.success(f"✅ Zapisano {saved_count} typów")
                                
                                if errors:
                                    st.warning(f"⚠️ {len(errors)} typów nie zostało zapisanych:\n" + "\n".join(errors[:5]))
                                storage.flush_save()  # Wymuś natychmiastowy zapis przed rerun
                                st.cache_data.clear()  # Wyczyść cache Streamlit
                                st.rerun()
                            else:
                                if errors:
                                    st.error("❌ Nie udało się zapisać typów:\n" + "\n".join(errors[:5]))
                                else:
                                    st.warning("⚠️ Wprowadź typy przed zapisem")
                                
                                # Przeładuj dane po zapisie (nawet jeśli były błędy, niektóre typy mogły zostać zapisane)
                                storage.reload_data()
                    
                    with col_delete_single:
                        if st.button("🗑️ Usuń typy", key="tipper_delete_all", use_container_width=True):
                            if storage.delete_player_predictions(round_id, selected_player):
                                storage.flush_save()  # Wymuś natychmiastowy zapis przed rerun
                                st.success("✅ Usunięto wszystkie typy")
                                st.rerun()
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
                    
                    if st.button("💾 Zapisz typy (bulk)", type="primary", key="tipper_bulk_save"):
                        if not predictions_text:
                            st.warning("⚠️ Wprowadź typy")
                        else:
                            # Parsuj typy z dopasowaniem do meczów
                            parsed = tipper.parse_match_predictions(predictions_text, selected_matches)
                            
                            if parsed:
                                saved_count = 0
                                updated_count = 0
                                errors = []
                                
                                for match_id, prediction in parsed.items():
                                    # Znajdź mecz
                                    match = next((m for m in selected_matches if str(m.get('match_id')) == match_id), None)
                                    
                                    if match:
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
                                            is_update = match_id in existing_predictions
                                            
                                            storage.add_prediction(round_id, selected_player, match_id, prediction)
                                            
                                            if is_update:
                                                updated_count += 1
                                            else:
                                                saved_count += 1
                                    else:
                                        errors.append(f"Nie znaleziono meczu dla ID: {match_id}")
                                
                                total_saved = saved_count + updated_count
                                if total_saved > 0:
                                    if updated_count > 0 and saved_count > 0:
                                        st.success(f"✅ Zapisano {saved_count} nowych typów, zaktualizowano {updated_count} typów")
                                    elif updated_count > 0:
                                        st.success(f"✅ Zaktualizowano {updated_count} typów")
                                    else:
                                        st.success(f"✅ Zapisano {saved_count} typów")
                                    
                                    if errors:
                                        st.warning(f"⚠️ {len(errors)} typów nie zostało zapisanych:\n" + "\n".join(errors[:5]))
                                    storage.flush_save()  # Wymuś natychmiastowy zapis przed rerun
                                    # Wyczyść cache i wymuś odświeżenie danych
                                    st.cache_data.clear()
                                    # Ustaw flagę odświeżenia w session_state
                                    st.session_state['_refresh_predictions'] = True
                                    st.rerun()
                                else:
                                    if errors:
                                        st.error("❌ Nie udało się zapisać typów:\n" + "\n".join(errors[:5]))
                                    else:
                                        st.warning("⚠️ Wszystkie mecze już rozpoczęte")
                            else:
                                st.error("❌ Nie można sparsować typów. Sprawdź format:\n- Nazwa drużyny1 - Nazwa drużyny2 Wynik\n- Przykład: Borciuchy International - WKS BRONEK 50 7:0")
            
    
    except Exception as e:
        st.error(f"❌ Błąd: {str(e)}")
        logger.error(f"Błąd typera: {e}", exc_info=True)


if __name__ == "__main__":
    main()

