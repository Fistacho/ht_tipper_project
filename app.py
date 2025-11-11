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
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('tipper.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


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
        
        # Tabs dla rankingu per kolejka i całości - domyślnie ranking całości (pierwszy tab)
        ranking_tab1, ranking_tab2 = st.tabs(["🏆 Ranking całości", "📊 Ranking per kolejka"])
        
        # Dla rankingu całości nie potrzebujemy wyboru rundy
        with ranking_tab1:
            st.markdown("### 🏆 Ranking całości")
            
            exclude_worst = st.checkbox("Odrzuć najgorszy wynik każdego gracza", value=True, key="exclude_worst_overall")
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
            
            # Znajdź ostatnią rozegraną kolejkę (domyślnie)
            default_round_idx = 0
            for idx, (date, matches) in enumerate(filtered_rounds):
                # Sprawdź czy kolejka ma rozegrane mecze
                has_played = any(m.get('home_goals') is not None and m.get('away_goals') is not None for m in matches)
                if has_played:
                    default_round_idx = idx
                    break  # Weź pierwszą (najnowszą) rozegraną kolejkę
            
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
                round_leaderboard = storage.get_round_leaderboard(round_id)
                
                if round_leaderboard:
                    # Pobierz mecze z rundy dla wyświetlenia typów
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
                                key=lambda mid: matches_map.get(mid, {}).get('match_date', '')
                            )
                            
                            # Przygotuj dane do tabeli
                            types_table_data = []
                            for match_id in sorted_match_ids:
                                match = matches_map.get(match_id, {})
                                pred = player_predictions[match_id]
                                home_team = match.get('home_team_name', '?')
                                away_team = match.get('away_team_name', '?')
                                pred_home = pred.get('home', 0)
                                pred_away = pred.get('away', 0)
                                
                                # Pobierz punkty dla tego meczu
                                match_points_dict = round_data.get('match_points', {}).get(player_name, {})
                                points = match_points_dict.get(match_id, 0)
                                
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
        
        # Wybór rundy - pod Rankingiem (dla sekcji wprowadzania typów)
        st.markdown("---")
        st.subheader("📅 Wybór rundy")
        
        # Znajdź ostatnią rozegraną kolejkę (domyślnie)
        default_round_idx = 0
        for idx, (date, matches) in enumerate(filtered_rounds):
            # Sprawdź czy kolejka ma rozegrane mecze
            has_played = any(m.get('home_goals') is not None and m.get('away_goals') is not None for m in matches)
            if has_played:
                default_round_idx = idx
                break  # Weź pierwszą (najnowszą) rozegraną kolejkę
        
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
            
            # Sprawdź czy mecze są już rozegrane
            matches_played = []
            matches_upcoming = []
            
            for match in selected_matches:
                if match.get('home_goals') is not None and match.get('away_goals') is not None:
                    matches_played.append(match)
                else:
                    matches_upcoming.append(match)
            
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
                    # Aktualizuj wynik w storage
                    try:
                        storage.update_match_result(round_id, match_id, int(home_goals), int(away_goals))
                    except:
                        pass
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
                # Pobierz istniejące typy gracza dla tej rundy
                existing_predictions = storage.get_player_predictions(selected_player, round_id, season_id=selected_season_id)
                
                st.markdown(f"### Typy dla: **{selected_player}**")
                
                # Tryb wprowadzania: pojedyncze lub bulk
                input_mode = st.radio("Tryb wprowadzania:", ["Pojedyncze mecze", "Wklej wszystkie (bulk)"], key="tipper_input_mode", horizontal=True)
                
                if input_mode == "Pojedyncze mecze":
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
                                pred_input = st.text_input(
                                    f"Typ:",
                                    value=default_value,
                                    key=f"tipper_pred_{selected_player}_{match_id}",
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
                    
                    # Przyciski zapisu i usuwania pod wszystkimi meczami
                    col_save, col_delete = st.columns(2)
                    with col_save:
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
                                st.rerun()
                            else:
                                if errors:
                                    st.error("❌ Nie udało się zapisać typów:\n" + "\n".join(errors[:5]))
                                else:
                                    st.warning("⚠️ Wprowadź typy przed zapisem")
                    
                    with col_delete:
                        if st.button("🗑️ Usuń typy", key="tipper_delete_all", use_container_width=True):
                            if storage.delete_player_predictions(round_id, selected_player):
                                storage.flush_save()  # Wymuś natychmiastowy zapis przed rerun
                                st.success("✅ Usunięto wszystkie typy")
                                st.rerun()
                            else:
                                st.error("❌ Nie udało się usunąć typów")
                
                else:  # Bulk mode
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

