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
import numpy as np

logger = logging.getLogger(__name__)


def get_all_time_leaderboard_for_login(exclude_worst: bool = False):
    """
    Oblicza ranking wszechczasów - suma punktów ze wszystkich sezonów dla każdego gracza
    (wersja dla ekranu logowania)
    
    Args:
        exclude_worst: Czy odrzucić najgorszy wynik z każdego sezonu
    
    Returns:
        Lista słowników z danymi graczy posortowana po sumie punktów (malejąco)
    """
    import glob
    import re
    import json
    from typing import List, Dict
    
    # Znajdź wszystkie pliki sezonów
    pattern = os.path.join(os.getcwd(), "tipper_data_season_*.json")
    files = glob.glob(pattern)
    
    # Słownik do przechowywania sum punktów dla każdego gracza
    players_total = {}  # {player_name: {'total': int, 'seasons': int, 'rounds': int, 'seasons_data': {season_id: points}}}
    
    # Przejdź przez wszystkie pliki sezonów
    for file_path in files:
        try:
            filename = os.path.basename(file_path)
            match = re.search(r'tipper_data_season_(\d+)\.json', filename)
            if not match:
                continue
            
            season_num = int(match.group(1))
            season_id = f"season_{season_num}"
            
            # Wczytaj dane sezonu
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            # Pobierz graczy z sezonu (najpierw sprawdź w seasons, potem w players)
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
                
                # Pobierz punkty gracza
                total_points = player_data.get('total_points', 0)
                worst_score = player_data.get('worst_score', 0)
                rounds_played = player_data.get('rounds_played', 0)
                
                # Odrzuć najgorszy wynik jeśli exclude_worst=True
                if exclude_worst and worst_score > 0:
                    season_points = total_points - worst_score
                else:
                    season_points = total_points
                
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
    Ładuje użytkowników z zmiennych środowiskowych
    
    Format w .env:
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
    load_dotenv()
    users = {}
    
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
        from tipper_storage import TipperStorage
        storage = TipperStorage()
        
        # Ranking - sekcja read-only
        st.subheader("🏆 Ranking (tylko do odczytu)")
        st.info("💡 Ranking jest widoczny publicznie. Zaloguj się aby wprowadzać typy.")
        
        # Tabs dla rankingu per kolejka, całości i wszechczasów
        ranking_tab1, ranking_tab2, ranking_tab3 = st.tabs(["🏆 Ranking całości", "📊 Ranking per kolejka", "🌟 Ranking wszechczasów"])
        
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
                    
                    # Rozbudowane raporty
                    st.markdown("---")
                    st.markdown("### 📊 Szczegółowe raporty")
                    
                    # Progress chart - punkty przez kolejki
                    if leaderboard and any(p.get('round_points') for p in leaderboard):
                        st.markdown("#### 📈 Progress przez kolejki")
                        progress_data = []
                        for player in leaderboard:
                            round_points = player.get('round_points', [])
                            if round_points:
                                cumulative = 0
                                for idx, points in enumerate(round_points, 1):
                                    cumulative += points
                                    progress_data.append({
                                        'Kolejka': idx,
                                        'Gracz': player['player_name'],
                                        'Punkty w kolejce': points,
                                        'Punkty łącznie': cumulative
                                    })
                        
                        if progress_data:
                            df_progress = pd.DataFrame(progress_data)
                            fig = px.line(
                                df_progress,
                                x='Kolejka',
                                y='Punkty łącznie',
                                color='Gracz',
                                title="Progress punktów przez kolejki",
                                markers=True
                            )
                            fig.update_layout(height=400)
                            st.plotly_chart(fig, use_container_width=True, key="login_progress_chart")
                    
                    # Heatmapa punktów przez kolejki
                    if leaderboard and any(p.get('round_points') for p in leaderboard):
                        st.markdown("#### 🔥 Heatmapa punktów przez kolejki")
                        heatmap_data = []
                        max_rounds = max(len(p.get('round_points', [])) for p in leaderboard if p.get('round_points'))
                        for player in leaderboard:
                            round_points = player.get('round_points', [])
                            for idx in range(1, max_rounds + 1):
                                points = round_points[idx - 1] if idx <= len(round_points) else 0
                                heatmap_data.append({
                                    'Gracz': player['player_name'],
                                    'Kolejka': idx,
                                    'Punkty': points
                                })
                        
                        if heatmap_data:
                            df_heatmap = pd.DataFrame(heatmap_data)
                            pivot_heatmap = df_heatmap.pivot(index='Gracz', columns='Kolejka', values='Punkty')
                            fig = px.imshow(
                                pivot_heatmap,
                                title="Heatmapa punktów przez kolejki",
                                labels=dict(x="Kolejka", y="Gracz", color="Punkty"),
                                color_continuous_scale='YlOrRd'
                            )
                            fig.update_layout(height=400)
                            st.plotly_chart(fig, use_container_width=True, key="login_heatmap_chart")
                    
                    # Box plot rozkładu punktów
                    if leaderboard and any(p.get('round_points') for p in leaderboard):
                        st.markdown("#### 📦 Rozkład punktów")
                        box_data = []
                        for player in leaderboard:
                            round_points = player.get('round_points', [])
                            if round_points:
                                for points in round_points:
                                    box_data.append({
                                        'Gracz': player['player_name'],
                                        'Punkty': points
                                    })
                        
                        if box_data:
                            df_box = pd.DataFrame(box_data)
                            fig = px.box(
                                df_box,
                                x='Gracz',
                                y='Punkty',
                                title="Rozkład punktów graczy",
                                color='Gracz'
                            )
                            fig.update_layout(xaxis_tickangle=-45, height=400, showlegend=False)
                            st.plotly_chart(fig, use_container_width=True, key="login_boxplot_chart")
                    
                    # Consistency score (odchylenie standardowe)
                    if leaderboard and any(p.get('round_points') for p in leaderboard):
                        st.markdown("#### 📊 Consistency (stabilność wyników)")
                        consistency_data = []
                        for player in leaderboard:
                            round_points = player.get('round_points', [])
                            if round_points and len(round_points) > 1:
                                std_dev = np.std(round_points)
                                consistency_data.append({
                                    'Gracz': player['player_name'],
                                    'Odchylenie standardowe': round(std_dev, 2),
                                    'Średnia': round(np.mean(round_points), 2)
                                })
                        
                        if consistency_data:
                            df_consistency = pd.DataFrame(consistency_data)
                            df_consistency = df_consistency.sort_values('Odchylenie standardowe')
                            fig = px.bar(
                                df_consistency,
                                x='Gracz',
                                y='Odchylenie standardowe',
                                title="Consistency - niższe = bardziej stabilne wyniki",
                                color='Odchylenie standardowe',
                                color_continuous_scale='RdYlGn_r'
                            )
                            fig.update_layout(xaxis_tickangle=-45, height=400)
                            st.plotly_chart(fig, use_container_width=True, key="login_consistency_chart")
                            st.dataframe(df_consistency, use_container_width=True, hide_index=True)
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
                            break  # Weź pierwszą (najnowszą) rozegraną kolejkę
                    
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
                                
                                # Rozbudowane raporty dla kolejki
                                st.markdown("---")
                                st.markdown("### 📊 Szczegółowe raporty kolejki")
                                
                                # Statystyki kolejki
                                col1, col2, col3, col4 = st.columns(4)
                                with col1:
                                    avg_points = np.mean([p['total_points'] for p in round_leaderboard]) if round_leaderboard else 0
                                    st.metric("Średnia punktów", f"{avg_points:.1f}")
                                with col2:
                                    max_points = max([p['total_points'] for p in round_leaderboard]) if round_leaderboard else 0
                                    st.metric("Najwięcej punktów", max_points)
                                with col3:
                                    min_points = min([p['total_points'] for p in round_leaderboard]) if round_leaderboard else 0
                                    st.metric("Najmniej punktów", min_points)
                                with col4:
                                    st.metric("Liczba graczy", len(round_leaderboard))
                                
                                # Porównanie z poprzednimi kolejkami
                                if len(round_options) > 1 and selected_round_idx > 0:
                                    st.markdown("#### 📈 Porównanie z poprzednimi kolejkami")
                                    comparison_data = []
                                    # Pobierz dane z ostatnich 5 kolejek
                                    for i in range(max(0, selected_round_idx - 4), selected_round_idx + 1):
                                        round_id_comp, date_comp, _ = round_options[i]
                                        round_lb = storage.get_round_leaderboard(round_id_comp)
                                        round_num_comp = date_to_round_number.get(round_id_comp, '?')
                                        
                                        for player in round_lb:
                                            comparison_data.append({
                                                'Kolejka': f"K{round_num_comp}",
                                                'Gracz': player['player_name'],
                                                'Punkty': player['total_points']
                                            })
                                    
                                    if comparison_data:
                                        df_comp = pd.DataFrame(comparison_data)
                                        fig = px.line(
                                            df_comp,
                                            x='Kolejka',
                                            y='Punkty',
                                            color='Gracz',
                                            title="Trend punktów przez ostatnie kolejki",
                                            markers=True
                                        )
                                        fig.update_layout(height=400)
                                        st.plotly_chart(fig, use_container_width=True, key=f"login_round_comparison_{round_number}")
                                
                                # Histogram rozkładu punktów
                                st.markdown("#### 📊 Rozkład punktów w kolejce")
                                points_list = [p['total_points'] for p in round_leaderboard]
                                if points_list:
                                    fig = px.histogram(
                                        x=points_list,
                                        title="Rozkład punktów w kolejce",
                                        labels={'x': 'Punkty', 'y': 'Liczba graczy'},
                                        nbins=20
                                    )
                                    fig.update_layout(height=300)
                                    st.plotly_chart(fig, use_container_width=True, key=f"login_round_histogram_{round_number}")
                        else:
                            st.info("📊 Brak danych do wyświetlenia dla tej kolejki")
                else:
                    st.info("📊 Brak rund do wyświetlenia")
            else:
                st.info("📊 Brak danych do wyświetlenia")
        
        # Ranking wszechczasów
        with ranking_tab3:
            st.markdown("### 🌟 Ranking wszechczasów")
            st.info("💡 Suma punktów ze wszystkich sezonów")
            
            exclude_worst = st.checkbox("Odrzuć najgorszy wynik każdego gracza z każdego sezonu", value=True, key="login_exclude_worst_alltime")
            
            # Oblicz ranking wszechczasów
            all_time_leaderboard = get_all_time_leaderboard_for_login(exclude_worst=exclude_worst)
            
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
                    st.plotly_chart(fig, use_container_width=True, key="login_ranking_alltime_chart")
                    
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
                    
                    # Rozbudowane raporty wszechczasów
                    st.markdown("---")
                    st.markdown("### 📊 Szczegółowe raporty wszechczasów")
                    
                    # Wykres liniowy - punkty przez sezony dla każdego gracza
                    st.markdown("#### 📈 Progress przez sezony")
                    seasons_progress_data = []
                    all_seasons = set()
                    for player in all_time_leaderboard:
                        for season_id, points in player['seasons_data'].items():
                            season_num = int(season_id.replace('season_', ''))
                            all_seasons.add(season_num)
                            seasons_progress_data.append({
                                'Sezon': season_num,
                                'Gracz': player['player_name'],
                                'Punkty': points
                            })
                    
                    if seasons_progress_data:
                        df_seasons_progress = pd.DataFrame(seasons_progress_data)
                        df_seasons_progress = df_seasons_progress.sort_values('Sezon')
                        fig = px.line(
                            df_seasons_progress,
                            x='Sezon',
                            y='Punkty',
                            color='Gracz',
                            title="Punkty graczy przez sezony",
                            markers=True
                        )
                        fig.update_layout(height=400)
                        st.plotly_chart(fig, use_container_width=True, key="login_alltime_progress_chart")
                    
                    # Heatmapa punktów przez sezony
                    st.markdown("#### 🔥 Heatmapa punktów przez sezony")
                    heatmap_seasons_data = []
                    sorted_seasons = sorted(all_seasons)
                    for player in all_time_leaderboard:
                        for season_num in sorted_seasons:
                            season_id = f"season_{season_num}"
                            points = player['seasons_data'].get(season_id, 0)
                            heatmap_seasons_data.append({
                                'Gracz': player['player_name'],
                                'Sezon': season_num,
                                'Punkty': points
                            })
                    
                    if heatmap_seasons_data:
                        df_heatmap_seasons = pd.DataFrame(heatmap_seasons_data)
                        pivot_heatmap_seasons = df_heatmap_seasons.pivot(index='Gracz', columns='Sezon', values='Punkty')
                        fig = px.imshow(
                            pivot_heatmap_seasons,
                            title="Heatmapa punktów przez sezony",
                            labels=dict(x="Sezon", y="Gracz", color="Punkty"),
                            color_continuous_scale='YlOrRd'
                        )
                        fig.update_layout(height=400)
                        st.plotly_chart(fig, use_container_width=True, key="login_alltime_heatmap_chart")
                    
                    # Najlepsze sezony (top 10)
                    st.markdown("#### 🏆 Najlepsze sezony graczy")
                    best_seasons_data = []
                    for player in all_time_leaderboard:
                        for season_id, points in player['seasons_data'].items():
                            season_num = int(season_id.replace('season_', ''))
                            best_seasons_data.append({
                                'Gracz': player['player_name'],
                                'Sezon': season_num,
                                'Punkty': points
                            })
                    
                    if best_seasons_data:
                        df_best_seasons = pd.DataFrame(best_seasons_data)
                        df_best_seasons = df_best_seasons.nlargest(10, 'Punkty')
                        fig = px.bar(
                            df_best_seasons,
                            x='Gracz',
                            y='Punkty',
                            color='Sezon',
                            title="Top 10 najlepszych sezonów",
                            labels={'Punkty': 'Punkty', 'Gracz': 'Gracz'}
                        )
                        fig.update_layout(xaxis_tickangle=-45, height=400)
                        st.plotly_chart(fig, use_container_width=True, key="login_best_seasons_chart")
                    
                    # Consistency score przez sezony
                    st.markdown("#### 📊 Consistency przez sezony (stabilność)")
                    consistency_seasons_data = []
                    for player in all_time_leaderboard:
                        season_points = list(player['seasons_data'].values())
                        if season_points and len(season_points) > 1:
                            std_dev = np.std(season_points)
                            consistency_seasons_data.append({
                                'Gracz': player['player_name'],
                                'Odchylenie standardowe': round(std_dev, 2),
                                'Średnia punktów/sezon': round(np.mean(season_points), 2),
                                'Liczba sezonów': len(season_points)
                            })
                    
                    if consistency_seasons_data:
                        df_consistency_seasons = pd.DataFrame(consistency_seasons_data)
                        df_consistency_seasons = df_consistency_seasons.sort_values('Odchylenie standardowe')
                        fig = px.bar(
                            df_consistency_seasons,
                            x='Gracz',
                            y='Odchylenie standardowe',
                            title="Consistency przez sezony - niższe = bardziej stabilne",
                            color='Odchylenie standardowe',
                            color_continuous_scale='RdYlGn_r'
                        )
                        fig.update_layout(xaxis_tickangle=-45, height=400)
                        st.plotly_chart(fig, use_container_width=True, key="login_alltime_consistency_chart")
                        st.dataframe(df_consistency_seasons, use_container_width=True, hide_index=True)
                    
                    # Porównanie graczy (wybór 2-3 graczy)
                    if len(all_time_leaderboard) >= 2:
                        st.markdown("#### 🔀 Porównanie graczy")
                        selected_players = st.multiselect(
                            "Wybierz graczy do porównania:",
                            options=[p['player_name'] for p in all_time_leaderboard],
                            default=[p['player_name'] for p in all_time_leaderboard[:3]] if len(all_time_leaderboard) >= 3 else [p['player_name'] for p in all_time_leaderboard],
                            key="login_compare_players"
                        )
                        
                        if selected_players:
                            comparison_players_data = []
                            for player in all_time_leaderboard:
                                if player['player_name'] in selected_players:
                                    for season_id, points in sorted(player['seasons_data'].items(), key=lambda x: int(x[0].replace('season_', ''))):
                                        season_num = int(season_id.replace('season_', ''))
                                        comparison_players_data.append({
                                            'Sezon': season_num,
                                            'Gracz': player['player_name'],
                                            'Punkty': points
                                        })
                            
                            if comparison_players_data:
                                df_comparison = pd.DataFrame(comparison_players_data)
                                fig = px.line(
                                    df_comparison,
                                    x='Sezon',
                                    y='Punkty',
                                    color='Gracz',
                                    title="Porównanie graczy przez sezony",
                                    markers=True
                                )
                                fig.update_layout(height=400)
                                st.plotly_chart(fig, use_container_width=True, key="login_players_comparison_chart")
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

