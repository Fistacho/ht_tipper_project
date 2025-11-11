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
import logging
import sys
from logging.handlers import RotatingFileHandler
import faulthandler

# Twarda konfiguracja logowania (wymuś handlery i rotację pliku)
root_logger = logging.getLogger()
for h in root_logger.handlers[:]:
    root_logger.removeHandler(h)

# Poziom logowania z konfiguracji
def _resolve_log_level() -> int:
    try:
        # 1) .env
        env_level = os.getenv('LOG_LEVEL')
        # 2) secrets (jeśli dostępne)
        secrets_level = None
        try:
            if hasattr(st, 'secrets'):
                secrets_level = getattr(st.secrets, 'LOG_LEVEL', None)
        except Exception:
            pass
        level_name = (env_level or secrets_level)
        if not level_name:
            # Jeśli środowisko prod – loguj tylko ERROR
            app_env = (os.getenv('APP_ENV') or os.getenv('ENV') or '').lower()
            level_name = 'ERROR' if app_env in ('prod', 'production') else 'INFO'
        return getattr(logging, str(level_name).upper(), logging.INFO)
    except Exception:
        return logging.INFO

_LOG_LEVEL = _resolve_log_level()

file_handler = RotatingFileHandler('tipper.log', maxBytes=1_000_000, backupCount=3, encoding='utf-8')
file_handler.setLevel(_LOG_LEVEL)
stream_handler = logging.StreamHandler(sys.stdout)
stream_handler.setLevel(_LOG_LEVEL)

logging.basicConfig(
    level=_LOG_LEVEL,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[file_handler, stream_handler],
    force=True
)
logger = logging.getLogger(__name__)

# Zapisz nieprzechwycone wyjątki do logów
def _uncaught_excepthook(exc_type, exc, tb):
    logging.getLogger("uncaught").exception("Uncaught exception", exc_info=(exc_type, exc, tb))
sys.excepthook = _uncaught_excepthook

# Włącz faulthandler także dla segmentacji i twardych padów
try:
    _fh = open('tipper_crash.log', 'a', encoding='utf-8')
    faulthandler.enable(file=_fh, all_threads=True)
except Exception:
    pass

# Cache API Hattrick: fixtures i sezon na ligę
@st.cache_data(ttl=300)
def cached_get_league_fixtures(league_id: int, consumer_key: str, consumer_secret: str, access_token: str, access_token_secret: str):
    from hattrick_oauth_simple import HattrickOAuthSimple
    client = HattrickOAuthSimple(consumer_key, consumer_secret)
    client.set_access_tokens(access_token, access_token_secret)
    league_data = client.get_league_fixtures(league_id)
    return league_data or {}

# Funkcja pomocnicza do logowania bezpośrednio do pliku
def log_to_file(message):
    """Loguje wiadomość bezpośrednio do pliku"""
    try:
        with open('tipper.log', 'a', encoding='utf-8') as f:
            f.write(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} - {message}\n")
            f.flush()
    except Exception as e:
        print(f"Błąd zapisu do pliku logów: {e}")


def safe_int(value, default=0):
    """Bezpiecznie konwertuje wartość na int, obsługując NaN i None"""
    import math
    if value is None:
        return default
    try:
        # Sprawdź czy to NaN
        if isinstance(value, float) and math.isnan(value):
            return default
        return int(float(value))
    except (ValueError, TypeError):
        return default


def is_match_finished(match: dict) -> bool:
    """
    Sprawdza TYLKO flagę z API/DB: match['is_finished'] (lub podobną).
    NIE używa żadnych heurystyk ani fallbacków.
    """
    try:
        # 1) Sprawdź bezpośredni sygnał z API/DB
        for key in ('is_finished', 'finished'):
            if key in match and match[key] is not None:
                try:
                    return bool(int(match[key]))
                except Exception:
                    return bool(match[key])
        
        # 2) Sprawdź status z API
        status = str(match.get('status', '')).lower()
        if status in ('finished', 'played', 'completed', 'ended'):
            return True
        
        # 3) Jeśli nie ma żadnej flagi z API/DB, mecz NIE jest zakończony
        return False
    except Exception:
        return False

# Cache: rankingi i typy (cache zależny od sezonu/rundy i wersji danych)
@st.cache_data(ttl=180, show_spinner=False)
def cached_overall_leaderboard(season_id: str, exclude_worst: bool, data_version: int):
    storage = st.session_state.get('shared_storage')
    return storage.get_leaderboard(exclude_worst=exclude_worst, season_id=season_id)


@st.cache_data(ttl=180, show_spinner=False)
def cached_round_leaderboard(round_id: str, data_version: int):
    storage = st.session_state.get('shared_storage')
    return storage.get_round_leaderboard(round_id)


@st.cache_data(ttl=120, show_spinner=False)
def cached_player_predictions(player_name: str, round_id: str, data_version: int):
    storage = st.session_state.get('shared_storage')
    return storage.get_player_predictions(player_name, round_id, use_cache=True)


def get_league_name_for_match(storage, match: dict, round_id: str) -> str:
    """Zwraca nazwę ligi dla meczu na podstawie danych z bazy (DB-first)."""
    try:
        # Najpierw spróbuj użyć mapy drużyna->liga przygotowanej dla widoku (bardziej wiarygodna dla UI)
        teams_map = st.session_state.get('teams_with_leagues')
        if teams_map:
            home_team = (match.get('home_team_name') or '').strip()
            away_team = (match.get('away_team_name') or '').strip()
            if home_team in teams_map:
                return teams_map[home_team]
            if away_team in teams_map:
                return teams_map[away_team]

        league_id = match.get('league_id')
        if not league_id or str(league_id).lower() == 'none':
            round_data = storage.data.get('rounds', {}).get(round_id, {})
            season_id = round_data.get('season_id')
            if season_id:
                season = storage.data.get('seasons', {}).get(season_id, {})
                league_id = season.get('league_id')
        if not league_id:
            return "Liga ?"
        league_names_map = st.session_state.get('league_names_map', {})
        try:
            lid_int = int(league_id)
        except Exception:
            lid_int = league_id
        return league_names_map.get(lid_int, f"Liga {league_id}")
    except Exception:
        return "Liga ?"

# Pomocnik: pobierz klucze OAuth z ENV lub Secrets
def _get_oauth_keys():
    import os
    ck = os.getenv('HATTRICK_CONSUMER_KEY') or st.secrets.get('HATTRICK_CONSUMER_KEY', '')
    cs = os.getenv('HATTRICK_CONSUMER_SECRET') or st.secrets.get('HATTRICK_CONSUMER_SECRET', '')
    at = os.getenv('HATTRICK_ACCESS_TOKEN') or st.secrets.get('HATTRICK_ACCESS_TOKEN', '')
    ats = os.getenv('HATTRICK_ACCESS_TOKEN_SECRET') or st.secrets.get('HATTRICK_ACCESS_TOKEN_SECRET', '')
    return ck, cs, at, ats


def refresh_round_from_api(storage, round_id: str, matches: List[dict]):
    """Odświeża dane z API dla konkretnej kolejki"""
    try:
        logger.info(f"🔄 Rozpoczynam odświeżanie kolejki {round_id} z API")
        logger.info(f"📊 Otrzymano {len(matches)} meczów do sprawdzenia")
        
        # Pobierz ligi z meczów w tej kolejce
        leagues = set()
        for match in matches:
            league_id = match.get('league_id')
            logger.info(f"🔍 Mecz {match.get('match_id', '?')}: league_id={league_id}, home={match.get('home_team_name', '?')}, away={match.get('away_team_name', '?')}")
            if league_id:
                try:
                    leagues.add(int(league_id))
                except Exception:
                    pass
        
        logger.info(f"📊 Znaleziono {len(leagues)} lig w meczach: {leagues}")
        
        # Jeśli nie znaleziono lig w meczach, spróbuj pobrać z bazy danych
        if not leagues:
            logger.warning(f"⚠️ Brak lig w meczach, próbuję pobrać z bazy danych dla kolejki {round_id}")
            if hasattr(storage, 'conn'):
                try:
                    # Najpierw sprawdź, czy w ogóle są mecze w tej kolejce
                    all_matches_df = storage.conn.query(
                        f"SELECT match_id, league_id, round_id FROM matches WHERE round_id = '{round_id}'",
                        ttl=0
                    )
                    logger.info(f"🔍 Znaleziono {len(all_matches_df)} meczów w kolejce {round_id} w bazie danych")
                    if not all_matches_df.empty:
                        logger.info(f"📊 Przykładowe mecze z bazy:")
                        for idx, row in all_matches_df.head(5).iterrows():
                            logger.info(f"  - match_id={row.get('match_id')}, league_id={row.get('league_id')}, round_id={row.get('round_id')}")
                    
                    logger.info(f"🔍 Wykonuję zapytanie SQL: SELECT DISTINCT league_id FROM matches WHERE round_id = '{round_id}' AND league_id IS NOT NULL")
                    matches_df = storage.conn.query(
                        f"SELECT DISTINCT league_id FROM matches WHERE round_id = '{round_id}' AND league_id IS NOT NULL",
                        ttl=0
                    )
                    logger.info(f"📊 Zapytanie SQL zwróciło {len(matches_df)} wierszy")
                    if not matches_df.empty:
                        logger.info(f"📊 Kolumny w wynikach: {matches_df.columns.tolist()}")
                        for idx, row in matches_df.iterrows():
                            league_id = row.get('league_id')
                            logger.info(f"🔍 Wiersz {idx}: league_id={league_id} (typ: {type(league_id)})")
                            if league_id:
                                try:
                                    leagues.add(int(league_id))
                                    logger.info(f"✅ Dodano ligę {league_id} do zbioru lig")
                                except Exception as e:
                                    logger.error(f"❌ Błąd konwersji league_id {league_id} na int: {e}")
                        logger.info(f"📊 Pobrano {len(leagues)} lig z bazy danych: {leagues}")
                    else:
                        logger.warning(f"⚠️ Zapytanie SQL nie zwróciło żadnych wyników dla kolejki {round_id}")
                        
                        # Jeśli nie znaleziono lig w meczach, spróbuj pobrać z tabeli teams na podstawie nazw drużyn
                        logger.info(f"🔍 Próbuję pobrać ligi z tabeli teams na podstawie nazw drużyn")
                        try:
                            # Pobierz nazwy drużyn z meczów
                            team_names = set()
                            for match in matches:
                                home_team = match.get('home_team_name', '').strip()
                                away_team = match.get('away_team_name', '').strip()
                                if home_team:
                                    team_names.add(home_team)
                                if away_team:
                                    team_names.add(away_team)
                            
                            if team_names:
                                team_names_str = "', '".join([t.replace("'", "''") for t in team_names])
                                teams_df = storage.conn.query(
                                    f"SELECT DISTINCT league_id FROM teams WHERE team_name IN ('{team_names_str}') AND league_id IS NOT NULL",
                                    ttl=0
                                )
                                logger.info(f"📊 Zapytanie do tabeli teams zwróciło {len(teams_df)} wierszy")
                                if not teams_df.empty:
                                    for _, row in teams_df.iterrows():
                                        league_id = row.get('league_id')
                                        if league_id:
                                            try:
                                                leagues.add(int(league_id))
                                                logger.info(f"✅ Dodano ligę {league_id} z tabeli teams do zbioru lig")
                                            except Exception as e:
                                                logger.error(f"❌ Błąd konwersji league_id {league_id} na int: {e}")
                                    logger.info(f"📊 Pobrano {len(leagues)} lig z tabeli teams: {leagues}")
                        except Exception as e:
                            logger.error(f"❌ Błąd pobierania lig z tabeli teams: {e}", exc_info=True)
                except Exception as e:
                    logger.error(f"❌ Błąd pobierania lig z bazy danych: {e}", exc_info=True)
        
        if not leagues:
            logger.warning(f"❌ Brak lig w kolejce {round_id} - nie można odświeżyć danych z API")
            return
        
        ck, cs, at, ats = _get_oauth_keys()
        if not ck or not cs:
            logger.warning("Brak kluczy OAuth do API")
            return
        
        logger.info(f"✅ Klucze OAuth dostępne, pobieram dane z API dla {len(leagues)} lig")
        
        # Użyj bezpośredniego wywołania API zamiast cache, aby zawsze pobrać najnowsze dane
        from hattrick_oauth_simple import HattrickOAuthSimple
        client = HattrickOAuthSimple(ck, cs)
        client.set_access_tokens(at, ats)
        
        updated_count = 0
        for league_id in leagues:
            try:
                logger.info(f"📡 Pobieram dane z API dla ligi {league_id} (bezpośrednio, bez cache)")
                # Pobierz dane z API dla ligi bezpośrednio, bez cache
                api_league = client.get_league_fixtures(league_id) or {}
                # get_league_fixtures zwraca {'season': ..., 'fixtures': [...]}
                if isinstance(api_league, dict) and 'fixtures' in api_league:
                    api_matches = api_league['fixtures']
                elif isinstance(api_league, dict) and 'matches' in api_league:
                    api_matches = api_league['matches']
                else:
                    api_matches = api_league if isinstance(api_league, list) else []
                
                logger.info(f"📊 Pobrano {len(api_matches)} meczów z API dla ligi {league_id}")
                
                # Stwórz mapę match_id -> match z API
                api_map = {str(m.get('match_id')): m for m in api_matches if m}
                logger.info(f"🔍 Utworzono mapę {len(api_map)} meczów z API dla ligi {league_id}")
                
                # Zaktualizuj mecze z tej kolejki - filtruj po match_id, nie po league_id
                # (ponieważ mecze w liście matches mogą nie mieć league_id)
                matches_in_round = []
                for m in matches:
                    match_id = str(m.get('match_id', ''))
                    if match_id in api_map:
                        matches_in_round.append(m)
                
                logger.info(f"🔍 Sprawdzam {len(matches_in_round)} meczów z kolejki {round_id} w lidze {league_id} (dopasowane po match_id)")
                
                for match in matches_in_round:
                    match_id = str(match.get('match_id', ''))
                    if not match_id:
                        continue
                    
                    api_match = api_map.get(match_id)
                    if not api_match:
                        logger.warning(f"⚠️ Nie znaleziono meczu {match_id} w danych z API dla ligi {league_id}")
                        continue
                    
                    logger.info(f"✅ Znaleziono mecz {match_id} w danych z API")
                    logger.info(f"📋 Pełne dane meczu z API: {api_match}")
                    
                    # Sprawdź flagę is_finished z API
                    finished_flag = None
                    if 'is_finished' in api_match:
                        finished_flag = api_match.get('is_finished')
                        logger.info(f"🔍 Mecz {match_id}: is_finished z API = {finished_flag}")
                    elif 'finished' in api_match:
                        finished_flag = api_match.get('finished')
                        logger.info(f"🔍 Mecz {match_id}: finished z API = {finished_flag}")
                    else:
                        status = str(api_match.get('status', '')).lower()
                        logger.info(f"🔍 Mecz {match_id}: status z API = '{status}'")
                        if status in ('finished', 'played', 'completed', 'ended'):
                            finished_flag = True
                            logger.info(f"✅ Mecz {match_id}: status wskazuje na zakończenie")
                        else:
                            logger.info(f"⚠️ Mecz {match_id}: status NIE wskazuje na zakończenie (status='{status}')")
                    
                    # Pobierz wyniki z API
                    hg = api_match.get('home_goals') or api_match.get('homeGoals')
                    ag = api_match.get('away_goals') or api_match.get('awayGoals')
                    logger.info(f"📊 Mecz {match_id}: wyniki z API = {hg}-{ag}")
                    
                    # Aktualizuj mecz w bazie
                    if hasattr(storage, 'conn'):
                        # WAŻNE: Aktualizuj wyniki TYLKO jeśli są dostępne w API
                        # update_match_result sprawdzi, czy mecz już ma wyniki w bazie i nie nadpisze ich
                        if hg is not None and ag is not None:
                            logger.info(f"📝 Aktualizuję wynik meczu {match_id}: {hg}-{ag} (update_match_result sprawdzi, czy mecz już ma wyniki)")
                            storage.update_match_result(round_id, match_id, safe_int(hg), safe_int(ag))
                            updated_count += 1
                        else:
                            logger.info(f"⚠️ Mecz {match_id} nie ma wyników w API (hg={hg}, ag={ag}) - NIE aktualizuję wyników")
                        
                        # Aktualizuj flagę is_finished - WAŻNE: jeśli API nie potwierdza zakończenia, ustaw is_finished=0
                        if finished_flag is not None:
                            is_finished_value = 1 if bool(finished_flag) else 0
                            logger.info(f"📝 Aktualizuję flagę is_finished dla meczu {match_id}: {is_finished_value} (z API)")
                            storage.conn.query(
                                f"UPDATE matches SET is_finished = {is_finished_value}, api_checked_at = NOW() WHERE match_id = '{match_id}' AND round_id = '{round_id}'",
                                ttl=0
                            )
                            updated_count += 1
                        else:
                            # Jeśli API nie zwraca flagi is_finished, ale status nie wskazuje na zakończenie, ustaw is_finished=0
                            status = str(api_match.get('status', '')).lower()
                            if status not in ('finished', 'played', 'completed', 'ended'):
                                logger.info(f"📝 API nie potwierdza zakończenia meczu {match_id} (status='{status}'), ustawiam is_finished=0")
                                storage.conn.query(
                                    f"UPDATE matches SET is_finished = 0, api_checked_at = NOW() WHERE match_id = '{match_id}' AND round_id = '{round_id}'",
                                    ttl=0
                                )
                                updated_count += 1
                            else:
                                logger.warning(f"⚠️ Mecz {match_id} nie ma flagi is_finished w API, ale status wskazuje na zakończenie")
            except Exception as e:
                logger.error(f"Błąd odświeżania ligi {league_id} z API: {e}")
                continue
        
        # Sprawdź czy wszystkie mecze w kolejce są zakończone i zaktualizuj status rundy
        if hasattr(storage, 'conn'):
            try:
                logger.info(f"🔍 Sprawdzam status rundy {round_id} po aktualizacji")
                matches_status_df = storage.conn.query(
                    f"""
                    SELECT 
                        COUNT(*) as total_matches,
                        SUM(CASE WHEN is_finished = 1 THEN 1 ELSE 0 END) as finished_matches
                    FROM matches 
                    WHERE round_id = '{round_id}'
                    """,
                    ttl=0
                )
                
                if not matches_status_df.empty:
                    total_matches = int(matches_status_df.iloc[0].get('total_matches', 0))
                    finished_matches = int(matches_status_df.iloc[0].get('finished_matches', 0))
                    
                    logger.info(f"📊 Status rundy {round_id}: {finished_matches}/{total_matches} meczów zakończonych")
                    
                    # Jeśli wszystkie mecze są zakończone, ustaw is_finished=1 dla rundy
                    if total_matches > 0 and finished_matches == total_matches:
                        logger.info(f"✅ Wszystkie mecze w kolejce {round_id} są zakończone, aktualizuję status rundy")
                        storage.conn.query(
                            f"UPDATE rounds SET is_finished = 1, is_archival = 1, is_current = 0 WHERE round_id = '{round_id}'",
                            ttl=0
                        )
                    else:
                        logger.info(f"⚠️ Nie wszystkie mecze w kolejce {round_id} są zakończone, nie aktualizuję statusu rundy")
            except Exception as e:
                logger.error(f"Błąd aktualizacji statusu rundy {round_id}: {e}")
        
        # Unieważnij cache
        st.session_state['data_version'] = st.session_state.get('data_version', 0) + 1
        
        logger.info(f"✅ Zakończono odświeżanie kolejki {round_id}: zaktualizowano {updated_count} meczów z API")
    except Exception as e:
        logger.error(f"Błąd refresh_round_from_api: {e}")


