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
from tipper_storage import TipperStorage, get_storage
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
        
        # Sekcja logów (debug)
        with st.expander("🔍 Logi aplikacji", expanded=False):
            if st.button("🔄 Odśwież logi", use_container_width=True):
                st.rerun()
            
            # Wyświetl ostatnie linie z pliku logów
            log_file = "tipper.log"
            if os.path.exists(log_file):
                try:
                    with open(log_file, 'r', encoding='utf-8') as f:
                        lines = f.readlines()
                        # Pokaż ostatnie 50 linii
                        recent_lines = lines[-50:] if len(lines) > 50 else lines
                        st.text_area(
                            "Ostatnie logi:",
                            value=''.join(recent_lines),
                            height=300,
                            disabled=True
                        )
                except Exception as e:
                    st.error(f"Błąd odczytu logów: {e}")
            else:
                st.info("Plik logów nie istnieje")
            
            # Wyświetl informacje o storage
            st.markdown("---")
            st.subheader("💾 Informacje o storage")
            try:
                logger.info("DEBUG: Tworzę storage...")
                storage = get_storage()
                logger.info(f"DEBUG: Storage utworzony: {type(storage).__name__}")
                storage_type = type(storage).__name__
                st.info(f"Typ storage: **{storage_type}**")
                
                if 'MySQL' in storage_type:
                    st.success("✅ Używam MySQL")
                    try:
                        # Sprawdź połączenie
                        test_data = storage.get_leaderboard()
                        if test_data:
                            st.success(f"✅ Połączenie działa ({len(test_data)} graczy)")
                        else:
                            st.warning("⚠️ Połączenie działa, ale brak danych")
                    except Exception as e:
                        st.error(f"❌ Błąd połączenia: {e}")
                else:
                    st.info("📄 Używam JSON")
            except Exception as e:
                st.error(f"Błąd: {e}")
        
        st.markdown("---")
        st.header("⚙️ Konfiguracja")
        
        # ID lig dla typera
        st.subheader("🏆 Ligi typera")
        league_1 = st.number_input(
            "Liga 1 (LeagueLevelUnitID):",
            value=32612,
            min_value=1,
            help="Wprowadź ID pierwszej ligi"
        )
        league_2 = st.number_input(
            "Liga 2 (LeagueLevelUnitID):",
            value=9399,
            min_value=1,
            help="Wprowadź ID drugiej ligi"
        )
        
        TIPPER_LEAGUES = [league_1, league_2]
        
        # Przycisk odświeżania danych
        if st.button("🔄 Odśwież dane", type="primary"):
            st.cache_data.clear()
            st.rerun()
        
        # Informacje
        st.info(f"**Liga 1:** {league_1}")
        st.info(f"**Liga 2:** {league_2}")
        
        st.markdown("---")
        st.subheader("💾 Import/Eksport danych")
        
        # Inicjalizacja storage (wcześniej dla eksportu/importu)
        # Automatycznie wybiera MySQL jeśli dostępne, w przeciwnym razie JSON
        storage = get_storage()
        
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
                            try:
                                # Zrób backup przed importem
                                backup_data = storage.data.copy()
                                
                                # Zaimportuj dane
                                # Dla MySQL użyj specjalnej metody importu
                                if hasattr(storage, '_import_data_to_mysql'):
                                    storage._import_data_to_mysql(uploaded_data)
                                else:
                                    # Dla JSON użyj standardowej metody
                                    storage.data = uploaded_data
                                    storage._save_data()
                                
                                st.success("✅ Dane zostały zaimportowane pomyślnie!")
                                st.info("🔄 Odśwież stronę aby zobaczyć zmiany")
                                st.rerun()
                            except Exception as e:
                                st.error(f"❌ Błąd importu danych: {str(e)}")
                                logger.error(f"Błąd importu danych: {e}", exc_info=True)
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
        # Najpierw spróbuj odczytać z Streamlit secrets (dla Streamlit Cloud)
        consumer_key = None
        consumer_secret = None
        access_token = None
        access_token_secret = None
        
        try:
            # Spróbuj odczytać z st.secrets (Streamlit Cloud)
            if hasattr(st, 'secrets'):
                try:
                    # W TOML zmienne są dostępne bezpośrednio jako atrybuty st.secrets
                    consumer_key = getattr(st.secrets, 'HATTRICK_CONSUMER_KEY', None)
                    consumer_secret = getattr(st.secrets, 'HATTRICK_CONSUMER_SECRET', None)
                    access_token = getattr(st.secrets, 'HATTRICK_ACCESS_TOKEN', None)
                    access_token_secret = getattr(st.secrets, 'HATTRICK_ACCESS_TOKEN_SECRET', None)
                    
                    # Debug - sprawdź czy są odczytane
                    if consumer_key:
                        logger.info(f"DEBUG: HATTRICK_CONSUMER_KEY odczytany z secrets: {consumer_key[:10]}...")
                    else:
                        logger.info("DEBUG: HATTRICK_CONSUMER_KEY NIE odczytany z secrets")
                except (AttributeError, KeyError) as e:
                    logger.info(f"DEBUG: Błąd odczytu OAuth z secrets: {e}")
        except Exception as e:
            logger.info(f"DEBUG: Błąd przy próbie odczytu secrets: {e}")
        
        # Jeśli nie ma secrets, spróbuj z .env (dla lokalnego rozwoju)
        if not all([consumer_key, consumer_secret, access_token, access_token_secret]):
            load_dotenv()
            consumer_key = consumer_key or os.getenv('HATTRICK_CONSUMER_KEY')
            consumer_secret = consumer_secret or os.getenv('HATTRICK_CONSUMER_SECRET')
            access_token = access_token or os.getenv('HATTRICK_ACCESS_TOKEN')
            access_token_secret = access_token_secret or os.getenv('HATTRICK_ACCESS_TOKEN_SECRET')
            
            if consumer_key:
                logger.info("DEBUG: OAuth odczytany z .env")
        
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
        
        # Pobierz zapisane ustawienia
        selected_teams = storage.get_selected_teams()
        
        # Jeśli nie ma zapisanych ustawień, wybierz wszystkie drużyny domyślnie
        if not selected_teams:
            selected_teams = all_team_names.copy()
        
        # Wybór drużyn do typowania - w sidebarze
        with st.sidebar:
            st.markdown("---")
            st.subheader("⚙️ Wybór drużyn do typowania")
            st.markdown("*Zaznacz drużyny, które chcesz uwzględnić w typerze*")
            
            # Użyj checkboxów dla wyboru drużyn
            new_selected_teams = []
            
            for team_name in all_team_names:
                if st.checkbox(team_name, value=team_name in selected_teams, key=f"team_select_{team_name}"):
                    new_selected_teams.append(team_name)
            
            # Przycisk zapisu ustawień
            if st.button("💾 Zapisz wybór drużyn", type="primary", use_container_width=True):
                storage.set_selected_teams(new_selected_teams)
                st.success(f"✅ Zapisano wybór {len(new_selected_teams)} drużyn")
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
            leaderboard = storage.get_leaderboard(exclude_worst=exclude_worst)
            
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
            
            # Znajdź najstarszą kolejkę bez wyników z API (domyślnie dla rankingu po zalogowaniu)
            # filtered_rounds jest posortowane DESC (najnowsza pierwsza: 14, 13, 12...)
            # Szukamy najstarszej kolejki bez wyników z API (ostatniej w liście DESC, która jest bez wyników)
            # NIE używamy session_state dla domyślnego wyboru - zawsze szukamy najstarszej bez wyników
            default_round_idx = None
            logger.info(f"DEBUG ranking: Sprawdzam {len(filtered_rounds)} kolejek (posortowane DESC)")
            # Przejdź przez wszystkie kolejki i zapamiętaj najstarszą bez wyników
            for idx, (date, matches) in enumerate(filtered_rounds):
                # Sprawdź czy kolejka ma wyniki z API (czyli czy mecze mają home_goals i away_goals)
                # Kolejka ma wyniki z API jeśli PRZYNAJMNIEJ JEDEN mecz ma wyniki
                matches_with_results = [
                    m for m in matches 
                    if m.get('home_goals') is not None and m.get('away_goals') is not None
                ]
                has_api_results = len(matches_with_results) > 0
                round_number = date_to_round_number.get(date, '?')
                logger.info(f"DEBUG ranking: idx={idx}, date={date}, round_number={round_number}, has_api_results={has_api_results}, matches_count={len(matches)}, matches_with_results={len(matches_with_results)}")
                if not has_api_results:
                    # Zapamiętaj najstarszą kolejkę bez wyników (ostatnią w liście DESC)
                    default_round_idx = idx
                    logger.info(f"DEBUG ranking: ✅ Znaleziono kolejkę bez wyników z API: {round_number} na indeksie {idx}")
                else:
                    logger.info(f"DEBUG ranking: ⏭️ Pomijam kolejkę {round_number} (ma wyniki z API)")
            
            # Jeśli nie znaleziono kolejki bez wyników z API, użyj pierwszej (najnowszej)
            if default_round_idx is None:
                default_round_idx = 0
                logger.info(f"DEBUG ranking: Nie znaleziono kolejki bez wyników z API, używam indeksu 0")
            else:
                logger.info(f"DEBUG ranking: ✅ Wybrano najstarszą kolejkę bez wyników z API na indeksie {default_round_idx}")
            
            # Sprawdź czy jest zapisany wybór rundy w session_state (tylko jeśli użytkownik wybrał ręcznie)
            # Używamy osobnego klucza dla rankingu, aby nie nadpisywać domyślnej kolejki
            # ALE tylko jeśli użytkownik już wcześniej wybrał kolejkę ręcznie (nie przy pierwszym załadowaniu)
            if 'ranking_selected_round_idx' in st.session_state and st.session_state.get('user_manually_selected_round', False):
                default_round_idx = st.session_state.ranking_selected_round_idx
                logger.info(f"DEBUG ranking: Używam zapisanego wyboru użytkownika: {default_round_idx}")
            
            # Numeruj kolejki według daty asc (numer 1 = najstarsza), ale wyświetlaj sort desc (najnowsza pierwsza)
            round_options = []
            for date, matches in filtered_rounds:
                round_number = date_to_round_number[date]  # Numer według daty asc
                round_options.append(f"Kolejka {round_number} - {date} ({len(matches)} meczów)")
            
            selected_round_idx = st.selectbox("Wybierz rundę:", range(len(round_options)), index=default_round_idx, format_func=lambda x: round_options[x], key="ranking_round_select")
            
            # Zapisz wybór rundy w session_state (osobny klucz dla rankingu)
            # Oznacz że użytkownik wybrał kolejkę ręcznie (jeśli wybór różni się od domyślnego)
            if selected_round_idx != default_round_idx:
                st.session_state.user_manually_selected_round = True
            st.session_state.ranking_selected_round_idx = selected_round_idx
            # Również zapisz w głównym kluczu dla synchronizacji z sekcją wprowadzania typów
            st.session_state.selected_round_idx = selected_round_idx
            
            if selected_round_idx is not None:
                selected_round_date, selected_matches = filtered_rounds[selected_round_idx]
                round_number = date_to_round_number[selected_round_date]  # Numer kolejki według daty asc (1 = najstarsza)
                round_id = f"round_{selected_round_date}"
                
                # Dodaj rundę do storage jeśli nie istnieje
                if round_id not in storage.data['rounds']:
                    # Sezon zostanie automatycznie utworzony w add_round jeśli nie istnieje
                    storage.add_round("current_season", round_id, selected_matches, selected_round_date)
                
                # Ranking dla wybranej rundy
                round_leaderboard = storage.get_round_leaderboard(round_id)
                
                # Debug: sprawdź czy są gracze w bazie i czy runda istnieje
                if not round_leaderboard:
                    # Wymuś przeładowanie danych z bazy (wyczyść cache)
                    if hasattr(storage, 'reload_data'):
                        storage.reload_data()
                    
                    # Sprawdź czy są gracze w bazie
                    all_players = list(storage.data.get('players', {}).keys())
                    logger.info(f"DEBUG: Po przeładowaniu - graczy w storage.data: {len(all_players)}")
                    logger.info(f"DEBUG: Gracze: {all_players[:5]}...")
                    
                    if not all_players:
                        st.warning("⚠️ Brak graczy w bazie. Dodaj graczy, aby zobaczyć ranking.")
                    else:
                        # Sprawdź czy runda istnieje w storage
                        round_exists = round_id in storage.data.get('rounds', {})
                        # Sprawdź czy są mecze w rundzie
                        round_data = storage.data.get('rounds', {}).get(round_id, {})
                        matches_in_round = len(round_data.get('matches', []))
                        
                        # Sprawdź bezpośrednio w bazie (jeśli MySQL storage)
                        if hasattr(storage, 'conn'):
                            try:
                                players_df = storage.conn.query("SELECT COUNT(*) as cnt FROM players", ttl=0)
                                players_count_db = int(players_df.iloc[0]['cnt']) if not players_df.empty else 0
                                logger.info(f"DEBUG: Graczy w bazie (bezpośrednie zapytanie): {players_count_db}")
                            except Exception as e:
                                logger.error(f"DEBUG: Błąd zapytania do bazy: {e}")
                                players_count_db = 0
                        else:
                            players_count_db = len(all_players)
                        
                        debug_info = f"📊 Debug: round_id='{round_id}', runda istnieje={round_exists}, mecze={matches_in_round}, graczy (cache)={len(all_players)}, graczy (DB)={players_count_db}"
                        logger.info(debug_info)
                        st.info(f"📊 Brak danych do wyświetlenia dla tej kolejki\n\n**Debug:**\n- round_id: `{round_id}`\n- Runda istnieje: {round_exists}\n- Mecze w rundzie: {matches_in_round}\n- Graczy w cache: {len(all_players)}\n- Graczy w bazie: {players_count_db}")
                
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
        
        # Znajdź najstarszą kolejkę bez wyników z API (domyślnie dla sekcji wprowadzania typów po zalogowaniu)
        # filtered_rounds jest posortowane DESC (najnowsza pierwsza: 14, 13, 12...)
        # Szukamy najstarszej kolejki bez wyników z API (ostatniej w liście DESC, która jest bez wyników)
        # NIE używamy session_state dla domyślnego wyboru - zawsze szukamy najstarszej bez wyników
        default_round_idx = None
        logger.info(f"DEBUG input: Sprawdzam {len(filtered_rounds)} kolejek (posortowane DESC)")
        # Przejdź przez wszystkie kolejki i zapamiętaj najstarszą bez wyników
        for idx, (date, matches) in enumerate(filtered_rounds):
            # Sprawdź czy kolejka ma wyniki z API (czyli czy mecze mają home_goals i away_goals)
            # Kolejka ma wyniki z API jeśli PRZYNAJMNIEJ JEDEN mecz ma wyniki
            matches_with_results = [
                m for m in matches 
                if m.get('home_goals') is not None and m.get('away_goals') is not None
            ]
            has_api_results = len(matches_with_results) > 0
            round_number = date_to_round_number.get(date, '?')
            logger.info(f"DEBUG input: idx={idx}, date={date}, round_number={round_number}, has_api_results={has_api_results}, matches_count={len(matches)}, matches_with_results={len(matches_with_results)}")
            if not has_api_results:
                # Zapamiętaj najstarszą kolejkę bez wyników (ostatnią w liście DESC)
                default_round_idx = idx
                logger.info(f"DEBUG input: ✅ Znaleziono kolejkę bez wyników z API: {round_number} na indeksie {idx}")
            else:
                logger.info(f"DEBUG input: ⏭️ Pomijam kolejkę {round_number} (ma wyniki z API)")
        
        # Jeśli nie znaleziono kolejki bez wyników z API, użyj pierwszej (najnowszej)
        if default_round_idx is None:
            default_round_idx = 0
            logger.info(f"DEBUG input: Nie znaleziono kolejki bez wyników z API, używam indeksu 0")
        else:
            logger.info(f"DEBUG input: ✅ Wybrano najstarszą kolejkę bez wyników z API na indeksie {default_round_idx}")
        
        # Sprawdź czy jest zapisany wybór rundy w session_state (synchronizacja z rankingiem)
        # Jeśli użytkownik wybrał kolejkę w rankingu, użyj tego wyboru
        # ALE tylko jeśli użytkownik już wcześniej wybrał kolejkę ręcznie
        if 'selected_round_idx' in st.session_state and st.session_state.get('user_manually_selected_round', False):
            default_round_idx = st.session_state.selected_round_idx
            logger.info(f"DEBUG input: Używam zapisanego wyboru użytkownika: {default_round_idx}")
        
        # Numeruj kolejki według daty asc (numer 1 = najstarsza), ale wyświetlaj sort desc (najnowsza pierwsza)
        round_options = []
        for date, matches in filtered_rounds:
            round_number = date_to_round_number[date]  # Numer według daty asc
            round_options.append(f"Kolejka {round_number} - {date} ({len(matches)} meczów)")
        
        selected_round_idx = st.selectbox("Wybierz rundę:", range(len(round_options)), index=default_round_idx, format_func=lambda x: round_options[x], key="round_select_main")
        
        # Zapisz wybór rundy w session_state (synchronizacja z rankingiem)
        # Oznacz że użytkownik wybrał kolejkę ręcznie (jeśli wybór różni się od domyślnego)
        if selected_round_idx != default_round_idx:
            st.session_state.user_manually_selected_round = True
        st.session_state.selected_round_idx = selected_round_idx
        
        if selected_round_idx is not None:
            selected_round_date, selected_matches = filtered_rounds[selected_round_idx]
            round_number = date_to_round_number[selected_round_date]  # Numer kolejki według daty asc (1 = najstarsza)
            round_id = f"round_{selected_round_date}"
            
            # Dodaj rundę do storage jeśli nie istnieje
            if round_id not in storage.data['rounds']:
                # Sezon zostanie automatycznie utworzony w add_round jeśli nie istnieje
                storage.add_round("current_season", round_id, selected_matches, selected_round_date)
            
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
            
            # Przycisk do dodawania nowego gracza
            col_add_player = st.columns([1])
            with col_add_player[0]:
                add_new_player = st.button("➕ Dodaj gracza", key="tipper_add_new_player_btn")
            
            # Dodawanie nowego gracza
            if add_new_player:
                with st.expander("➕ Dodaj nowego gracza", expanded=True):
                    new_player_name = st.text_input("Nazwa nowego gracza:", key="tipper_new_player_name")
                    if st.button("💾 Zapisz", key="tipper_save_new_player"):
                        if new_player_name:
                            if new_player_name not in storage.data['players']:
                                storage.data['players'][new_player_name] = {
                                    'predictions': {},
                                    'total_points': 0,
                                    'rounds_played': 0,
                                    'best_score': 0,
                                    'worst_score': float('inf')
                                }
                                storage._save_data()
                                st.success(f"✅ Dodano gracza: {new_player_name}")
                                st.rerun()
                            else:
                                st.warning("⚠️ Gracz już istnieje")
            
            # Lista graczy w kolejności alfabetycznej
            all_players_list = sorted(list(storage.data['players'].keys()))
            
            if not all_players_list:
                st.info("📊 Brak graczy. Dodaj nowego gracza.")
            else:
                # Wyświetl sekcję dla każdego gracza
                for player_name in all_players_list:
                    # Pobierz istniejące typy gracza dla tej rundy
                    existing_predictions = storage.get_player_predictions(player_name, round_id)
                    
                    st.markdown(f"### Typy dla: **{player_name}**")
                    
                    # Dwie kolumny obok siebie: Pojedyncze mecze i Bulk
                    col_single, col_bulk = st.columns(2)
                    
                    with col_single:
                        st.markdown("#### 📝 Pojedyncze mecze")
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
                                default_value = ""
                            
                            # Oblicz punkty jeśli mecz rozegrany
                            points_display = ""
                            if home_goals is not None and away_goals is not None and has_existing:
                                pred_home = existing_pred.get('home', 0)
                                pred_away = existing_pred.get('away', 0)
                                points = tipper.calculate_points((pred_home, pred_away), (int(home_goals), int(away_goals)))
                                points_display = f" | **Punkty: {points}**"
                            
                            col1, col2 = st.columns([3, 1.5])
                            with col1:
                                status_icon = "✅" if has_existing else "❌"
                                result_text = f" ({home_goals}-{away_goals})" if home_goals is not None and away_goals is not None else ""
                                st.write(f"{status_icon} **{home_team}** vs **{away_team}**{result_text} {points_display}")
                            with col2:
                                if can_edit:
                                    # Pole tekstowe bez automatycznego zapisu
                                    st.text_input(
                                        f"Typ:",
                                        value=default_value,
                                        key=f"tipper_pred_{player_name}_{match_id}",
                                        label_visibility="collapsed",
                                        placeholder="0-0"
                                    )
                                else:
                                    if is_historical:
                                        st.info("⏰ Rozegrany")
                                    else:
                                        st.warning("⏰ Rozpoczęty")
                        
                        # Przycisk do zapisania wszystkich typów
                        if st.button("💾 Zapisz typy", type="primary", key=f"tipper_save_all_{player_name}"):
                            # Zbierz wszystkie typy z pól tekstowych
                            predictions_to_save = {}
                            
                            for match in selected_matches:
                                match_id = str(match.get('match_id', ''))
                                input_key = f"tipper_pred_{player_name}_{match_id}"
                                
                                if input_key in st.session_state:
                                    pred_input = st.session_state[input_key]
                                    if pred_input and pred_input.strip():
                                        parsed = tipper.parse_prediction(pred_input)
                                        if parsed:
                                            predictions_to_save[match_id] = parsed
                            
                            if predictions_to_save:
                                saved_count = 0
                                updated_count = 0
                                
                                for match_id, prediction in predictions_to_save.items():
                                    # Sprawdź czy typ już istnieje
                                    is_update = match_id in existing_predictions
                                    
                                    # Sprawdź czy mecz można edytować
                                    match = next((m for m in selected_matches if str(m.get('match_id')) == match_id), None)
                                    can_add = True
                                    
                                    if match:
                                        match_date = match.get('match_date')
                                        if match_date:
                                            try:
                                                match_dt = datetime.strptime(match_date, "%Y-%m-%d %H:%M:%S")
                                                if datetime.now() >= match_dt:
                                                    can_add = allow_historical
                                            except:
                                                pass
                                    
                                    if can_add:
                                        storage.add_prediction(round_id, player_name, match_id, prediction)
                                        
                                        if is_update:
                                            updated_count += 1
                                        else:
                                            saved_count += 1
                                
                                total_saved = saved_count + updated_count
                                if total_saved > 0:
                                    if updated_count > 0 and saved_count > 0:
                                        st.success(f"✅ Zapisano {saved_count} nowych typów, zaktualizowano {updated_count} typów")
                                    elif updated_count > 0:
                                        st.success(f"✅ Zaktualizowano {updated_count} typów")
                                    else:
                                        st.success(f"✅ Zapisano {saved_count} typów")
                                    st.rerun()
                                else:
                                    st.warning("⚠️ Wszystkie mecze już rozpoczęte")
                            else:
                                st.info("ℹ️ Wprowadź typy przed zapisaniem")
                    
                    with col_bulk:
                        st.markdown("#### 📋 Wklej wszystkie (bulk)")
                        st.markdown("**Wklej typy w formacie:**")
                        st.markdown("*Format: Nazwa drużyny1 - Nazwa drużyny2 Wynik*")
                        st.markdown("*Przykład: Borciuchy International - WKS BRONEK 50 7:0*")
                        
                        predictions_text = st.text_area(
                            "Typy:",
                            height=300,
                            help="Wklej typy w formacie:\nBorciuchy International - WKS BRONEK 50 7:0\nMoli Team - Szmacianka Szynwałdzian 1:1\nLegiaWawa - ks Jastrowie 2:1",
                            key=f"tipper_bulk_text_{player_name}"
                        )
                        
                        if st.button("💾 Zapisz typy (bulk)", type="primary", key=f"tipper_bulk_save_{player_name}"):
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
                                                
                                                storage.add_prediction(round_id, player_name, match_id, prediction)
                                                
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
                                        st.rerun()
                                    else:
                                        if errors:
                                            st.error("❌ Nie udało się zapisać typów:\n" + "\n".join(errors[:5]))
                                        else:
                                            st.warning("⚠️ Wszystkie mecze już rozpoczęte")
                                else:
                                    st.error("❌ Nie można sparsować typów. Sprawdź format:\n- Nazwa drużyny1 - Nazwa drużyny2 Wynik\n- Przykład: Borciuchy International - WKS BRONEK 50 7:0")
                    
                    # Dodaj separator między graczami
                    st.markdown("---")
            
    
    except Exception as e:
        error_msg = str(e)
        # Jeśli błąd to tuple (np. z pymysql), wyświetl czytelniejszy komunikat
        if isinstance(e, tuple) and len(e) == 2:
            error_code, error_message = e
            if error_message:
                error_msg = f"Błąd MySQL ({error_code}): {error_message}"
            else:
                error_msg = f"Błąd MySQL (kod: {error_code})"
        st.error(f"❌ Błąd: {error_msg}")
        logger.error(f"Błąd typera: {e}", exc_info=True)


if __name__ == "__main__":
    main()

