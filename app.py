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
        
        # ID lig dla typera - dynamiczne dodawanie/usuwanie
        st.subheader("🏆 Ligi typera")
        
        # Storage już zainicjalizowany wcześniej (przy filtrze sezonu)
        
        # Pobierz aktualne ligi (lista ID)
        selected_league_ids = storage.get_selected_leagues()
        
        # Pobierz nazwy lig z API (jeśli są klucze OAuth)
        league_names_map = {}  # {league_id: league_name}
        
        if selected_league_ids:
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
            
            # Pobierz nazwy lig z API
            if all([consumer_key, consumer_secret, access_token, access_token_secret]):
                try:
                    client = HattrickOAuthSimple(consumer_key, consumer_secret)
                    client.set_access_tokens(access_token, access_token_secret)
                    
                    for league_id in selected_league_ids:
                        try:
                            league_details = client.get_league_details(league_id)
                            if league_details and league_details.get('league_name'):
                                league_names_map[league_id] = league_details['league_name']
                            else:
                                league_names_map[league_id] = f"Liga {league_id}"
                        except Exception as e:
                            logger.error(f"Błąd pobierania nazwy ligi {league_id} z API: {e}")
                            league_names_map[league_id] = f"Liga {league_id}"
                except Exception as e:
                    logger.error(f"Błąd inicjalizacji klienta OAuth: {e}")
                    # Użyj domyślnych nazw
                    for league_id in selected_league_ids:
                        league_names_map[league_id] = f"Liga {league_id}"
            else:
                # Użyj domyślnych nazw jeśli brak OAuth
                for league_id in selected_league_ids:
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
                        selected_league_ids.remove(league_id)
                        storage.set_selected_leagues(selected_league_ids)
                        st.success(f"✅ Usunięto ligę {league_name}")
                        st.rerun()
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
            fetch_name_clicked = st.button("🔍 Pobierz nazwę z API", key="fetch_league_name", use_container_width=True)
        
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
            if st.button("➕ Dodaj ligę", type="primary", use_container_width=True):
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
                    
                    # Dodaj tylko ID ligi (nie zapisujemy nazwy)
                    selected_league_ids.append(new_league_id)
                    storage.set_selected_leagues(selected_league_ids)
                    st.success(f"✅ Dodano ligę: {final_league_name} (ID: {new_league_id})")
                    st.rerun()
                else:
                    st.warning(f"⚠️ Liga o ID {new_league_id} już istnieje")
        
        with col_add2:
            if st.button("🔄 Odśwież dane", use_container_width=True):
                st.cache_data.clear()
                st.rerun()
        
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
        
        # Pobierz nazwy lig z API dla wszystkich zapisanych ID (jeśli jeszcze nie pobrano w sekcji konfiguracji)
        # league_names_map powinna być już wypełniona z sekcji konfiguracji, ale uzupełnij jeśli brakuje
        if 'league_names_map' not in st.session_state or not st.session_state.get('league_names_map'):
            league_names_map = {}
            for league_id in TIPPER_LEAGUES:
                try:
                    league_details = client.get_league_details(league_id)
                    if league_details and league_details.get('league_name'):
                        league_names_map[league_id] = league_details['league_name']
                    else:
                        league_names_map[league_id] = f"Liga {league_id}"
                except Exception as e:
                    logger.error(f"Błąd pobierania nazwy ligi {league_id} z API: {e}")
                    league_names_map[league_id] = f"Liga {league_id}"
            st.session_state.league_names_map = league_names_map
        else:
            league_names_map = st.session_state.league_names_map
        
        # Pobierz mecze z obu lig wraz z informacją o sezonie
        all_fixtures = []
        current_season = None
        with st.spinner("Pobieranie meczów z lig..."):
            for league_id in TIPPER_LEAGUES:
                try:
                    league_data = client.get_league_fixtures(league_id)
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
        
        if not all_fixtures:
            st.error("❌ Nie udało się pobrać meczów z API")
            return
        
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
        
        # Pobierz wszystkie unikalne nazwy drużyn z meczów wraz z informacją o lidze
        # Słownik: {team_name: league_name}
        teams_with_leagues = {}
        for _, matches in sorted_rounds_asc:
            for match in matches:
                home_team = match.get('home_team_name', '').strip()
                away_team = match.get('away_team_name', '').strip()
                match_league_id = match.get('league_id')
                # Pobierz nazwę ligi z league_names_map (pobrane z API)
                league_name = league_names_map.get(match_league_id, f"Liga {match_league_id}" if match_league_id else "?")
                
                if home_team:
                    teams_with_leagues[home_team] = league_name
                if away_team:
                    teams_with_leagues[away_team] = league_name
        
        all_team_names = sorted(list(teams_with_leagues.keys()))
        
        # Przeładuj dane z pliku (aby mieć aktualne dane po restarcie)
        storage.reload_data()
        
        # Pobierz zapisane ustawienia
        selected_teams = storage.get_selected_teams()
        logger.info(f"DEBUG: Pobrano z bazy selected_teams: {len(selected_teams) if selected_teams else 0} drużyn")
        
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
        
        # Jeśli nie ma zapisanych ustawień LUB wybrane drużyny nie zawierają żadnej drużyny z meczów z API
        # wybierz wszystkie drużyny z API i zapisz je w bazie
        if not selected_teams:
            logger.info(f"DEBUG: Brak zapisanych drużyn w bazie, wybieram wszystkie drużyny z API ({len(teams_in_matches)} drużyn)")
            selected_teams = sorted(list(teams_in_matches))
            # Zapisz nowy wybór drużyn w bazie
            storage.set_selected_teams(selected_teams)
            logger.info(f"DEBUG: Zapisano {len(selected_teams)} drużyn w bazie")
        elif not any(team in teams_in_matches for team in selected_teams):
            logger.warning(f"DEBUG: Wybrane drużyny ({len(selected_teams)}) nie zawierają żadnej drużyny z meczów z API ({len(teams_in_matches)}). Automatycznie wybieram wszystkie drużyny z API.")
            logger.warning(f"DEBUG: Przykładowe wybrane drużyny: {selected_teams[:5]}")
            logger.warning(f"DEBUG: Przykładowe drużyny z API: {list(teams_in_matches)[:5]}")
            selected_teams = sorted(list(teams_in_matches))
            # Zapisz nowy wybór drużyn w bazie
            storage.set_selected_teams(selected_teams)
            logger.info(f"DEBUG: Zapisano {len(selected_teams)} drużyn w bazie")
        
        logger.info(f"DEBUG: Końcowe wybrane drużyny ({len(selected_teams)}): {selected_teams[:5]}...")
        
        # Wybór drużyn do typowania - w sidebarze
        with st.sidebar:
            st.markdown("---")
            st.subheader("⚙️ Wybór drużyn do typowania")
            st.markdown("*Zaznacz drużyny, które chcesz uwzględnić w typerze*")
            
            # Użyj checkboxów dla wyboru drużyn (z informacją o lidze)
            new_selected_teams = []
            
            for team_name in all_team_names:
                league_name = teams_with_leagues.get(team_name, "?")
                team_label = f"{team_name} _(Liga: {league_name})_"
                if st.checkbox(team_label, value=team_name in selected_teams, key=f"team_select_{team_name}"):
                    new_selected_teams.append(team_name)
            
            # Przycisk zapisu ustawień
            if st.button("💾 Zapisz wybór drużyn", type="primary", use_container_width=True):
                storage.set_selected_teams(new_selected_teams)
                st.success(f"✅ Zapisano wybór {len(new_selected_teams)} drużyn")
                st.rerun()
            
            # Użyj aktualnie wybranych drużyn
            # Jeśli użytkownik nie zaznaczył żadnych drużyn, użyj zapisanych z bazy
            # (nie nadpisuj pustą listą, bo wtedy wszystkie mecze będą wyświetlane)
            if new_selected_teams:
                selected_teams = new_selected_teams
            # Jeśli new_selected_teams jest puste, zostaw selected_teams bez zmian (zapisane z bazy)
        
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
                    # Użyj wybranego sezonu z filtra
                    selected_season_id = st.session_state.get('selected_season_id', season_id)
                    storage.add_round(selected_season_id, round_id, selected_matches, selected_round_date)
                
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
                                pred_home = safe_int(pred.get('home', 0))
                                pred_away = safe_int(pred.get('away', 0))
                                
                                # Pobierz punkty dla tego meczu
                                match_points_dict = round_data.get('match_points', {}).get(player_name, {})
                                points = match_points_dict.get(match_id, 0)
                                
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
                # Użyj wybranego sezonu z filtra
                selected_season_id = st.session_state.get('selected_season_id', season_id)
                storage.add_round(selected_season_id, round_id, selected_matches, selected_round_date)
            
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
                if home_goals is not None and away_goals is not None:
                    status = f"✅ {safe_int(home_goals)}-{safe_int(away_goals)}"
                    # Aktualizuj wynik w storage
                    try:
                        storage.update_match_result(round_id, match_id, safe_int(home_goals), safe_int(away_goals))
                    except:
                        pass
                else:
                    try:
                        match_dt = datetime.strptime(match_date, "%Y-%m-%d %H:%M:%S")
                        if datetime.now() >= match_dt:
                            status = "⏰ Rozpoczęty"
                    except:
                        pass
                
                # Pobierz ID ligi dla meczu
                match_league_id = match.get('league_id', '?')
                # Pobierz nazwę ligi z league_names_map (pobrane z API)
                if match_league_id != '?':
                    league_name = league_names_map.get(match_league_id, f"Liga {match_league_id}")
                    league_info = f" (Liga: {league_name})"
                else:
                    league_info = ""
                
                matches_table_data.append({
                    'Gospodarz': f"{home_team}{league_info}",
                    'Gość': f"{away_team}{league_info}",
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
                                default_value = f"{safe_int(existing_pred.get('home', 0))}-{safe_int(existing_pred.get('away', 0))}"
                            else:
                                default_value = ""
                            
                            # Oblicz punkty jeśli mecz rozegrany
                            points_display = ""
                            if home_goals is not None and away_goals is not None and has_existing:
                                pred_home = existing_pred.get('home', 0)
                                pred_away = existing_pred.get('away', 0)
                                points = tipper.calculate_points((pred_home, pred_away), (safe_int(home_goals), safe_int(away_goals)))
                                points_display = f" | **Punkty: {points}**"
                            
                            # Pobierz ID ligi dla meczu
                            match_league_id = match.get('league_id', '?')
                            # Pobierz nazwę ligi z league_names_map (pobrane z API)
                            if match_league_id != '?':
                                league_name = league_names_map.get(match_league_id, f"Liga {match_league_id}")
                                league_info = f" _(Liga: {league_name})_"
                            else:
                                league_info = ""
                            
                            col1, col2 = st.columns([3, 1.5])
                            with col1:
                                status_icon = "✅" if has_existing else "❌"
                                result_text = f" ({safe_int(home_goals)}-{safe_int(away_goals)})" if home_goals is not None and away_goals is not None else ""
                                st.write(f"{status_icon} **{home_team}** vs **{away_team}**{league_info}{result_text} {points_display}")
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
                        
                        # Przyciski do zapisania i usunięcia typów - w jednej linii
                        btn_col1, btn_col2 = st.columns(2)
                        
                        with btn_col1:
                            save_clicked = st.button("💾 Zapisz typy", type="primary", key=f"tipper_save_all_{player_name}", use_container_width=True)
                        
                        with btn_col2:
                            delete_clicked = st.button("🗑️ Usuń typy", key=f"tipper_delete_all_{player_name}", use_container_width=True)
                        
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
                                        # Zapisz zmiany (dla JSON storage)
                                        if hasattr(storage, '_save_data'):
                                            storage._save_data()
                                        
                                        # Dla MySQL storage - upewnij się, że dane są zapisane przed przeładowaniem
                                        import time
                                        if hasattr(storage, 'conn'):
                                            # Sprawdź, czy dane są zapisane - poczekaj maksymalnie 1 sekundę
                                            max_attempts = 10
                                            for attempt in range(max_attempts):
                                                time.sleep(0.1)  # 100ms opóźnienie między próbami
                                                # Sprawdź, czy zapisane typy są dostępne w bazie
                                                try:
                                                    test_predictions = storage.get_player_predictions(player_name, round_id)
                                                    # Sprawdź, czy wszystkie zapisane typy są dostępne
                                                    saved_match_ids = set(predictions_to_save.keys())
                                                    available_match_ids = set(test_predictions.keys())
                                                    if saved_match_ids.issubset(available_match_ids):
                                                        # Wszystkie typy są dostępne - można przeładować
                                                        logger.info(f"DEBUG: Wszystkie {len(saved_match_ids)} typów są dostępne w bazie po {attempt + 1} próbach")
                                                        break
                                                except Exception as e:
                                                    logger.error(f"Błąd weryfikacji zapisanych typów: {e}")
                                                    pass
                                        
                                        # Wymuś przeładowanie danych z bazy przed rerun, aby existing_predictions było dostępne
                                        # add_prediction czyści cache po każdym typie, więc cache jest pusty
                                        # Przed rerun musimy przeładować dane, aby pola tekstowe miały poprawne wartości domyślne
                                        if hasattr(storage, 'reload_data'):
                                            storage.reload_data()
                                        
                                        # Usuń klucze z session_state, aby pola tekstowe zostały ponownie zainicjalizowane z wartościami z bazy
                                        # Streamlit text_input zachowuje wartość w session_state po rerun, więc musimy je usunąć
                                        # Po rerun() pola tekstowe będą inicjalizowane z existing_predictions, które są pobierane po przeładowaniu danych
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
                                            # Dla JSON storage - usuń z danych
                                            if hasattr(storage, 'data') and isinstance(storage.data, dict):
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
                                    # Wyczyść cache jeśli istnieje
                                    if hasattr(storage, 'reload_data'):
                                        storage.reload_data()
                                    
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
                        bulk_save_clicked = st.button("💾 Zapisz typy (bulk)", type="primary", key=f"tipper_bulk_save_{player_name}", use_container_width=True)
                        
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
                                        # Zapisz zmiany (dla JSON storage)
                                        if hasattr(storage, '_save_data'):
                                            storage._save_data()
                                        
                                        # Dla MySQL storage - upewnij się, że dane są zapisane przed przeładowaniem
                                        import time
                                        if hasattr(storage, 'conn'):
                                            # Sprawdź, czy dane są zapisane - poczekaj maksymalnie 1 sekundę
                                            max_attempts = 10
                                            for attempt in range(max_attempts):
                                                time.sleep(0.1)  # 100ms opóźnienie między próbami
                                                # Sprawdź, czy zapisane typy są dostępne w bazie
                                                try:
                                                    test_predictions = storage.get_player_predictions(player_name, round_id)
                                                    # Sprawdź, czy wszystkie zapisane typy są dostępne
                                                    saved_match_ids = set(parsed.keys())
                                                    available_match_ids = set(test_predictions.keys())
                                                    if saved_match_ids.issubset(available_match_ids):
                                                        # Wszystkie typy są dostępne - można przeładować
                                                        logger.info(f"DEBUG: Wszystkie {len(saved_match_ids)} typów są dostępne w bazie po {attempt + 1} próbach")
                                                        break
                                                except Exception as e:
                                                    logger.error(f"Błąd weryfikacji zapisanych typów: {e}")
                                                    pass
                                        
                                        # Wymuś przeładowanie danych z bazy przed rerun, aby existing_predictions było dostępne
                                        # add_prediction czyści cache po każdym typie, więc cache jest pusty
                                        # Przed rerun musimy przeładować dane, aby pola tekstowe miały poprawne wartości domyślne
                                        if hasattr(storage, 'reload_data'):
                                            storage.reload_data()
                                        
                                        # Usuń klucze z session_state, aby pola tekstowe zostały ponownie zainicjalizowane z wartościami z bazy
                                        # Streamlit text_input zachowuje wartość w session_state po rerun, więc musimy je usunąć
                                        # Po rerun() pola tekstowe będą inicjalizowane z existing_predictions, które są pobierane po przeładowaniu danych
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