def refresh_unfinished_matches_from_api(storage, season_id: str, throttle_seconds: int = 120):
    """Uzupełnia w bazie wyniki tylko dla meczów nieukończonych; ogranicza liczbę zapytań do API.
    - pyta API tylko dla lig, w których są nieukończone mecze
    - aktualizuje tylko mecze, które mają już wynik w API
    """
    import time
    try:
        last_sync = st.session_state.get('last_api_sync_ts', 0)
        if last_sync and (time.time() - last_sync) < throttle_seconds:
            return

        # Znajdź nieukończone mecze w bieżącym sezonie
        unfinished_df = storage.conn.query(
            f"""
            SELECT m.match_id, m.round_id, m.league_id
            FROM matches m
            INNER JOIN rounds r ON r.round_id = m.round_id
            WHERE r.season_id = '{season_id}'
              AND (m.is_finished = 0 OR m.home_goals IS NULL OR m.away_goals IS NULL)
            """,
            ttl=0
        ) if hasattr(storage, 'conn') else None

        if unfinished_df is None or unfinished_df.empty:
            st.session_state['last_api_sync_ts'] = time.time()
            return

        # Grupuj po lidze, aby ograniczyć liczbę zapytań do API
        leagues = sorted(set(int(row['league_id']) for _, row in unfinished_df.iterrows() if row.get('league_id') is not None))
        if not leagues:
            st.session_state['last_api_sync_ts'] = time.time()
            return

        ck, cs, at, ats = _get_oauth_keys()
        if not ck or not cs:
            # Brak kluczy do API – nie odświeżamy (ale aplikacja działa na danych z bazy)
            st.session_state['last_api_sync_ts'] = time.time()
            return

        for league_id in leagues:
            try:
                api_league = cached_get_league_fixtures(league_id, ck, cs, at, ats) or {}
                # Wyciągnij listę meczów
                if isinstance(api_league, dict) and 'matches' in api_league:
                    api_matches = api_league['matches']
                else:
                    api_matches = api_league if isinstance(api_league, list) else []

                api_map = {str(m.get('match_id')): m for m in api_matches if m}
                league_rows = unfinished_df[unfinished_df['league_id'] == league_id]

                updated_any = False
                for _, row in league_rows.iterrows():
                    mid = str(row['match_id'])
                    rid = str(row['round_id'])
                    api_m = api_map.get(mid)
                    if not api_m:
                        continue
                    finished_flag = None
                    if 'is_finished' in api_m:
                        finished_flag = api_m.get('is_finished')
                    elif 'finished' in api_m:
                        finished_flag = api_m.get('finished')
                    else:
                        st_str = str(api_m.get('status', '')).lower()
                        if st_str in ('finished', 'played', 'completed'):
                            finished_flag = True
                    hg = api_m.get('home_goals')
                    ag = api_m.get('away_goals')

                    # Aktualizuj wynik jeśli mamy bramki; w każdym przypadku, gdy API mówi 'finished', ustaw flagę is_finished=1
                    try:
                        if hg is not None and ag is not None:
                            storage.update_match_result(rid, mid, safe_int(hg), safe_int(ag))
                            updated_any = True
                        if finished_flag is not None:
                            if hasattr(storage, 'conn'):
                                storage.conn.query(
                                    f"UPDATE matches SET api_checked_at = NOW(), is_finished = {1 if bool(finished_flag) else 0} WHERE match_id = '{mid}' AND round_id = '{rid}'",
                                    ttl=0
                                )
                            updated_any = True
                    except Exception as e:
                        logger.error(f"Błąd aktualizacji meczu {mid}: {e}")

                if updated_any:
                    # Unieważnij cache rankingów/typów
                    st.session_state['data_version'] = st.session_state.get('data_version', 0) + 1
            except Exception as e:
                logger.error(f"Błąd odświeżania z API dla ligi {league_id}: {e}")
                continue

        st.session_state['last_api_sync_ts'] = time.time()
    except Exception as e:
        logger.error(f"Błąd refresh_unfinished_matches_from_api: {e}")
        st.session_state['last_api_sync_ts'] = time.time()

