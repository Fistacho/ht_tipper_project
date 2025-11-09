"""
Moduł autentykacji dla aplikacji Hattrick Typer
"""
import streamlit as st
import hashlib
import os
from typing import Optional, Dict
from dotenv import load_dotenv
import logging
import pandas as pd
import plotly.express as px

logger = logging.getLogger(__name__)


def hash_password(password: str, salt: str = None) -> tuple:
    """
    Haszuje hasło używając SHA256 z solą
    
    Args:
        password: Hasło do zahaszowania
        salt: Opcjonalna sól (jeśli None, zostanie wygenerowana)
        
    Returns:
        Tuple (hashed_password, salt)
    """
    if salt is None:
        # Generuj sól z hasła (dla prostoty, w produkcji użyj secrets.token_hex)
        salt = hashlib.sha256(password.encode()).hexdigest()[:16]
    
    # Haszuj hasło z solą
    hashed = hashlib.sha256((password + salt).encode()).hexdigest()
    return hashed, salt


def verify_password(password: str, hashed_password: str, salt: str) -> bool:
    """
    Weryfikuje hasło
    
    Args:
        password: Hasło do sprawdzenia
        hashed_password: Zahaszowane hasło
        salt: Sól użyta do haszowania
        
    Returns:
        True jeśli hasło jest poprawne, False w przeciwnym razie
    """
    hashed, _ = hash_password(password, salt)
    return hashed == hashed_password


def load_users() -> Dict[str, Dict[str, str]]:
    """
    Ładuje użytkowników z Streamlit secrets lub zmiennych środowiskowych
    
    Format w Streamlit secrets lub .env:
    APP_USERNAME=admin
    APP_PASSWORD_HASH=hashed_password
    APP_PASSWORD_SALT=salt
    
    Lub dla wielu użytkowników:
    APP_USER_1_USERNAME=user1
    APP_USER_1_PASSWORD_HASH=hash1
    APP_USER_1_PASSWORD_SALT=salt1
    APP_USER_2_USERNAME=user2
    APP_USER_2_PASSWORD_HASH=hash2
    APP_USER_2_PASSWORD_SALT=salt2
    
    Returns:
        Dict z username -> {password_hash, salt}
    """
    users = {}
    
    # Najpierw spróbuj odczytać z Streamlit secrets (dla Streamlit Cloud)
    try:
        if hasattr(st, 'secrets'):
            # Sprawdź pojedynczego użytkownika (stary format)
            try:
                username = getattr(st.secrets, 'APP_USERNAME', None)
                password_hash = getattr(st.secrets, 'APP_PASSWORD_HASH', None)
                password_salt = getattr(st.secrets, 'APP_PASSWORD_SALT', None)
                
                if username and password_hash and password_salt:
                    users[username] = {
                        'password_hash': password_hash,
                        'salt': password_salt
                    }
                    logger.info(f"DEBUG: Użytkownik {username} odczytany z secrets")
                else:
                    logger.info("DEBUG: APP_USERNAME nie odczytany z secrets")
            except (AttributeError, KeyError) as e:
                logger.info(f"DEBUG: Błąd odczytu autentykacji z secrets: {e}")
            
            # Sprawdź wielu użytkowników (nowy format)
            i = 1
            while True:
                try:
                    user_username = getattr(st.secrets, f'APP_USER_{i}_USERNAME', None)
                    user_password_hash = getattr(st.secrets, f'APP_USER_{i}_PASSWORD_HASH', None)
                    user_password_salt = getattr(st.secrets, f'APP_USER_{i}_PASSWORD_SALT', None)
                    
                    if not user_username:
                        break
                    
                    if user_password_hash and user_password_salt:
                        users[user_username] = {
                            'password_hash': user_password_hash,
                            'salt': user_password_salt
                        }
                    i += 1
                except (AttributeError, KeyError):
                    break
    except (AttributeError, KeyError) as e:
        logger.info(f"DEBUG: Błąd przy próbie odczytu secrets: {e}")
    
    # Jeśli nie ma secrets lub nie znaleziono użytkowników, spróbuj z .env (dla lokalnego rozwoju)
    if not users:
        load_dotenv()
        
        # Sprawdź pojedynczego użytkownika (stary format)
        username = os.getenv('APP_USERNAME')
        password_hash = os.getenv('APP_PASSWORD_HASH')
        password_salt = os.getenv('APP_PASSWORD_SALT')
        
        if username and password_hash and password_salt:
            users[username] = {
                'password_hash': password_hash,
                'salt': password_salt
            }
        
        # Sprawdź wielu użytkowników (nowy format)
        i = 1
        while True:
            user_username = os.getenv(f'APP_USER_{i}_USERNAME')
            user_password_hash = os.getenv(f'APP_USER_{i}_PASSWORD_HASH')
            user_password_salt = os.getenv(f'APP_USER_{i}_PASSWORD_SALT')
            
            if not user_username:
                break
            
            if user_password_hash and user_password_salt:
                users[user_username] = {
                    'password_hash': user_password_hash,
                    'salt': user_password_salt
                }
            i += 1
    
    # Jeśli nie ma żadnych użytkowników, utwórz domyślnego
    if not users:
        logger.warning("Brak skonfigurowanych użytkowników, używam domyślnego (admin/admin)")
        default_hash, default_salt = hash_password("admin")
        users["admin"] = {
            'password_hash': default_hash,
            'salt': default_salt
        }
    
    return users