def main():
    """Główna funkcja aplikacji typera"""
    # Sprawdź autentykację
    if not check_authentication():
        login_page()
        return
    
    # Pobierz nazwę użytkownika z sesji
    username = st.session_state.get('username', 'Użytkownik')
    
    st.title("🎯 Hattrick Typer")
    
    # Inicjalizacja storage (potrzebne do pobrania sezonów)
    # Użyj współdzielonej instancji storage z session_state, aby uniknąć wielokrotnych połączeń MySQL
    if 'shared_storage' not in st.session_state:
        try:
            st.session_state.shared_storage = get_storage()
        except Exception as e:
            logger.error(f"Błąd inicjalizacji storage: {e}")
            st.error(f"❌ Błąd inicjalizacji storage: {e}")
            return
    
    storage = st.session_state.shared_storage
    
    # Sprawdź czy storage ma wymagane metody
    if not hasattr(storage, 'get_current_season'):
        logger.error(f"Storage nie ma metody get_current_season. Typ: {type(storage)}")
        st.error("❌ Błąd: Storage nie ma wymaganej metody get_current_season")
        return
    
    # Filtr sezonu - na górze pod tytułem
    st.markdown("---")
    st.subheader("📅 Filtr sezonu")
    
    # Pobierz wszystkie dostępne sezony
    # Użyj try-except, aby obsłużyć błędy ładowania danych
    try:
        all_seasons = storage.data.get('seasons', {})
    except Exception as e:
        logger.error(f"Błąd pobierania sezonów z storage: {e}")
        # Jeśli błąd, spróbuj przeładować dane
        if hasattr(storage, 'reload_data'):
            storage.reload_data()
        try:
            all_seasons = storage.data.get('seasons', {})
        except Exception as e2:
            logger.error(f"Błąd ponownego pobierania sezonów: {e2}")
            all_seasons = {}
    
    season_options = []
    season_ids = []
    
    # Przygotuj listę sezonów do wyboru (posortowane: najnowszy pierwszy)
    # Filtruj sezony - pomiń "current_season" i inne nieprawidłowe wartości
    seasons_list = []
    for season_id, season_data in all_seasons.items():
        # Wyciągnij numer sezonu z season_id (np. "season_80" -> "80")
        season_number = season_id.replace('season_', '') if season_id.startswith('season_') else season_id
        
        # Pomiń sezony z "current_season" lub innymi nieprawidłowymi wartościami
        if season_number == "current_season" or not season_number or season_number == "":
            continue
        
        try:
            # Spróbuj przekonwertować na liczbę dla sortowania
            season_num = int(season_number)
        except ValueError:
            # Jeśli nie można przekonwertować, pomiń ten sezon
            continue
        seasons_list.append((season_num, season_id, season_number))
    
    # Sortuj sezony: najnowszy pierwszy (malejąco)
    seasons_list.sort(key=lambda x: x[0], reverse=True)
    
    for season_num, season_id, season_number in seasons_list:
        season_display = f"Sezon {season_number}"
        season_options.append(season_display)
        season_ids.append(season_id)
    
    # Jeśli nie ma sezonów, dodaj domyślny
    if not season_options:
        # Najpierw sprawdź czy mamy zapisany sezon w session_state (fallback)
        saved_season_id = st.session_state.get('selected_season_id', None)
        
        # Pobierz aktualny sezon z storage lub użyj domyślnego
        try:
            current_season_id = storage.get_current_season()
        except Exception as e:
            logger.error(f"Błąd pobierania aktualnego sezonu: {e}")
            current_season_id = None
        
        # Użyj zapisanego sezonu z session_state jako fallback, jeśli aktualny sezon nie jest dostępny
        if not current_season_id and saved_season_id:
            current_season_id = saved_season_id
            logger.info(f"DEBUG: Używam zapisanego sezonu z session_state jako fallback: {saved_season_id}")
        
        if current_season_id:
            season_number = current_season_id.replace('season_', '') if current_season_id.startswith('season_') else current_season_id
            # Pomiń sezony z "current_season" lub innymi nieprawidłowymi wartościami
            if season_number != "current_season" and season_number and season_number != "":
                try:
                    # Sprawdź czy to liczba
                    int(season_number)
                    season_options.append(f"Sezon {season_number}")
                    season_ids.append(current_season_id)
                except ValueError:
                    # Nieprawidłowy format sezonu
                    season_options.append("Brak sezonów")
                    season_ids.append(None)
            else:
                season_options.append("Brak sezonów")
                season_ids.append(None)
        else:
            season_options.append("Brak sezonów")
            season_ids.append(None)
    
    # Selectbox do wyboru sezonu
    if season_options:
        # Znajdź indeks aktualnego sezonu
        try:
            current_season_id = storage.get_current_season()
        except Exception as e:
            logger.error(f"Błąd pobierania aktualnego sezonu: {e}")
            current_season_id = None
        default_index = 0
        if current_season_id and current_season_id in season_ids:
            default_index = season_ids.index(current_season_id)
        elif current_season_id:
            # Jeśli aktualny sezon nie jest na liście, dodaj go (tylko jeśli to prawidłowy sezon)
            season_number = current_season_id.replace('season_', '') if current_season_id.startswith('season_') else current_season_id
            # Pomiń sezony z "current_season" lub innymi nieprawidłowymi wartościami
            if season_number != "current_season" and season_number and season_number != "":
                try:
                    # Sprawdź czy to liczba
                    int(season_number)
                    season_options.insert(0, f"Sezon {season_number}")
                    season_ids.insert(0, current_season_id)
                    default_index = 0
                except ValueError:
                    # Nieprawidłowy format sezonu - nie dodawaj
                    pass
        
        # Sprawdź czy użytkownik wybrał sezon wcześniej
        if 'selected_season_id' in st.session_state and st.session_state.selected_season_id in season_ids:
            default_index = season_ids.index(st.session_state.selected_season_id)
        
        selected_season_display = st.selectbox(
            "Wybierz sezon:",
            options=range(len(season_options)),
            index=default_index,
            format_func=lambda x: season_options[x],
            key="season_filter"
        )
        
        selected_season_id = season_ids[selected_season_display]
        
        # Zapisz wybrany sezon w session_state
        st.session_state.selected_season_id = selected_season_id
        
        # NIE ustawiaj wybranego sezonu jako aktualnego w storage - pozwól użytkownikowi przeglądać archiwalne sezony
        # Aktualny sezon w storage jest ustawiany tylko automatycznie (gdy sezon się zmienia z API)
        # Użytkownik może wybrać archiwalny sezon do przeglądania, ale to nie zmienia aktualnego sezonu
    else:
        selected_season_id = None
        st.warning("⚠️ Brak sezonów w bazie. Sezon zostanie utworzony po pobraniu meczów z API.")
    
    st.markdown("---")
    
    # Sidebar z konfiguracją
    with st.sidebar:
        # Sekcja użytkownika
        st.header("👤 Użytkownik")
        st.info(f"Zalogowany jako: **{username}**")
        if st.button("🚪 Wyloguj się", width="stretch"):
            logout()
            return
        
        st.markdown("---")
        
        # Sekcja logów (debug)
        with st.expander("🔍 Logi aplikacji", expanded=False):
            if st.button("🔄 Odśwież logi", width="stretch"):
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
                # Użyj współdzielonej instancji storage (nie tworz nowej!)
                storage = st.session_state.get('shared_storage', storage)
                logger.info(f"DEBUG: Storage type: {type(storage).__name__}")
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
        
        # Pobierz wybrany sezon
        selected_season_id = st.session_state.get('selected_season_id', None)
        if not selected_season_id:
            st.warning("⚠️ Wybierz sezon, aby zarządzać ligami i zespołami.")
            return
        
        # Wydzielone okno do zarządzania ligami i zespołami
        with st.expander("🏆 Zarządzanie ligami i zespołami", expanded=True):
            st.markdown(f"**Sezon:** {selected_season_id}")
            st.markdown("---")
            
            # Sekcja zarządzania ligami
            st.subheader("📋 Ligi")
            
            # Pobierz aktualne ligi dla wybranego sezonu (lista ID)
            if hasattr(storage, 'get_season_leagues'):
                selected_league_ids = storage.get_season_leagues(selected_season_id)
            else:
                # Fallback do globalnych lig (dla kompatybilności wstecznej)
                selected_league_ids = storage.get_selected_leagues()
            
            # Pobierz nazwy lig: najpierw z bazy per sezon, brakujące z API
            league_names_map = {}  # {league_id: league_name}
            
            if selected_league_ids:
                # Najpierw spróbuj z bazy per sezon (bez API)
                try:
                    if hasattr(storage, 'get_season_league_names'):
                        db_names = storage.get_season_league_names(selected_season_id)
                        if db_names:
                            league_names_map.update(db_names)
                    elif hasattr(storage, 'get_league_names'):
                        # Fallback do globalnych lig (dla kompatybilności wstecznej)
                        db_names = storage.get_league_names(selected_league_ids)
                        if db_names:
                            league_names_map.update(db_names)
                except Exception as e:
                    logger.warning(f"Nie udało się pobrać nazw lig z bazy: {e}")

                # Sprawdź czy mamy klucze OAuth
                consumer_key = None
                consumer_secret = None
                access_token = None
                access_token_secret = None
                
                try:
                    if hasattr(st, 'secrets'):
                        consumer_key = getattr(st.secrets, 'HATTRICK_CONSUMER_KEY', None)
                        consumer_secret = getattr(st.secrets, 'HATTRICK_CONSUMER_SECRET', None)
                        access_token = getattr(st.secrets, 'HATTRICK_ACCESS_TOKEN', None)
                        access_token_secret = getattr(st.secrets, 'HATTRICK_ACCESS_TOKEN_SECRET', None)
                except:
                    pass
                
                if not all([consumer_key, consumer_secret, access_token, access_token_secret]):
                    load_dotenv()
                    consumer_key = consumer_key or os.getenv('HATTRICK_CONSUMER_KEY')
                    consumer_secret = consumer_secret or os.getenv('HATTRICK_CONSUMER_SECRET')
                    access_token = access_token or os.getenv('HATTRICK_ACCESS_TOKEN')
                    access_token_secret = access_token_secret or os.getenv('HATTRICK_ACCESS_TOKEN_SECRET')
                
                # Pobierz nazwy lig z API tylko dla brakujących ID
                missing_ids = [lid for lid in selected_league_ids if lid not in league_names_map]
                if missing_ids and all([consumer_key, consumer_secret, access_token, access_token_secret]):
                    try:
                        client = HattrickOAuthSimple(consumer_key, consumer_secret)
                        client.set_access_tokens(access_token, access_token_secret)
                        
                        for league_id in missing_ids:
                            try:
                                league_details = client.get_league_details(league_id)
                                if league_details and league_details.get('league_name'):
                                    league_names_map[league_id] = league_details['league_name']
                                    # Zapisz do bazy, by nie pytać API ponownie
                                    try:
                                        storage.add_league(league_id, league_details['league_name'])
                                    except Exception:
                                        pass
                                else:
                                    league_names_map[league_id] = f"Liga {league_id}"
                            except Exception as e:
                                logger.error(f"Błąd pobierania nazwy ligi {league_id} z API: {e}")
                                league_names_map[league_id] = f"Liga {league_id}"
                    except Exception as e:
                        logger.error(f"Błąd inicjalizacji klienta OAuth: {e}")
                        # Użyj domyślnych nazw
                        for league_id in missing_ids:
                            league_names_map[league_id] = f"Liga {league_id}"
                else:
                    # Użyj domyślnych nazw jeśli brak OAuth
                    for league_id in missing_ids:
                        league_names_map[league_id] = f"Liga {league_id}"
                
                # Zapisz w session_state dla użycia w dalszej części aplikacji
                st.session_state.league_names_map = league_names_map
            
            # Wyświetl listę lig z możliwością usunięcia
            if selected_league_ids:
                st.markdown("**Aktualne ligi:**")
                for idx, league_id in enumerate(selected_league_ids, 1):
                    league_name = league_names_map.get(league_id, f"Liga {league_id}")
                    col1, col2 = st.columns([3, 1])
                    with col1:
                        st.write(f"🏆 **{league_name}** (ID: {league_id})")
                    with col2:
                        if st.button("🗑️ Usuń", key=f"delete_league_{league_id}"):
                            try:
                                if hasattr(storage, 'remove_season_league'):
                                    storage.remove_season_league(selected_season_id, league_id)
                                else:
                                    # Fallback do globalnych lig (dla kompatybilności wstecznej)
                                    selected_league_ids.remove(league_id)
                                    storage.set_selected_leagues(selected_league_ids)
                                st.success(f"✅ Usunięto ligę {league_name} z sezonu {selected_season_id}")
                                st.rerun()
                            except Exception as e:
                                st.error(f"❌ Błąd usuwania ligi: {e}")
            else:
                st.info("📊 Brak lig. Dodaj nową ligę.")
            
            # Dodawanie nowej ligi
            st.markdown("---")
            st.markdown("**➕ Dodaj nową ligę:**")
            new_league_id = st.number_input(
                "ID ligi (LeagueLevelUnitID):",
            value=32612,
            min_value=1,
                key="new_league_id",
                help="Wprowadź ID ligi do dodania"
            )
            
            # Sprawdź czy jest pobrana nazwa z API (z poprzedniego przebiegu)
            fetched_league_name = st.session_state.get('fetched_league_name', '')
            if fetched_league_name:
                # Wyczyść po użyciu
                del st.session_state['fetched_league_name']
            
            # Przycisk do pobrania nazwy z API
            col_fetch, col_name = st.columns([1, 3])
            with col_fetch:
                fetch_name_clicked = st.button("🔍 Pobierz nazwę z API", key="fetch_league_name", width="stretch")
            
            with col_name:
                # Użyj pobranej nazwy jako wartości domyślnej, jeśli jest dostępna
                default_name = fetched_league_name if fetched_league_name else ""
                new_league_name = st.text_input(
                    "Nazwa ligi:",
                    value=default_name,
                    key="new_league_name",
                    help="Nazwa ligi (można pobrać z API lub wprowadzić ręcznie)",
                    placeholder="Nazwa ligi (pobierz z API lub wprowadź ręcznie)"
                )
            
            # Pobierz nazwę z API jeśli kliknięto przycisk
            if fetch_name_clicked:
                try:
                    # Sprawdź czy mamy klucze OAuth
                    consumer_key = None
                    consumer_secret = None
                    access_token = None
                    access_token_secret = None
                    
                    try:
                        if hasattr(st, 'secrets'):
                            consumer_key = getattr(st.secrets, 'HATTRICK_CONSUMER_KEY', None)
                            consumer_secret = getattr(st.secrets, 'HATTRICK_CONSUMER_SECRET', None)
                            access_token = getattr(st.secrets, 'HATTRICK_ACCESS_TOKEN', None)
                            access_token_secret = getattr(st.secrets, 'HATTRICK_ACCESS_TOKEN_SECRET', None)
                    except:
                        pass
                    
                    if not all([consumer_key, consumer_secret, access_token, access_token_secret]):
                        load_dotenv()
                        consumer_key = consumer_key or os.getenv('HATTRICK_CONSUMER_KEY')
                        consumer_secret = consumer_secret or os.getenv('HATTRICK_CONSUMER_SECRET')
                        access_token = access_token or os.getenv('HATTRICK_ACCESS_TOKEN')
                        access_token_secret = access_token_secret or os.getenv('HATTRICK_ACCESS_TOKEN_SECRET')
                    
                    if all([consumer_key, consumer_secret, access_token, access_token_secret]):
                        with st.spinner("Pobieranie nazwy ligi z API..."):
                            client = HattrickOAuthSimple(consumer_key, consumer_secret)
                            client.set_access_tokens(access_token, access_token_secret)
                            league_details = client.get_league_details(new_league_id)
                            
                            if league_details and league_details.get('league_name'):
                                # Zapisz pobraną nazwę w session_state dla następnego przebiegu
                                st.session_state.fetched_league_name = league_details['league_name']
                                st.success(f"✅ Pobrano nazwę: {league_details['league_name']}")
                                st.rerun()
                            else:
                                st.warning("⚠️ Nie udało się pobrać nazwy ligi z API")
                    else:
                        st.warning("⚠️ Brak kluczy OAuth. Skonfiguruj OAuth aby pobrać nazwę z API.")
                except Exception as e:
                    logger.error(f"Błąd pobierania nazwy ligi z API: {e}")
                    st.error(f"❌ Błąd pobierania nazwy ligi z API: {str(e)}")
            
            col_add1, col_add2 = st.columns([1, 1])
            with col_add1:
                if st.button("➕ Dodaj ligę", type="primary", key="add_league_btn", width="stretch"):
                    if new_league_id not in selected_league_ids:
                        # Pobierz nazwę z API jeśli nie podano ręcznie
                        final_league_name = new_league_name
                        
                        if not final_league_name:
                            try:
                                # Sprawdź czy mamy klucze OAuth
                                consumer_key = None
                                consumer_secret = None
                                access_token = None
                                access_token_secret = None
                                
                                try:
                                    if hasattr(st, 'secrets'):
                                        consumer_key = getattr(st.secrets, 'HATTRICK_CONSUMER_KEY', None)
                                        consumer_secret = getattr(st.secrets, 'HATTRICK_CONSUMER_SECRET', None)
                                        access_token = getattr(st.secrets, 'HATTRICK_ACCESS_TOKEN', None)
                                        access_token_secret = getattr(st.secrets, 'HATTRICK_ACCESS_TOKEN_SECRET', None)
                                except:
                                    pass
                                
                                if not all([consumer_key, consumer_secret, access_token, access_token_secret]):
                                    load_dotenv()
                                    consumer_key = consumer_key or os.getenv('HATTRICK_CONSUMER_KEY')
                                    consumer_secret = consumer_secret or os.getenv('HATTRICK_CONSUMER_SECRET')
                                    access_token = access_token or os.getenv('HATTRICK_ACCESS_TOKEN')
                                    access_token_secret = access_token_secret or os.getenv('HATTRICK_ACCESS_TOKEN_SECRET')
                                
                                if all([consumer_key, consumer_secret, access_token, access_token_secret]):
                                    with st.spinner("Pobieranie nazwy ligi z API..."):
                                        client = HattrickOAuthSimple(consumer_key, consumer_secret)
                                        client.set_access_tokens(access_token, access_token_secret)
                                        league_details = client.get_league_details(new_league_id)
                                        
                                        if league_details and league_details.get('league_name'):
                                            final_league_name = league_details['league_name']
                                        else:
                                            final_league_name = f"Liga {new_league_id}"
                                else:
                                    final_league_name = f"Liga {new_league_id}"
                            except Exception as e:
                                logger.error(f"Błąd pobierania nazwy ligi z API: {e}")
                                final_league_name = f"Liga {new_league_id}"
                        
                        # Dodaj ligę do sezonu
                        try:
                            if hasattr(storage, 'add_season_league'):
                                storage.add_season_league(selected_season_id, new_league_id, final_league_name)
                                
                                # Po dodaniu ligi, automatycznie pobierz zespoły z API i zapisz dla sezonu
                                if all([consumer_key, consumer_secret, access_token, access_token_secret]):
                                    with st.spinner(f"Pobieranie zespołów z ligi {final_league_name}..."):
                                        try:
                                            client = HattrickOAuthSimple(consumer_key, consumer_secret)
                                            client.set_access_tokens(access_token, access_token_secret)
                                            
                                            # Pobierz zespoły bezpośrednio z tabeli ligowej (zamiast z meczów)
                                            league_teams = client.get_league_table(new_league_id)
                                            teams_to_add = []
                                            
                                            if league_teams and isinstance(league_teams, list):
                                                # Zbierz zespoły z tabeli ligowej
                                                for team_data in league_teams:
                                                    team_name = team_data.get('team_name', '').strip()
                                                    if team_name:
                                                        teams_to_add.append({
                                                            'team_name': team_name,
                                                            'league_id': new_league_id,
                                                            'league_name': final_league_name,
                                                            'is_selected': False  # Domyślnie nie wybrane
                                                        })
                                            
                                            # Dodaj zespoły do sezonu
                                            if teams_to_add and hasattr(storage, 'bulk_add_season_teams'):
                                                storage.bulk_add_season_teams(selected_season_id, teams_to_add)
                                                st.success(f"✅ Dodano ligę: {final_league_name} (ID: {new_league_id}) i {len(teams_to_add)} zespołów")
                                            else:
                                                st.success(f"✅ Dodano ligę: {final_league_name} (ID: {new_league_id})")
                                                if not teams_to_add:
                                                    st.warning(f"⚠️ Nie znaleziono zespołów w tabeli ligowej dla ligi {new_league_id}")
                                        except Exception as e:
                                            logger.error(f"Błąd pobierania zespołów z ligi {new_league_id}: {e}")
                                            st.success(f"✅ Dodano ligę: {final_league_name} (ID: {new_league_id})")
                                            st.warning(f"⚠️ Nie udało się pobrać zespołów z API: {e}")
                                else:
                                    st.success(f"✅ Dodano ligę: {final_league_name} (ID: {new_league_id})")
                                    st.info("ℹ️ Skonfiguruj OAuth aby automatycznie pobrać zespoły z API")
                            else:
                                # Fallback do globalnych lig (dla kompatybilności wstecznej)
                                selected_league_ids.append(new_league_id)
                                storage.set_selected_leagues(selected_league_ids)
                                st.success(f"✅ Dodano ligę: {final_league_name} (ID: {new_league_id})")
                            st.rerun()
                        except Exception as e:
                            logger.error(f"Błąd dodawania ligi: {e}")
                            st.error(f"❌ Błąd dodawania ligi: {e}")
                else:
                    st.warning(f"⚠️ Liga o ID {new_league_id} już istnieje")
        
            with col_add2:
                if st.button("🔄 Odśwież dane", key="refresh_data_btn", width="stretch"):
                    st.cache_data.clear()
                    st.rerun()
        
            # Sekcja zarządzania zespołami
            st.markdown("---")
            st.subheader("👥 Zespoły")
            
            # Pobierz zespoły dla wybranego sezonu
            if hasattr(storage, 'get_season_teams'):
                season_teams = storage.get_season_teams(selected_season_id, only_selected=False)
                
                if season_teams:
                    # Grupuj zespoły według lig
                    teams_by_league = {}
                    teams_without_league = []
                    for team in season_teams:
                        league_id = team.get('league_id')
                        league_name = team.get('league_name') or f"Liga {league_id}" if league_id else "?"
                        if league_id is None or league_id == 0:
                            # Zespoły bez ligi - dodaj do osobnej grupy
                            teams_without_league.append(team)
                        else:
                            if league_id not in teams_by_league:
                                teams_by_league[league_id] = {
                                    'league_name': league_name,
                                    'teams': []
                                }
                            teams_by_league[league_id]['teams'].append(team)
                    
                    # Wyświetl zespoły pogrupowane według lig
                    for league_id, league_data in sorted(teams_by_league.items()):
                        league_name = league_data['league_name']
                        teams = league_data['teams']
                        
                        with st.expander(f"🏆 {league_name} ({len(teams)} zespołów)", expanded=True):
                            # Formularz do zaznaczania zespołów
                            with st.form(f"team_selection_form_{league_id}", clear_on_submit=False):
                                selected_teams_for_league = []
                                
                                for team in sorted(teams, key=lambda x: x['team_name']):
                                    team_name = team['team_name']
                                    is_selected = team.get('is_selected', False)
                                    checkbox_key = f"team_select_{selected_season_id}_{league_id}_{team_name}"
                                    
                                    # Inicjalizuj wartość checkboxa jeśli nie istnieje w session_state
                                    if checkbox_key not in st.session_state:
                                        st.session_state[checkbox_key] = is_selected
                                    
                                    if st.checkbox(team_name, key=checkbox_key, value=st.session_state[checkbox_key]):
                                        selected_teams_for_league.append(team_name)
                                
                                # Przycisk zapisu
                                if st.form_submit_button(f"💾 Zapisz wybór dla {league_name}", type="primary", width="stretch"):
                                    try:
                                        # Ustaw wybór dla każdego zespołu w lidze
                                        for team in teams:
                                            team_name = team['team_name']
                                            is_selected = team_name in selected_teams_for_league
                                            storage.set_season_team_selected(selected_season_id, team_name, is_selected)
                                        st.success(f"✅ Zapisano wybór dla {league_name}: {len(selected_teams_for_league)}/{len(teams)} zespołów")
                                        st.rerun()
                                    except Exception as e:
                                        logger.error(f"Błąd zapisywania wyboru zespołów: {e}")
                                        st.error(f"❌ Błąd zapisywania wyboru zespołów: {e}")
                    
                    # Wyświetl zespoły bez ligi (jeśli są)
                    if teams_without_league:
                        with st.expander(f"❓ Zespoły bez przypisanej ligi ({len(teams_without_league)} zespołów)", expanded=True):
                            st.warning("⚠️ Te zespoły nie mają przypisanej ligi. Dodaj ligi w sekcji '📋 Ligi' i pobierz zespoły z API, aby przypisać ligi.")
                            # Formularz do zaznaczania zespołów bez ligi
                            with st.form(f"team_selection_form_no_league", clear_on_submit=False):
                                selected_teams_no_league = []
                                
                                for team in sorted(teams_without_league, key=lambda x: x['team_name']):
                                    team_name = team['team_name']
                                    is_selected = team.get('is_selected', False)
                                    checkbox_key = f"team_select_{selected_season_id}_no_league_{team_name}"
                                    
                                    # Inicjalizuj wartość checkboxa jeśli nie istnieje w session_state
                                    if checkbox_key not in st.session_state:
                                        st.session_state[checkbox_key] = is_selected
                                    
                                    if st.checkbox(team_name, key=checkbox_key, value=st.session_state[checkbox_key]):
                                        selected_teams_no_league.append(team_name)
                                
                                # Przycisk zapisu
                                if st.form_submit_button(f"💾 Zapisz wybór dla zespołów bez ligi", type="primary", width="stretch"):
                                    try:
                                        # Ustaw wybór dla każdego zespołu bez ligi
                                        for team in teams_without_league:
                                            team_name = team['team_name']
                                            is_selected = team_name in selected_teams_no_league
                                            storage.set_season_team_selected(selected_season_id, team_name, is_selected)
                                        st.success(f"✅ Zapisano wybór dla zespołów bez ligi: {len(selected_teams_no_league)}/{len(teams_without_league)} zespołów")
                                        st.rerun()
                                    except Exception as e:
                                        logger.error(f"Błąd zapisywania wyboru zespołów: {e}")
                                        st.error(f"❌ Błąd zapisywania wyboru zespołów: {e}")
                else:
                    st.info("📊 Brak zespołów dla tego sezonu. Dodaj ligi, aby automatycznie pobrać zespoły z API.")
            else:
                st.warning("⚠️ Funkcja zarządzania zespołami per sezon nie jest dostępna.")
            
            # Użyj wybranych lig (lista ID dla API)
            TIPPER_LEAGUES = selected_league_ids
            
        # Informacje
            if TIPPER_LEAGUES:
                league_names = [league_names_map.get(league_id, f"Liga {league_id}") for league_id in TIPPER_LEAGUES]
                st.info(f"**Aktywne ligi ({len(TIPPER_LEAGUES)}):** {', '.join(league_names)}")
            else:
                st.warning("⚠️ Brak aktywnych lig. Dodaj ligi aby pobrać mecze.")
        
        st.markdown("---")
        st.subheader("💾 Import/Eksport danych")
        
        # Eksport danych
        if st.button("📥 Pobierz backup danych", width="stretch", help="Pobierz aktualny plik tipper_data.json"):
            import json
            data_str = json.dumps(storage.data, ensure_ascii=False, indent=2)
            st.download_button(
                label="⬇️ Pobierz plik JSON",
                data=data_str,
                file_name="tipper_data.json",
                mime="application/json",
                width="stretch"
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
                        if st.button("💾 Zaimportuj dane", type="primary", width="stretch"):
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
        
        # league_names_map: najpierw DB, brakujące z API
        if 'league_names_map' not in st.session_state or not st.session_state.get('league_names_map'):
            league_names_map = {}
            # DB-first
            try:
                if hasattr(storage, 'get_league_names'):
                    db_names = storage.get_league_names(TIPPER_LEAGUES)
                    if db_names:
                        league_names_map.update(db_names)
            except Exception:
                pass
            # API for missing
            missing_ids = [lid for lid in TIPPER_LEAGUES if lid not in league_names_map]
            for league_id in missing_ids:
                try:
                    league_details = client.get_league_details(league_id)
                    if league_details and league_details.get('league_name'):
                        league_names_map[league_id] = league_details['league_name']
                        try:
                            storage.add_league(league_id, league_details['league_name'])
                        except Exception:
                            pass
                    else:
                        league_names_map[league_id] = f"Liga {league_id}"
                except Exception as e:
                    logger.error(f"Błąd pobierania nazwy ligi {league_id} z API: {e}")
                    league_names_map[league_id] = f"Liga {league_id}"
            st.session_state.league_names_map = league_names_map
        else:
            league_names_map = st.session_state.league_names_map
        
        # Pobierz mecze z obu lig wraz z informacją o sezonie – najpierw DB-first, potem ewentualnie API
        all_fixtures = []
        current_season = None
        skip_api = False

        # 0) DB-first: jeśli mamy MySQL i w bazie są już mecze dla wybranego sezonu – użyj ich (bez API)
        try:
            if hasattr(storage, 'conn'):
                # Ustal sezon z filtra jeśli dostępny
                selected_season_id = st.session_state.get("selected_season_id")
                if not selected_season_id:
                    # Spróbuj z storage
                    selected_season_id = storage.get_current_season()

                if selected_season_id:
                    db_df = storage.conn.query(
                        f"""
                        SELECT m.match_id, m.round_id, m.home_team_name, m.away_team_name,
                               m.match_date, m.home_goals, m.away_goals, m.league_id, m.is_finished,
                               r.season_id
                        FROM matches m
                        INNER JOIN rounds r ON r.round_id = m.round_id
                        WHERE r.season_id = '{selected_season_id}'
                        ORDER BY m.match_date ASC
                        """,
                        ttl=0
                    )
                    if not db_df.empty:
                        for _, row in db_df.iterrows():
                            match_dict = {
                                'match_id': str(row['match_id']),
                                'round_id': row['round_id'],
                                'home_team_name': row['home_team_name'],
                                'away_team_name': row['away_team_name'],
                                'match_date': row['match_date'],
                                'home_goals': row.get('home_goals'),
                                'away_goals': row.get('away_goals'),
                                'league_id': row.get('league_id'),
                                'season': str(row.get('season_id')).replace('season_', '') if row.get('season_id') else None,
                                'is_finished': row.get('is_finished', 0),  # WAŻNE: Dodaj flagę is_finished z bazy
                            }
                            all_fixtures.append(match_dict)
                        # Wyciągnij numer sezonu z season_id
                        if selected_season_id and str(selected_season_id).startswith('season_'):
                            try:
                                current_season = int(str(selected_season_id).replace('season_', ''))
                            except Exception:
                                current_season = None
                        skip_api = True
                        st.session_state["all_fixtures_cache"] = all_fixtures
                        if current_season is not None:
                            st.session_state["fixtures_season"] = current_season
                        logger.info("DEBUG: Używam fixtures z DB (DB-first) dla wybranego sezonu")
        except Exception as e:
            logger.warning(f"DB-first fixtures warning: {e}")

        # 1) Cache sesji – jeśli mamy i pasuje do wybranego sezonu, użyj zamiast API
        # Spróbuj użyć cache sesji (nie wołaj API przy każdym rerunie)
        cached_fixtures = st.session_state.get("all_fixtures_cache")
        cached_season = st.session_state.get("fixtures_season")
        selected_season_from_filter = st.session_state.get("selected_season_id")
        selected_season_num = None
        if selected_season_from_filter and str(selected_season_from_filter).startswith("season_"):
            try:
                selected_season_num = int(str(selected_season_from_filter).replace("season_", ""))
            except Exception:
                selected_season_num = None
        
        if not skip_api and cached_fixtures and cached_season and (selected_season_num is None or cached_season == selected_season_num):
            # Użyj danych z cache sesji
            all_fixtures = cached_fixtures
            current_season = cached_season
            logger.info("DEBUG: Używam fixtures z cache sesji (bez odpytywania API)")
        elif not skip_api:
            # Brak w cache – jednorazowo pobierz z API i zapisz do cache sesji
            with st.spinner("Pobieranie meczów z lig..."):
                for league_id in TIPPER_LEAGUES:
                    try:
                        league_data = cached_get_league_fixtures(league_id, consumer_key, consumer_secret, access_token, access_token_secret)
                        fixtures = []
                        season = None
                        if league_data and 'fixtures' in league_data:
                            fixtures = league_data['fixtures']
                            season = league_data.get('season')
                        
                        # Zapisz sezon (użyj pierwszego znalezionego sezonu)
                        if season and current_season is None:
                            current_season = season
                        
                        if fixtures:
                            # Dodaj informację o lidze i sezonie
                            for fixture in fixtures:
                                fixture['league_id'] = league_id
                                if season:
                                    fixture['season'] = season
                            all_fixtures.extend(fixtures)
                            logger.info(f"Pobrano {len(fixtures)} meczów z ligi {league_id}, sezon: {season}")
                    except Exception as e:
                        logger.error(f"Błąd pobierania meczów z ligi {league_id}: {e}")
                        st.warning(f"⚠️ Nie udało się pobrać meczów z ligi {league_id}: {e}")
            # Zapisz jednorazowo w cache sesji (by nie pytać API przy następnym rerunie)
            if all_fixtures and current_season is not None:
                st.session_state["all_fixtures_cache"] = all_fixtures
                st.session_state["fixtures_season"] = current_season
        
        if not all_fixtures:
            st.error("❌ Nie udało się pobrać meczów z API")
            return
        
        # Zapisz/uzupełnij rundy i mecze w bazie (persistuj wyniki, aby nie pobierać ich za każdym razem)
        try:
            from collections import defaultdict
            
            def _parse_result_tuple(fx):
                # Spróbuj różne pola
                res = fx.get('result') or fx.get('score')
                hg = fx.get('home_goals') or fx.get('homeGoals')
                ag = fx.get('away_goals') or fx.get('awayGoals')
                if hg is not None and ag is not None:
                    return int(float(hg)), int(float(ag))
                if isinstance(res, str) and '-' in res:
                    try:
                        a, b = res.replace(' ', '').split('-', 1)
                        return int(a), int(b)
                    except:
                        return None, None
                return None, None
            
            rounds_map = defaultdict(list)
            for fx in all_fixtures:
                match_dt = fx.get('match_date') or fx.get('date') or fx.get('matchDate')
                if not match_dt:
                    continue
                round_date = str(match_dt).split(' ')[0]
                round_id = f"round_{round_date}"
                hg, ag = _parse_result_tuple(fx)
                match_payload = {
                    'match_id': str(fx.get('match_id') or fx.get('matchId') or ''),
                    'home_team_name': fx.get('home_team_name') or fx.get('homeTeamName') or fx.get('home_team') or '',
                    'away_team_name': fx.get('away_team_name') or fx.get('awayTeamName') or fx.get('away_team') or '',
                    'match_date': match_dt,
                }
                if hg is not None and ag is not None:
                    match_payload['home_goals'] = hg
                    match_payload['away_goals'] = ag
                rounds_map[round_id].append(match_payload)
            
            season_id = f"season_{current_season}" if current_season is not None else storage.get_current_season() or 'season_current'
            for r_id, matches in rounds_map.items():
                try:
                    storage.add_round(season_id=season_id, round_id=r_id, matches=matches, start_date=r_id.replace('round_', '') + " 00:00:00")
                except Exception as e:
                    logger.warning(f"Nie udało się zapisać rundy {r_id}: {e}")
        except Exception as e:
            logger.warning(f"Persist rounds warning: {e}")
        
        # Jeśli nie znaleziono sezonu w meczach, spróbuj pobrać z get_league_details
        if current_season is None:
            try:
                for league_id in TIPPER_LEAGUES:
                    league_details = client.get_league_details(league_id)
                    if league_details and 'season' in league_details:
                        current_season = league_details['season']
                        logger.info(f"Pobrano sezon z get_league_details dla ligi {league_id}: {current_season}")
                        break
            except Exception as e:
                logger.warning(f"Nie udało się pobrać sezonu z get_league_details: {e}")
        
        # Jeśli nadal nie ma sezonu, użyj domyślnego
        if current_season is None:
            current_season = "current_season"
            logger.warning("Nie znaleziono sezonu w API, używam domyślnego: current_season")
        
        # Zapisz sezon w storage
        season_id = f"season_{current_season}"
        if season_id not in storage.data.get('seasons', {}):
            # Pobierz pierwszą ligę dla sezonu
            first_league_id = TIPPER_LEAGUES[0] if TIPPER_LEAGUES else None
            storage.add_season(first_league_id, season_id, None, None)
            logger.info(f"Dodano sezon do storage: {season_id}")
        
        # Sprawdź czy aktualny sezon z API jest inny niż zapisany w storage
        # Jeśli tak, oznacza to, że sezon się zmienił (np. z 80 na 81)
        try:
            stored_current_season_id = storage.get_current_season()
        except Exception as e:
            logger.error(f"Błąd pobierania aktualnego sezonu z storage: {e}")
            stored_current_season_id = None
        
        # Jeśli API zwraca sezon 80, to jest to aktualny sezon
        # Sezon 80 jest aktualny, dopóki nie ma 14 rund i API nie zwróci nowego sezonu (81)
        if stored_current_season_id and stored_current_season_id != season_id:
            # Sprawdź czy stary sezon ma już 14 rund (sezon zakończony)
            if stored_current_season_id.startswith('season_'):
                # Policz rundy w starym sezonie
                rounds_in_old_season = []
                for round_id, round_data in storage.data.get('rounds', {}).items():
                    if round_data.get('season_id') == stored_current_season_id:
                        rounds_in_old_season.append(round_id)
                
                # Jeśli stary sezon ma 14 rund, to się skończył i nowy sezon z API jest aktualny
                if len(rounds_in_old_season) >= 14:
                    old_season_num = stored_current_season_id.replace('season_', '') if stored_current_season_id.startswith('season_') else stored_current_season_id
                    logger.info(f"Wykryto zmianę sezonu: {old_season_num} -> {current_season}. Stary sezon ({old_season_num}) ma {len(rounds_in_old_season)} rund - sezon zakończony.")
                    # Ustaw nowy sezon jako aktualny
                    storage.set_current_season(season_id)
                    # Jeśli użytkownik nie wybrał sezonu ręcznie, ustaw nowy sezon jako domyślny
                    if 'selected_season_id' not in st.session_state or st.session_state.selected_season_id == stored_current_season_id:
                        st.session_state.selected_season_id = season_id
                else:
                    # Stary sezon nie ma jeszcze 14 rund - użyj starego sezonu jako aktualnego
                    # API może zwracać nowy sezon, ale stary sezon jeszcze się nie skończył
                    logger.info(f"Stary sezon {stored_current_season_id} ma tylko {len(rounds_in_old_season)} rund - jeszcze się nie skończył. Używam starego sezonu jako aktualnego.")
                    season_id = stored_current_season_id
            else:
                # Stary sezon nie ma prawidłowego formatu - użyj nowego sezonu z API
                logger.info(f"Stary sezon {stored_current_season_id} nie ma prawidłowego formatu. Używam nowego sezonu z API: {season_id}")
                storage.set_current_season(season_id)
        
        # Użyj wybranego sezonu z filtra (jeśli jest), w przeciwnym razie użyj aktualnego
        # ZAWSZE ustaw aktualny sezon w storage (sezon 80 z API jest aktualny)
        # To zapewni, że sezon 80 jest zapisany jako aktualny sezon w bazie
        storage.set_current_season(season_id)
        logger.info(f"Ustawiono aktualny sezon w storage: {season_id} (z API: {current_season})")
        
        # Jeśli użytkownik nie wybrał sezonu ręcznie, użyj aktualnego sezonu z API
        if 'selected_season_id' not in st.session_state or not st.session_state.selected_season_id:
            st.session_state.selected_season_id = season_id
            logger.info(f"Ustawiono wybrany sezon w session_state: {season_id}")
        else:
            # Użytkownik wybrał sezon ręcznie - użyj wybranego sezonu
            season_id = st.session_state.selected_season_id
            logger.info(f"Używam wybranego sezonu z filtra: {season_id}")
        
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
        
        # Mapowanie drużyna->liga (DB-first per sezon)
        # Strategia: 1) season_teams dla sezonu, 2) tabela teams, 3) matches dla sezonu, 4) mecze z API, 5) selected_teams
        selected_season_id_for_teams = st.session_state.get('selected_season_id', season_id)
        teams_with_leagues: Dict[str, str] = {}
        tmp_map: Dict[str, int] = {}
        
        # 1. Użyj drużyn z season_teams dla wybranego sezonu (najlepsze źródło per sezon)
        if hasattr(storage, 'get_season_teams'):
            try:
                season_teams = storage.get_season_teams(selected_season_id_for_teams, only_selected=False)
                if season_teams:
                    for team in season_teams:
                        team_name = team['team_name']
                        league_id = team.get('league_id')
                        league_name = team.get('league_name') or (f"Liga {league_id}" if league_id else "?")
                        teams_with_leagues[team_name] = league_name
                        if league_id:
                            tmp_map[team_name] = int(league_id)
                    logger.info(f"DEBUG: Dodano {len(teams_with_leagues)} drużyn z season_teams dla sezonu {selected_season_id_for_teams}")
            except Exception as e:
                logger.warning(f"Błąd pobierania season_teams z bazy: {e}")
        
        # 2. Fallback: użyj drużyn z tabeli teams (globalne)
        if not teams_with_leagues:
            teams_with_leagues_db = {}
            try:
                if hasattr(storage, 'get_team_leagues'):
                    teams_with_leagues_db = storage.get_team_leagues()
                    logger.info(f"DEBUG: Pobrano {len(teams_with_leagues_db)} drużyn z tabeli teams")
            except Exception as e:
                logger.warning(f"Błąd pobierania teams z bazy: {e}")
                teams_with_leagues_db = {}
            
            if teams_with_leagues_db:
                for team_name, meta in teams_with_leagues_db.items():
                    league_name = meta.get('league_name') or (f"Liga {meta.get('league_id')}" if meta.get('league_id') else "?")
                    teams_with_leagues[team_name] = league_name
                    if meta.get('league_id'):
                        tmp_map[team_name] = int(meta['league_id'])
                logger.info(f"DEBUG: Dodano {len(teams_with_leagues)} drużyn z tabeli teams do teams_with_leagues")
        
        # 3. Jeśli nadal puste, spróbuj z matches dla wybranego sezonu
        if not teams_with_leagues and hasattr(storage, 'conn'):
            try:
                selected_season_id = st.session_state.get('selected_season_id', season_id)
                logger.info(f"DEBUG: Próbuję pobrać drużyny z matches dla sezonu: {selected_season_id}")
                db_teams_df = storage.conn.query(
                    "SELECT DISTINCT m.home_team_name AS team_name, m.league_id "
                    "FROM matches m INNER JOIN rounds r ON r.round_id = m.round_id "
                    f"WHERE r.season_id = '{selected_season_id}' AND m.home_team_name IS NOT NULL AND m.home_team_name != '' "
                    "UNION "
                    "SELECT DISTINCT m.away_team_name AS team_name, m.league_id "
                    "FROM matches m INNER JOIN rounds r ON r.round_id = m.round_id "
                    f"WHERE r.season_id = '{selected_season_id}' AND m.away_team_name IS NOT NULL AND m.away_team_name != ''",
                    ttl=120
                )
                if not db_teams_df.empty:
                    logger.info(f"DEBUG: Znaleziono {len(db_teams_df)} drużyn w matches dla sezonu {selected_season_id}")
                    for _, row in db_teams_df.iterrows():
                        tname = (str(row['team_name']) or '').strip()
                        lid = row.get('league_id')
                        if tname and lid is not None and tname not in tmp_map:
                            tmp_map[tname] = int(lid)
                            teams_with_leagues[tname] = league_names_map.get(lid, f"Liga {lid}")
                else:
                    logger.warning(f"DEBUG: Brak drużyn w matches dla sezonu {selected_season_id}")
            except Exception as e:
                logger.warning(f"DB-fallback team map failed: {e}")
        
        # 4. Jeśli nadal puste, spróbuj z meczów z API
        if not teams_with_leagues:
            logger.info(f"DEBUG: Próbuję pobrać drużyny z meczów z API (sorted_rounds_asc ma {len(sorted_rounds_asc)} rund)")
            for _, matches in sorted_rounds_asc:
                for match in matches:
                    home_team = match.get('home_team_name', '').strip()
                    away_team = match.get('away_team_name', '').strip()
                    mid = match.get('league_id')
                    if mid is not None:
                        if home_team and home_team not in tmp_map:
                            tmp_map[home_team] = int(mid)
                            teams_with_leagues[home_team] = league_names_map.get(int(mid), f"Liga {int(mid)}")
                        if away_team and away_team not in tmp_map:
                            tmp_map[away_team] = int(mid)
                            teams_with_leagues[away_team] = league_names_map.get(int(mid), f"Liga {int(mid)}")
            if teams_with_leagues:
                logger.info(f"DEBUG: Dodano {len(teams_with_leagues)} drużyn z meczów z API")
        
        # 4. ZAWSZE dodaj selected_teams (zapisane w ustawieniach) - nawet jeśli już są w teams_with_leagues
        # Ale najpierw spróbuj znaleźć ich ligi w bazie danych
        # Pobierz zespoły per sezon lub globalne (dla kompatybilności wstecznej)
        selected_season_id_for_teams = st.session_state.get('selected_season_id', season_id)
        if hasattr(storage, 'get_selected_season_teams'):
            selected_teams_from_db = storage.get_selected_season_teams(selected_season_id_for_teams)
        else:
            selected_teams_from_db = storage.get_selected_teams()
        logger.info(f"DEBUG: Pobrano {len(selected_teams_from_db) if selected_teams_from_db else 0} drużyn z selected_teams (sezon: {selected_season_id_for_teams})")
        if selected_teams_from_db:
            for team_name in selected_teams_from_db:
                if team_name:
                    # Jeśli drużyna już jest w teams_with_leagues, nie rób nic
                    if team_name in teams_with_leagues:
                        logger.info(f"DEBUG: Drużyna {team_name} już jest w teams_with_leagues z ligą: {teams_with_leagues[team_name]}")
                        continue
                    
                    # Spróbuj znaleźć ligę dla tej drużyny
                    league_name = "?"
                    
                    # 1. Sprawdź w teams_with_leagues_db (z tabeli teams) - już mamy to w pamięci
                    if teams_with_leagues_db and team_name in teams_with_leagues_db:
                        meta = teams_with_leagues_db[team_name]
                        league_name = meta.get('league_name') or (f"Liga {meta.get('league_id')}" if meta.get('league_id') else "?")
                        logger.info(f"DEBUG: Znaleziono ligę dla {team_name} w tabeli teams: {league_name}")
                    # 2. Jeśli nie ma, sprawdź w tmp_map (z matches lub API - już przetworzone)
                    elif team_name in tmp_map:
                        lid = tmp_map[team_name]
                        league_name = league_names_map.get(lid, f"Liga {lid}")
                        logger.info(f"DEBUG: Znaleziono ligę dla {team_name} w tmp_map: {league_name}")
                    # 3. Jeśli nadal nie ma, spróbuj znaleźć w matches dla wybranego sezonu (zapytanie do DB)
                    elif hasattr(storage, 'conn'):
                        try:
                            selected_season_id = st.session_state.get('selected_season_id', season_id)
                            # Escapowanie apostrofów dla SQL
                            escaped_team_name = team_name.replace("'", "''")
                            team_league_df = storage.conn.query(
                                f"SELECT DISTINCT m.league_id FROM matches m "
                                f"INNER JOIN rounds r ON r.round_id = m.round_id "
                                f"WHERE r.season_id = '{selected_season_id}' "
                                f"AND (m.home_team_name = '{escaped_team_name}' OR m.away_team_name = '{escaped_team_name}') "
                                f"LIMIT 1",
                                ttl=120
                            )
                            if not team_league_df.empty:
                                lid = team_league_df.iloc[0].get('league_id')
                                if lid is not None:
                                    league_name = league_names_map.get(int(lid), f"Liga {int(lid)}")
                                    logger.info(f"DEBUG: Znaleziono ligę dla {team_name} w matches: {league_name}")
                                    # Dodaj do tmp_map, aby nie szukać ponownie
                                    tmp_map[team_name] = int(lid)
                        except Exception as e:
                            logger.warning(f"DEBUG: Błąd szukania ligi dla {team_name} w matches: {e}")
                    # 4. Jeśli nadal nie ma, spróbuj znaleźć w meczach z API
                    if league_name == "?" and sorted_rounds_asc:
                        for _, matches in sorted_rounds_asc:
                            for match in matches:
                                home_team = match.get('home_team_name', '').strip()
                                away_team = match.get('away_team_name', '').strip()
                                mid = match.get('league_id')
                                if (home_team == team_name or away_team == team_name) and mid is not None:
                                    league_name = league_names_map.get(int(mid), f"Liga {int(mid)}")
                                    logger.info(f"DEBUG: Znaleziono ligę dla {team_name} w meczach z API: {league_name}")
                                    # Dodaj do tmp_map, aby nie szukać ponownie
                                    tmp_map[team_name] = int(mid)
                                    break
                            if league_name != "?":
                                break
                    
                    teams_with_leagues[team_name] = league_name
                    logger.info(f"DEBUG: Dodano drużynę {team_name} z selected_teams do teams_with_leagues z ligą: {league_name}")
        
        # Zapisz do DB jeśli mamy nowe dane z API
        if tmp_map and hasattr(storage, 'bulk_upsert_team_leagues'):
            try:
                storage.bulk_upsert_team_leagues(tmp_map)
                logger.info(f"DEBUG: Zapisano {len(tmp_map)} drużyn do tabeli teams")
            except Exception:
                pass
        
        # Sprawdź czy wybrane drużyny zawierają drużyny z meczów z API
        # Zbierz wszystkie drużyny z meczów z API
        teams_in_matches = set()
        for _, matches in sorted_rounds_asc:
            for match in matches:
                home_team = match.get('home_team_name', '').strip()
                away_team = match.get('away_team_name', '').strip()
                if home_team:
                    teams_in_matches.add(home_team)
                if away_team:
                    teams_in_matches.add(away_team)
        
        logger.info(f"DEBUG: Drużyny w meczach z API: {len(teams_in_matches)} drużyn")
        logger.info(f"DEBUG: Przykładowe drużyny z API: {list(teams_in_matches)[:5]}")
        
        # Uzupełnij teams_with_leagues o drużyny z meczów, które nie są jeszcze w mapie
        # Również zaktualizuj tmp_map dla drużyn z meczów
        for team_name in teams_in_matches:
            if team_name and team_name not in teams_with_leagues:
                # Spróbuj znaleźć ligę dla tej drużyny
                league_name = "?"
                lid = None
                
                # Najpierw sprawdź tmp_map (już przetworzone)
                if team_name in tmp_map:
                    lid = tmp_map[team_name]
                    league_name = league_names_map.get(lid, f"Liga {lid}")
                else:
                    # Spróbuj znaleźć w meczach
                    for _, matches in sorted_rounds_asc:
                        for match in matches:
                            if match.get('home_team_name', '').strip() == team_name or match.get('away_team_name', '').strip() == team_name:
                                lid = match.get('league_id')
                                if lid:
                                    tmp_map[team_name] = int(lid)
                                    league_name = league_names_map.get(int(lid), f"Liga {int(lid)}")
                                    break
                        if lid:
                            break
                
                teams_with_leagues[team_name] = league_name
        
        # Zapisz do session_state, by inne sekcje mogły używać tej mapy
        st.session_state['teams_with_leagues'] = teams_with_leagues
        
        all_team_names = sorted(list(teams_with_leagues.keys()))
        logger.info(f"DEBUG: Końcowa lista all_team_names zawiera {len(all_team_names)} drużyn: {all_team_names[:5]}...")
        
        # Pobierz zapisane ustawienia per sezon lub globalne (dla kompatybilności wstecznej)
        selected_season_id_for_teams = st.session_state.get('selected_season_id', season_id)
        if hasattr(storage, 'get_selected_season_teams'):
            selected_teams = storage.get_selected_season_teams(selected_season_id_for_teams)
        else:
            selected_teams = storage.get_selected_teams()
        logger.info(f"DEBUG: Pobrano z bazy selected_teams: {len(selected_teams) if selected_teams else 0} drużyn (sezon: {selected_season_id_for_teams})")
        
        # Jeśli nie ma zapisanych ustawień LUB wybrane drużyny nie zawierają żadnej drużyny z meczów z API
        # wybierz wszystkie drużyny z API i zapisz je w bazie per sezon
        if not selected_teams:
            logger.info(f"DEBUG: Brak zapisanych drużyn w bazie, wybieram wszystkie drużyny z API ({len(teams_in_matches)} drużyn)")
            selected_teams = sorted(list(teams_in_matches))
            # Najpierw dodaj zespoły do season_teams z league_id i league_name, potem ustaw is_selected
            if hasattr(storage, 'bulk_add_season_teams'):
                teams_to_add = []
                for team_name in all_team_names:
                    league_name = teams_with_leagues.get(team_name, "?")
                    # Znajdź league_id dla tego zespołu
                    league_id = tmp_map.get(team_name)
                    if not league_id:
                        # Spróbuj znaleźć w meczach
                        for _, matches in sorted_rounds_asc:
                            for match in matches:
                                if match.get('home_team_name', '').strip() == team_name or match.get('away_team_name', '').strip() == team_name:
                                    league_id = match.get('league_id')
                                    if league_id:
                                        break
                            if league_id:
                                break
                    teams_to_add.append({
                        'team_name': team_name,
                        'league_id': league_id if league_id is not None else None,
                        'league_name': league_name if league_name != "?" else (f"Liga {league_id}" if league_id else "?"),
                        'is_selected': team_name in selected_teams
                    })
                if teams_to_add:
                    storage.bulk_add_season_teams(selected_season_id_for_teams, teams_to_add)
                    logger.info(f"DEBUG: Dodano {len(teams_to_add)} zespołów do season_teams (sezon: {selected_season_id_for_teams})")
            elif hasattr(storage, 'set_season_team_selected'):
                for team_name in all_team_names:
                    is_selected = team_name in selected_teams
                    storage.set_season_team_selected(selected_season_id_for_teams, team_name, is_selected)
            else:
                storage.set_selected_teams(selected_teams)
            logger.info(f"DEBUG: Zapisano {len(selected_teams)} drużyn w bazie (sezon: {selected_season_id_for_teams})")
        elif not any(team in teams_in_matches for team in selected_teams):
            logger.warning(f"DEBUG: Wybrane drużyny ({len(selected_teams)}) nie zawierają żadnej drużyny z meczów z API ({len(teams_in_matches)}). Automatycznie wybieram wszystkie drużyny z API.")
            logger.warning(f"DEBUG: Przykładowe wybrane drużyny: {selected_teams[:5]}")
            logger.warning(f"DEBUG: Przykładowe drużyny z API: {list(teams_in_matches)[:5]}")
            selected_teams = sorted(list(teams_in_matches))
            # Najpierw dodaj zespoły do season_teams z league_id i league_name, potem ustaw is_selected
            if hasattr(storage, 'bulk_add_season_teams'):
                teams_to_add = []
                for team_name in all_team_names:
                    league_name = teams_with_leagues.get(team_name, "?")
                    # Znajdź league_id dla tego zespołu
                    league_id = tmp_map.get(team_name)
                    if not league_id:
                        # Spróbuj znaleźć w meczach
                        for _, matches in sorted_rounds_asc:
                            for match in matches:
                                if match.get('home_team_name', '').strip() == team_name or match.get('away_team_name', '').strip() == team_name:
                                    league_id = match.get('league_id')
                                    if league_id:
                                        break
                            if league_id:
                                break
                    teams_to_add.append({
                        'team_name': team_name,
                        'league_id': league_id if league_id is not None else None,
                        'league_name': league_name if league_name != "?" else (f"Liga {league_id}" if league_id else "?"),
                        'is_selected': team_name in selected_teams
                    })
                if teams_to_add:
                    storage.bulk_add_season_teams(selected_season_id_for_teams, teams_to_add)
                    logger.info(f"DEBUG: Dodano {len(teams_to_add)} zespołów do season_teams (sezon: {selected_season_id_for_teams})")
            elif hasattr(storage, 'set_season_team_selected'):
                for team_name in all_team_names:
                    is_selected = team_name in selected_teams
                    storage.set_season_team_selected(selected_season_id_for_teams, team_name, is_selected)
            else:
                storage.set_selected_teams(selected_teams)
            logger.info(f"DEBUG: Zapisano {len(selected_teams)} drużyn w bazie (sezon: {selected_season_id_for_teams})")
        
        logger.info(f"DEBUG: Końcowe wybrane drużyny ({len(selected_teams)}): {selected_teams[:5]}...")
        
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
        
        # Filtruj rundy (według daty asc dla numeracji) - również po sezonie
        filtered_rounds_asc = []
        # Użyj wybranego sezonu z filtra, jeśli nie ma, użyj aktualnego sezonu (season_80)
        # Upewnij się, że selected_season_id jest zawsze ustawiony
        selected_season_id = st.session_state.get('selected_season_id', None)
        if not selected_season_id:
            # Jeśli nie ma wybranego sezonu, użyj aktualnego sezonu z API
            selected_season_id = season_id
            st.session_state.selected_season_id = season_id
            logger.info(f"DEBUG filtrowanie rund: selected_season_id był None, ustawiono na {season_id}")
        logger.info(f"DEBUG filtrowanie rund: selected_season_id={selected_season_id}, season_id={season_id}, liczba rund z API={len(sorted_rounds_asc)}")

        # Uzupełnij wyniki z API tylko dla nieukończonych meczów w wybranym sezonie
        try:
            refresh_unfinished_matches_from_api(storage, selected_season_id, throttle_seconds=180)
        except Exception as e:
            logger.warning(f"Nie udało się odświeżyć wyników z API: {e}")
        
        for date, matches in sorted_rounds_asc:
            # Sprawdź czy runda jest przypisana do wybranego sezonu
            round_id = f"round_{date}"
            round_data = storage.data.get('rounds', {}).get(round_id, {})
            round_season_id = round_data.get('season_id') if round_data else None
            
            logger.info(f"DEBUG filtrowanie rund: date={date}, round_id={round_id}, round_season_id={round_season_id}, selected_season_id={selected_season_id}, mecze={len(matches)}")
            
            # Filtrowanie po sezonie:
            # - Jeśli runda ma przypisany sezon i jest inny niż wybrany, pomiń ją
            # - Jeśli runda nie ma przypisanego sezonu (round_season_id jest None), dodaj ją (będzie przypisana do wybranego sezonu)
            # - Jeśli runda ma przypisany sezon i jest taki sam jak wybrany, dodaj ją
            # WAŻNE: Jeśli selected_season_id jest None, nie filtruj po sezonie (dodaj wszystkie rundy)
            if selected_season_id:
                # Jeśli runda ma przypisany sezon i jest inny niż wybrany, pomiń ją
                if round_season_id and round_season_id != selected_season_id:
                    # Pomiń rundy z innych sezonów
                    logger.info(f"DEBUG filtrowanie rund: Pomijam rundę {round_id} - ma sezon {round_season_id}, wybrany sezon to {selected_season_id}")
                    continue
                # Jeśli runda nie ma przypisanego sezonu (round_season_id jest None) LUB sezon pasuje, dodaj ją
                logger.info(f"DEBUG filtrowanie rund: Dodaję rundę {round_id} - nie ma przypisanego sezonu (None) lub sezon pasuje ({round_season_id} == {selected_season_id})")
            else:
                # Jeśli selected_season_id jest None, nie filtruj po sezonie (dodaj wszystkie rundy)
                logger.warning(f"DEBUG filtrowanie rund: selected_season_id jest None - nie filtruję po sezonie, dodaję wszystkie rundy")
            
            filtered_matches = filter_matches_by_teams(matches, selected_teams)
            logger.info(f"DEBUG filtrowanie rund: Po filtrowaniu drużyn - mecze={len(filtered_matches)} z {len(matches)}")
            logger.info(f"DEBUG filtrowanie rund: Wybrane drużyny ({len(selected_teams)}): {selected_teams[:5]}...")
            if len(matches) > 0:
                sample_match = matches[0]
                sample_home = sample_match.get('home_team_name', '?')
                sample_away = sample_match.get('away_team_name', '?')
                logger.info(f"DEBUG filtrowanie rund: Przykładowy mecz: {sample_home} vs {sample_away}")
                logger.info(f"DEBUG filtrowanie rund: Czy {sample_home} w selected_teams? {sample_home in selected_teams}")
                logger.info(f"DEBUG filtrowanie rund: Czy {sample_away} w selected_teams? {sample_away in selected_teams}")
            if filtered_matches:  # Tylko jeśli są jakieś mecze po filtrowaniu
                filtered_rounds_asc.append((date, filtered_matches))
                logger.info(f"DEBUG filtrowanie rund: ✅ Dodano rundę {round_id} do filtered_rounds_asc")
            else:
                logger.warning(f"DEBUG filtrowanie rund: ❌ Pomijam rundę {round_id} - brak meczów po filtrowaniu drużyn (było {len(matches)} meczów)")
        
        logger.info(f"DEBUG filtrowanie rund: Końcowa liczba rund po filtrowaniu: {len(filtered_rounds_asc)}")
        
        # Domyślnie wyświetlamy wszystkie kolejki (bez filtrowania archiwum)
        
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
        # Wyświetl sezon w nagłówku rankingu (użyj wybranego sezonu z filtra)
        if 'selected_season_id' in st.session_state and st.session_state.selected_season_id:
            selected_season_num = st.session_state.selected_season_id.replace('season_', '') if st.session_state.selected_season_id.startswith('season_') else st.session_state.selected_season_id
            season_display = f"Sezon {selected_season_num}"
        else:
            season_display = current_season if current_season != "current_season" else "Bieżący"
        st.subheader(f"🏆 Ranking {season_display}")
        
        # Tabs dla rankingu per kolejka i całości - domyślnie ranking całości (pierwszy tab)
        ranking_tab1, ranking_tab2 = st.tabs(["🏆 Ranking całości", "📊 Ranking per kolejka"])
        
        # Dla rankingu całości nie potrzebujemy wyboru rundy
        with ranking_tab1:
            st.markdown(f"### 🏆 Ranking całości - Sezon {season_display}")
            
            exclude_worst = st.checkbox("Odrzuć najgorszy wynik każdego gracza", value=True, key="exclude_worst_overall")
            # Użyj wybranego sezonu z filtra
            selected_season_id = st.session_state.get('selected_season_id', season_id)
            leaderboard = cached_overall_leaderboard(
                selected_season_id,
                exclude_worst,
                st.session_state.get('data_version', 0)
            )
            
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
                st.dataframe(df_leaderboard, width="stretch", hide_index=True)
                
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
                    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": True}, key="ranking_overall_chart_main")
                    
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
                # Kolejka zakończona tylko jeśli wszystkie mecze mają wyniki z API
                finished_count = sum(1 for m in matches if is_match_finished(m))
                has_api_results = (len(matches) > 0 and finished_count == len(matches))
                round_number = date_to_round_number.get(date, '?')
                logger.info(f"DEBUG ranking: idx={idx}, date={date}, round_number={round_number}, has_api_results={has_api_results}, matches_count={len(matches)}, finished_count={finished_count}")
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
                
                # WAŻNE: NIE wywołuj add_round tutaj, jeśli runda już istnieje w bazie
                # add_round może nadpisać wyniki meczów, jeśli mecze z API mają home_goals=None
                # Zamiast tego, sprawdź czy runda istnieje w bazie (dla MySQL)
                round_exists_in_db = False
                if hasattr(storage, 'conn'):
                    try:
                        rounds_df = storage.conn.query(
                            f"SELECT round_id FROM rounds WHERE round_id = '{round_id}'",
                            ttl=0
                        )
                        round_exists_in_db = not rounds_df.empty
                    except Exception:
                        pass
                
                # Dodaj rundę do storage tylko jeśli nie istnieje (ani w storage.data, ani w bazie)
                if round_id not in storage.data['rounds'] and not round_exists_in_db:
                    # Użyj wybranego sezonu z filtra
                    selected_season_id = st.session_state.get('selected_season_id', season_id)
                    logger.info(f"📝 Dodaję rundę {round_id} do storage (nie istnieje w storage.data ani w bazie)")
                    storage.add_round(selected_season_id, round_id, selected_matches, selected_round_date)
                elif round_exists_in_db:
                    logger.info(f"✅ Runda {round_id} już istnieje w bazie, NIE wywołuję add_round (aby nie nadpisać wyników)")
                
                # Przed pobraniem rankingu, zaktualizuj status meczów z API (tylko te, które nie są zakończone)
                # To zapewni, że is_finished=1 dla meczów, które mają wyniki
                if hasattr(storage, 'conn'):
                    try:
                        # Pobierz mecze, które nie są zakończone (is_finished=0) ale mogą mieć wyniki
                        unfinished_matches_df = storage.conn.query(
                            f"""
                            SELECT match_id, round_id, league_id 
                            FROM matches 
                            WHERE round_id = '{round_id}' 
                            AND is_finished = 0
                            """,
                            ttl=0
                        )
                        
                        if not unfinished_matches_df.empty:
                            # Jeśli są mecze bez is_finished=1, sprawdź czy mają wyniki i zaktualizuj
                            # Lub wywołaj refresh_unfinished_matches_from_api dla tej rundy
                            selected_season_id_for_refresh = st.session_state.get('selected_season_id', season_id)
                            refresh_unfinished_matches_from_api(storage, selected_season_id_for_refresh, throttle_seconds=0)
                    except Exception as e:
                        logger.warning(f"Błąd aktualizacji statusu meczów przed rankingiem: {e}")
                
                # Ranking dla wybranej rundy (cache)
                round_leaderboard = cached_round_leaderboard(
                    round_id,
                    st.session_state.get('data_version', 0)
                )
                
                # Debug: sprawdź czy są gracze w bazie i czy runda istnieje
                if not round_leaderboard:
                    # Sprawdź czy są gracze w bazie
                    all_players = list(storage.data.get('players', {}).keys())
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
                    st.dataframe(df_round_leaderboard, width="stretch", hide_index=True)
                    
                    # Dodaj expandery z typami dla każdego gracza
                    st.markdown("### 📋 Szczegóły typów")
                    for player in round_leaderboard:
                        player_name = player['player_name']
                        player_predictions = cached_player_predictions(
                            player_name, round_id, st.session_state.get('data_version', 0)
                        )
                        
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
                                pred_home = safe_int(pred.get('home', 0))
                                pred_away = safe_int(pred.get('away', 0))
                                
                                # WAŻNE: Pobierz punkty TYLKO jeśli mecz jest zakończony (is_finished=1)
                                match_is_finished = is_match_finished(match)
                                match_points_dict = round_data.get('match_points', {}).get(player_name, {})
                                points = match_points_dict.get(match_id, 0) if match_is_finished else 0
                                
                                # Pobierz wynik meczu jeśli rozegrany
                                home_goals = match.get('home_goals')
                                away_goals = match.get('away_goals')
                                result = f"{safe_int(home_goals)}-{safe_int(away_goals)}" if home_goals is not None and away_goals is not None else "—"
                                
                                types_table_data.append({
                                    'Mecz': f"{home_team} vs {away_team}",
                                    'Typ': f"{pred_home}-{pred_away}",
                                    'Wynik': result,
                                    'Punkty': points
                                })
                            
                            if types_table_data:
                                with st.expander(f"👤 {player_name} - Typy i wyniki", expanded=False):
                                    df_types = pd.DataFrame(types_table_data)
                                    st.dataframe(df_types, width="stretch", hide_index=True)
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
                        st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": True}, key=f"ranking_round_{round_number}_chart")
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
            # Kolejka zakończona tylko jeśli wszystkie mecze mają wyniki z API
            finished_count = sum(1 for m in matches if is_match_finished(m))
            has_api_results = (len(matches) > 0 and finished_count == len(matches))
            round_number = date_to_round_number.get(date, '?')
            logger.info(f"DEBUG input: idx={idx}, date={date}, round_number={round_number}, has_api_results={has_api_results}, matches_count={len(matches)}, finished_count={finished_count}")
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
        
        # Przycisk do odświeżania danych z API dla wybranej kolejki
        col1, col2 = st.columns([3, 1])
        with col2:
            if st.button("🔄 Odśwież dane z API", key="refresh_round_api", help="Pobierz aktualne wyniki z API dla wybranej kolejki"):
                if selected_round_idx is not None:
                    selected_round_date, selected_matches = filtered_rounds[selected_round_idx]
                    round_id = f"round_{selected_round_date}"
                    refresh_round_from_api(storage, round_id, selected_matches)
                    st.success(f"✅ Zaktualizowano dane z API dla kolejki {date_to_round_number.get(selected_round_date, '?')}")
                    st.rerun()
        
        # Zapisz wybór rundy w session_state (synchronizacja z rankingiem)
        # Oznacz że użytkownik wybrał kolejkę ręcznie (jeśli wybór różni się od domyślnego)
        if selected_round_idx != default_round_idx:
            st.session_state.user_manually_selected_round = True
        st.session_state.selected_round_idx = selected_round_idx
        
        if selected_round_idx is not None:
            selected_round_date, selected_matches = filtered_rounds[selected_round_idx]
            # Posortuj mecze: najpierw liga 32612, potem 9399, następnie reszta
            try:
                _prio = {32612: 0, 9399: 1}
                selected_matches = sorted(
                    selected_matches,
                    key=lambda m: (_prio.get(m.get('league_id'), 2), m.get('match_date', ''))
                )
            except Exception:
                pass
            round_number = date_to_round_number[selected_round_date]  # Numer kolejki według daty asc (1 = najstarsza)
            round_id = f"round_{selected_round_date}"
            
            # WAŻNE: NIE wywołuj add_round tutaj, jeśli runda już istnieje w bazie
            # add_round może nadpisać wyniki meczów, jeśli mecze z API mają home_goals=None
            # Zamiast tego, sprawdź czy runda istnieje w bazie (dla MySQL)
            round_exists_in_db = False
            if hasattr(storage, 'conn'):
                try:
                    rounds_df = storage.conn.query(
                        f"SELECT round_id FROM rounds WHERE round_id = '{round_id}'",
                        ttl=0
                    )
                    round_exists_in_db = not rounds_df.empty
                except Exception:
                    pass
            
            # Dodaj rundę do storage tylko jeśli nie istnieje (ani w storage.data, ani w bazie)
            if round_id not in storage.data['rounds'] and not round_exists_in_db:
                # Użyj wybranego sezonu z filtra
                selected_season_id = st.session_state.get('selected_season_id', season_id)
                logger.info(f"📝 Dodaję rundę {round_id} do storage (nie istnieje w storage.data ani w bazie)")
                storage.add_round(selected_season_id, round_id, selected_matches, selected_round_date)
            elif round_exists_in_db:
                logger.info(f"✅ Runda {round_id} już istnieje w bazie, NIE wywołuję add_round (aby nie nadpisać wyników)")
            
            # Wyświetl mecze w rundzie - tabela na górze dla czytelności
            st.subheader(f"⚽ Kolejka {round_number} - {selected_round_date}")
            
            # Pobierz league_names_map z session_state (jeśli dostępna)
            if 'league_names_map' in st.session_state:
                league_names_map = st.session_state.league_names_map
            else:
                # Jeśli nie ma w session_state, utwórz pustą mapę
                league_names_map = {}
            
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
                if is_match_finished(match):
                    if home_goals is not None and away_goals is not None:
                        status = f"✅ {safe_int(home_goals)}-{safe_int(away_goals)}"
                    else:
                        status = "✅ Po czasie (brak wyniku)"
                else:
                    try:
                        match_dt = datetime.strptime(match_date, "%Y-%m-%d %H:%M:%S")
                        if datetime.now() >= match_dt:
                            status = "⏰ Rozpoczęty"
                    except:
                        pass
                
                # Nazwa ligi z bazy danych (DB-first)
                league_name = get_league_name_for_match(storage, match, round_id)
                league_info = f" (Liga: {league_name})"
                
                matches_table_data.append({
                    'Gospodarz': f"{home_team}{league_info}",
                    'Gość': f"{away_team}{league_info}",
                    'Data': match_date,
                    'Status': status
                })
            
            # Wyświetl tabelę z meczami
            if matches_table_data:
                df_matches = pd.DataFrame(matches_table_data)
                st.dataframe(df_matches, width="stretch", hide_index=True)
            
            
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
                # Szybki wybór jednego gracza do edycji (ogranicza liczbę widgetów i przyspiesza render)
                player_name = st.selectbox("Wybierz gracza do edycji", all_players_list, key="tipper_player_select", index=0)
                if player_name:
                    # Pobierz istniejące typy gracza dla tej rundy (zawsze bezpośrednio z bazy, ttl=0)
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
                        input_key = f"tipper_pred_{player_name}_{match_id}"
                        
                        # Ustaw wartość w session_state tylko jeśli klucz nie istnieje
                        # To zapewnia, że po usunięciu klucza przed rerun(), wartość zostanie zaktualizowana
                        if input_key not in st.session_state:
                            if has_existing:
                                existing_pred = existing_predictions[match_id]
                                default_value = f"{safe_int(existing_pred.get('home', 0))}-{safe_int(existing_pred.get('away', 0))}"
                                st.session_state[input_key] = default_value
                            else:
                                st.session_state[input_key] = ""
                        else:
                            # Jeśli klucz istnieje, NIE aktualizuj go z existing_predictions
                            # Pozwól użytkownikowi edytować wartość bez nadpisywania jej wartością z bazy
                            # Aktualizacja nastąpi dopiero po st.rerun(), gdy klucz zostanie usunięty i ponownie utworzony
                            current_value = st.session_state[input_key]
                            if has_existing:
                                existing_pred = existing_predictions[match_id]
                                expected_value = f"{safe_int(existing_pred.get('home', 0))}-{safe_int(existing_pred.get('away', 0))}"
                                # Nie aktualizuj wartości - pozwól użytkownikowi edytować
                            else:
                                # Jeśli nie ma typu w bazie, ale klucz istnieje i ma wartość, zachowaj ją (użytkownik może wprowadzać nowy typ)
                                pass
                        
                        # Pobierz existing_pred dla obliczenia punktów
                        existing_pred = existing_predictions.get(match_id) if has_existing else None
                        
                        # WAŻNE: Oblicz punkty TYLKO jeśli mecz ma wynik I jest zakończony (is_finished=1)
                        points_display = ""
                        match_is_finished = is_match_finished(match)
                        if match_is_finished and home_goals is not None and away_goals is not None and has_existing and existing_pred:
                            pred_home = existing_pred.get('home', 0)
                            pred_away = existing_pred.get('away', 0)
                            points = tipper.calculate_points((pred_home, pred_away), (safe_int(home_goals), safe_int(away_goals)))
                            points_display = f" | **Punkty: {points}**"
                        
                        league_name = get_league_name_for_match(storage, match, round_id)
                        league_info = f" _(Liga: {league_name})_"
                        
                        col1, col2 = st.columns([3, 1.5])
                        with col1:
                            status_icon = "✅" if has_existing else "❌"
                            result_text = f" ({safe_int(home_goals)}-{safe_int(away_goals)})" if home_goals is not None and away_goals is not None else ""
                            st.write(f"{status_icon} **{home_team}** vs **{away_team}**{league_info}{result_text} {points_display}")
                        with col2:
                            if can_edit:
                                    # Pole tekstowe - wartość jest już w session_state
                                    st.text_input(
                                    f"Typ:",
                                        key=input_key,
                                    label_visibility="collapsed",
                                        placeholder="0-0"
                                )
                            else:
                                if is_historical:
                                    st.info("⏰ Rozegrany")
                                else:
                                    st.warning("⏰ Rozpoczęty")
                    
                    # Przyciski do zapisania i usunięcia typów - w jednej linii (POZA pętlą meczów)
                    btn_col1, btn_col2 = st.columns(2)
                    
                    with btn_col1:
                        save_clicked = st.button("💾 Zapisz typy", type="primary", key=f"tipper_save_all_{player_name}", width="stretch")
                    
                    with btn_col2:
                        delete_clicked = st.button("🗑️ Usuń typy", key=f"tipper_delete_all_{player_name}", width="stretch")
                    
                    if save_clicked:
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
                            
                            # Filtruj typy, które można zapisać
                            valid_predictions = {}
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
                                    valid_predictions[match_id] = prediction
                                    if is_update:
                                        updated_count += 1
                                    else:
                                        saved_count += 1
                            
                            # Zapisz wszystkie typy naraz (batch insert - szybsze)
                            if valid_predictions:
                                try:
                                    log_to_file(f"save_clicked: start add_predictions_batch count={len(valid_predictions)} player={player_name} round={round_id}")
                                    logger.info(f"DEBUG save: zapisuję {len(valid_predictions)} typów dla gracza {player_name} w rundzie {round_id}")
                                    if hasattr(storage, 'add_predictions_batch'):
                                        storage.add_predictions_batch(round_id, player_name, valid_predictions)
                                    else:
                                        # Fallback dla JSON storage
                                        for match_id, prediction in valid_predictions.items():
                                            storage.add_prediction(round_id, player_name, match_id, prediction)
                                    log_to_file("save_clicked: add_predictions_batch done")
                                except Exception as e:
                                    logger.exception(f"Błąd zapisu typów (single): {e}")
                                    log_to_file(f"save_clicked: EXCEPTION {e}")
                                    st.error(f"❌ Błąd zapisu typów: {e}")
                                    return
                            
                            total_saved = saved_count + updated_count
                            
                            if total_saved > 0:
                                # Zwiększ wersję danych, aby unieważnić cache
                                st.session_state['data_version'] = st.session_state.get('data_version', 0) + 1
                                # Zapisz zmiany (dla JSON storage)
                                if hasattr(storage, '_save_data'):
                                    storage._save_data()
                                
                                # Usuń klucze z session_state, aby pola tekstowe zostały ponownie zainicjalizowane z wartościami z bazy
                                # Streamlit text_input zachowuje wartość w session_state po rerun, więc musimy je usunąć
                                keys_to_remove = []
                                for match in selected_matches:
                                    match_id = str(match.get('match_id', ''))
                                    input_key = f"tipper_pred_{player_name}_{match_id}"
                                    if input_key in st.session_state:
                                        keys_to_remove.append(input_key)
                                
                                # Usuń klucze po zakończeniu iteracji (aby uniknąć modyfikacji podczas iteracji)
                                for key in keys_to_remove:
                                    del st.session_state[key]
                                
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
                        
                        if delete_clicked:
                            # Sprawdź czy są typy do usunięcia
                            if existing_predictions:
                                # Usuń wszystkie typy dla tego gracza w tej rundzie
                                deleted_count = 0
                                
                                for match_id in existing_predictions.keys():
                                    # Sprawdź czy mecz można edytować
                                    match = next((m for m in selected_matches if str(m.get('match_id')) == match_id), None)
                                    can_delete = True
                                    
                                    if match:
                                        match_date = match.get('match_date')
                                        if match_date:
                                            try:
                                                match_dt = datetime.strptime(match_date, "%Y-%m-%d %H:%M:%S")
                                                if datetime.now() >= match_dt:
                                                    can_delete = allow_historical
                                            except:
                                                pass
                                    
                                    if can_delete:
                                        # Usuń typ z storage
                                        try:
                                            # Dla MySQL storage - usuń z bazy
                                            if hasattr(storage, 'conn'):
                                                storage.conn.query(
                                                    f"DELETE FROM predictions WHERE round_id = '{round_id}' AND player_name = '{player_name}' AND match_id = '{match_id}'",
                                                    ttl=0
                                                )
                                                storage.conn.query(
                                                    f"DELETE FROM match_points WHERE round_id = '{round_id}' AND player_name = '{player_name}' AND match_id = '{match_id}'",
                                                    ttl=0
                                                )
                                                # Przelicz całkowite punkty gracza
                                                if hasattr(storage, '_recalculate_player_totals'):
                                                    storage._recalculate_player_totals()
                                                deleted_count += 1
                                            # Dla JSON storage - usuń z danych
                                            elif hasattr(storage, 'data') and isinstance(storage.data, dict):
                                                if round_id in storage.data.get('rounds', {}):
                                                    if 'predictions' in storage.data['rounds'][round_id]:
                                                        if player_name in storage.data['rounds'][round_id]['predictions']:
                                                            if match_id in storage.data['rounds'][round_id]['predictions'][player_name]:
                                                                del storage.data['rounds'][round_id]['predictions'][player_name][match_id]
                                                                deleted_count += 1
                                                                # Usuń również z gracza
                                                                if round_id in storage.data['players'][player_name].get('predictions', {}):
                                                                    if match_id in storage.data['players'][player_name]['predictions'][round_id]:
                                                                        del storage.data['players'][player_name]['predictions'][round_id][match_id]
                                                                # Usuń również punkty
                                                                if 'match_points' in storage.data['rounds'][round_id]:
                                                                    if player_name in storage.data['rounds'][round_id]['match_points']:
                                                                        if match_id in storage.data['rounds'][round_id]['match_points'][player_name]:
                                                                            del storage.data['rounds'][round_id]['match_points'][player_name][match_id]
                                            
                                            # Dla MySQL storage - usuń z bazy
                                            if hasattr(storage, 'conn'):
                                                try:
                                                    query = f"DELETE FROM predictions WHERE round_id = '{round_id}' AND player_name = '{player_name}' AND match_id = '{match_id}'"
                                                    storage.conn.query(query, ttl=0)
                                                    # Usuń również punkty
                                                    query_points = f"DELETE FROM match_points WHERE round_id = '{round_id}' AND player_name = '{player_name}' AND match_id = '{match_id}'"
                                                    storage.conn.query(query_points, ttl=0)
                                                    deleted_count += 1
                                                except Exception as e:
                                                    logger.error(f"Błąd usuwania typu z MySQL: {e}")
                                        except Exception as e:
                                            logger.error(f"Błąd usuwania typu: {e}")
                                
                                if deleted_count > 0:
                                    # Zapisz zmiany
                                    if hasattr(storage, '_save_data'):
                                        storage._save_data()
                                    st.success(f"✅ Usunięto {deleted_count} typów")
                                    # Usuń klucze z session_state (zamiast modyfikować, co powoduje błąd)
                                    # Po rerun widgety będą miały puste wartości domyślne
                                    keys_to_remove = []
                                    for match in selected_matches:
                                        match_id = str(match.get('match_id', ''))
                                        input_key = f"tipper_pred_{player_name}_{match_id}"
                                        if input_key in st.session_state:
                                            keys_to_remove.append(input_key)
                                    
                                    # Usuń klucze po zakończeniu iteracji (aby uniknąć modyfikacji podczas iteracji)
                                    for key in keys_to_remove:
                                        del st.session_state[key]
                                    
                                    st.rerun()
                                else:
                                    st.warning("⚠️ Nie można usunąć typów - mecze już rozpoczęte")
                            else:
                                st.info("ℹ️ Brak typów do usunięcia")
                
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
                        
                        # Przycisk bulk w tej samej linii co przyciski z lewej kolumny
                        bulk_save_clicked = st.button("💾 Zapisz typy (bulk)", type="primary", key=f"tipper_bulk_save_{player_name}", width="stretch")
                        
                        if bulk_save_clicked:
                            if not predictions_text:
                                st.warning("⚠️ Wprowadź typy")
                            else:
                                # Parsuj typy z dopasowaniem do meczów
                                parsed = tipper.parse_match_predictions(predictions_text, selected_matches)
                                
                                if parsed:
                                    saved_count = 0
                                    updated_count = 0
                                    errors = []
                                    
                                    # Filtruj typy, które można zapisać
                                    valid_predictions = {}
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
                                                valid_predictions[match_id] = prediction
                                                if is_update:
                                                    updated_count += 1
                                                else:
                                                    saved_count += 1
                                        else:
                                            errors.append(f"Nie znaleziono meczu dla ID: {match_id}")
                                
                                    # Zapisz wszystkie typy naraz (batch insert - szybsze)
                                    if valid_predictions:
                                        try:
                                            log_to_file(f"bulk_save: start add_predictions_batch count={len(valid_predictions)} player={player_name} round={round_id}")
                                            logger.info(f"DEBUG bulk-save: zapisuję {len(valid_predictions)} typów dla gracza {player_name} w rundzie {round_id}")
                                            if hasattr(storage, 'add_predictions_batch'):
                                                storage.add_predictions_batch(round_id, player_name, valid_predictions)
                                            else:
                                                # Fallback dla JSON storage
                                                for match_id, prediction in valid_predictions.items():
                                                    storage.add_prediction(round_id, player_name, match_id, prediction)
                                            log_to_file("bulk_save: add_predictions_batch done")
                                        except Exception as e:
                                            logger.exception(f"Błąd zapisu typów (bulk): {e}")
                                            log_to_file(f"bulk_save: EXCEPTION {e}")
                                            st.error(f"❌ Błąd zapisu typów: {e}")
                                            return
                                    
                                    total_saved = saved_count + updated_count
                                    
                                    if total_saved > 0:
                                        # Zwiększ wersję danych, aby unieważnić cache
                                        st.session_state['data_version'] = st.session_state.get('data_version', 0) + 1
                                        # Zapisz zmiany (dla JSON storage)
                                        if hasattr(storage, '_save_data'):
                                            storage._save_data()
                                        
                                        # Usuń klucze z session_state, aby pola tekstowe zostały ponownie zainicjalizowane z wartościami z bazy
                                        # Streamlit text_input zachowuje wartość w session_state po rerun, więc musimy je usunąć
                                        keys_to_remove = []
                                        for match in selected_matches:
                                            match_id = str(match.get('match_id', ''))
                                            input_key = f"tipper_pred_{player_name}_{match_id}"
                                            if input_key in st.session_state:
                                                keys_to_remove.append(input_key)
                                        
                                        # Usuń klucze po zakończeniu iteracji (aby uniknąć modyfikacji podczas iteracji)
                                        for key in keys_to_remove:
                                            del st.session_state[key]
                                        
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