def check_authentication() -> bool:
    """
    Sprawdza czy użytkownik jest zalogowany
    
    Returns:
        True jeśli użytkownik jest zalogowany, False w przeciwnym razie
    """
    return st.session_state.get('authenticated', False)


def login_page() -> bool:
    """
    Wyświetla stronę logowania i weryfikuje dane
    
    Returns:
        True jeśli logowanie się powiodło, False w przeciwnym razie
    """
    # Wyświetl ranking (read-only) przed formularzem logowania
    try:
        from tipper_storage import get_storage
        storage = get_storage()
        
        # Ranking - sekcja read-only
        st.subheader("🏆 Ranking (tylko do odczytu)")
        st.info("💡 Ranking jest widoczny publicznie. Zaloguj się aby wprowadzać typy.")
        
        # Tabs dla rankingu per kolejka i całości
        ranking_tab1, ranking_tab2 = st.tabs(["🏆 Ranking całości", "📊 Ranking per kolejka"])
        
        # Ranking całości
        with ranking_tab1:
            st.markdown("### 🏆 Ranking całości")
            
            exclude_worst = st.checkbox("Odrzuć najgorszy wynik każdego gracza", value=True, key="login_exclude_worst_overall")
            leaderboard = storage.get_leaderboard(exclude_worst=exclude_worst)
            
            if leaderboard:
                # Przygotuj dane do wyświetlenia
                leaderboard_data = []
                for idx, player in enumerate(leaderboard, 1):
                    round_points = player.get('round_points', [])
                    original_total = player.get('original_total', player['total_points'])
                    
                    if round_points:
                        points_str = ' + '.join(str(p) for p in round_points)
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
                    st.plotly_chart(fig, use_container_width=True, key="login_ranking_overall_chart")
                    
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
        
        # Ranking per kolejka
        with ranking_tab2:
            st.markdown("### 📊 Ranking per kolejka")
            
            # Pobierz wszystkie rundy z storage
            all_rounds = sorted(storage.data['rounds'].items(), key=lambda x: x[1].get('start_date', ''))
            
            if all_rounds:
                # Stwórz listę opcji rund
                round_options = []
                for round_id, round_data in all_rounds:
                    start_date = round_data.get('start_date', '')
                    matches_count = len(round_data.get('matches', []))
                    # Wyciągnij datę z round_id (format: round_2025-11-09)
                    if start_date:
                        try:
                            date_str = start_date.split()[0] if ' ' in start_date else start_date
                            round_options.append((round_id, date_str, matches_count))
                        except:
                            round_options.append((round_id, start_date, matches_count))
                    else:
                        # Spróbuj wyciągnąć datę z round_id
                        if round_id.startswith('round_'):
                            date_str = round_id.replace('round_', '')
                            round_options.append((round_id, date_str, matches_count))
                
                if round_options:
                    # Sortuj po dacie (najnowsza pierwsza)
                    round_options.sort(key=lambda x: x[1], reverse=True)
                    
                    # Numeruj kolejki (najstarsza = 1)
                    date_to_round_number = {}
                    sorted_by_date = sorted(round_options, key=lambda x: x[1])
                    for idx, (round_id, date_str, _) in enumerate(sorted_by_date, 1):
                        date_to_round_number[round_id] = idx
                    
                    # Znajdź ostatnią rozegraną kolejkę (domyślnie)
                    # round_options jest posortowane DESC (najnowsza pierwsza), więc szukamy pierwszej rozegranej
                    default_round_idx = 0
                    for idx, (round_id, _, _) in enumerate(round_options):
                        round_data = storage.data['rounds'].get(round_id, {})
                        matches = round_data.get('matches', [])
                        # Sprawdź czy kolejka ma rozegrane mecze
                        has_played = any(
                            m.get('home_goals') is not None and m.get('away_goals') is not None 
                            for m in matches
                        )
                        if has_played:
                            default_round_idx = idx
                            break  # Znajdź pierwszą (najnowszą) rozegraną kolejkę w liście
                    
                    # Wybór rundy
                    round_display_options = [f"Kolejka {date_to_round_number.get(rid, '?')} - {date} ({matches} meczów)" 
                                            for rid, date, matches in round_options]
                    
                    selected_round_idx = st.selectbox(
                        "Wybierz rundę:",
                        range(len(round_display_options)),
                        index=default_round_idx,
                        format_func=lambda x: round_display_options[x],
                        key="login_ranking_round_select"
                    )
                    
                    if selected_round_idx is not None:
                        selected_round_id, selected_date, _ = round_options[selected_round_idx]
                        round_number = date_to_round_number.get(selected_round_id, '?')
                        
                        # Ranking dla wybranej rundy
                        round_leaderboard = storage.get_round_leaderboard(selected_round_id)
                        
                        if round_leaderboard:
                            # Pobierz mecze z rundy dla wyświetlenia typów
                            round_data = storage.data['rounds'].get(selected_round_id, {})
                            matches = round_data.get('matches', [])
                            matches_map = {str(m.get('match_id', '')): m for m in matches}
                            
                            # Przygotuj dane do wyświetlenia (bez kolumny Typy)
                            round_leaderboard_data = []
                            for idx, player in enumerate(round_leaderboard, 1):
                                match_points = player.get('match_points', [])
                                if match_points:
                                    points_str = '+'.join(str(p) for p in match_points)
                                    if player['total_points'] > 0:
                                        points_summary = f"{points_str}={player['total_points']}"
                                    else:
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
                                player_predictions = storage.get_player_predictions(player_name, selected_round_id)
                                
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
                                st.plotly_chart(fig, use_container_width=True, key=f"login_ranking_round_{round_number}_chart")
                        else:
                            st.info("📊 Brak danych do wyświetlenia dla tej kolejki")
                else:
                    st.info("📊 Brak rund do wyświetlenia")
            else:
                st.info("📊 Brak danych do wyświetlenia")
        
        st.markdown("---")
    except Exception as e:
        logger.error(f"Błąd wyświetlania rankingu: {e}")
        # Kontynuuj bez rankingu jeśli wystąpi błąd
    
    # Formularz logowania
    users = load_users()
    
    if not users:
        st.error("❌ Brak skonfigurowanych użytkowników. Skonfiguruj użytkowników w pliku .env")
        return False
    
    with st.form("login_form"):
        username = st.text_input("👤 Nazwa użytkownika", key="login_username")
        password = st.text_input("🔒 Hasło", type="password", key="login_password")
        submit_button = st.form_submit_button("🚀 Zaloguj się", use_container_width=True)
        
        if submit_button:
            if not username or not password:
                st.error("❌ Wprowadź nazwę użytkownika i hasło")
                return False
            
            if username in users:
                user_data = users[username]
                if verify_password(password, user_data['password_hash'], user_data['salt']):
                    st.session_state['authenticated'] = True
                    st.session_state['username'] = username
                    st.success(f"✅ Zalogowano jako {username}")
                    st.rerun()
                else:
                    st.error("❌ Nieprawidłowe hasło")
                    return False
            else:
                st.error("❌ Nieprawidłowa nazwa użytkownika")
                return False
    
    return False


def logout():
    """Wylogowuje użytkownika"""
    if 'authenticated' in st.session_state:
        del st.session_state['authenticated']
    if 'username' in st.session_state:
        del st.session_state['username']
    st.rerun()


def require_auth(func):
    """
    Dekorator wymagający autentykacji przed wykonaniem funkcji
    
    Usage:
        @require_auth
        def my_function():
            ...
    """
    def wrapper(*args, **kwargs):
        if not check_authentication():
            if not login_page():
                return
        return func(*args, **kwargs)
    return wrapper


def generate_password_hash(password: str) -> tuple:
    """
    Generuje hash i sól dla hasła (użyteczne do konfiguracji)
    
    Args:
        password: Hasło do zahaszowania
        
    Returns:
        Tuple (hashed_password, salt) - użyj tych wartości w .env
    """
    hashed, salt = hash_password(password)
    return hashed, salt

