"""
Moduł przechowywania danych typera w bazie MySQL
"""
import json
import os
import logging
from typing import Dict, List, Optional
from datetime import datetime
import streamlit as st
from concurrent.futures import ThreadPoolExecutor, as_completed

logger = logging.getLogger(__name__)


class TipperStorageMySQL:
    """Klasa do przechowywania i zarządzania danymi typera w MySQL"""
    
    # Cache w pamięci (współdzielony między instancjami)
    _memory_cache = None
    _cache_timestamp = None
    _cache_ttl = 300  # Cache ważny przez 300 sekund (5 minut) - zwiększone dla lepszej wydajności na serwerze
    
    def __init__(self):
        """Inicjalizuje połączenie z bazą MySQL (używa współdzielonego połączenia z session_state)"""
        # Użyj współdzielonego połączenia z session_state, aby uniknąć przekroczenia limitu połączeń
        connection_key = 'mysql_connection_wrapper'
        connection_raw_key = 'mysql_connection_raw'
        mysql_config_key = 'mysql_config'
        
        # Sprawdź czy mamy już połączenie w session_state
        if connection_key in st.session_state and connection_raw_key in st.session_state:
            try:
                # Sprawdź czy połączenie jest jeszcze aktywne
                test_conn = st.session_state[connection_key]
                raw_conn = st.session_state[connection_raw_key]
                
                if hasattr(test_conn, 'conn') and raw_conn:
                    # Sprawdź czy połączenie jest otwarte (bez wykonywania zapytania)
                    try:
                        # Sprawdź czy połączenie jest otwarte
                        if raw_conn.open:
                            # Spróbuj wykonać proste zapytanie ping, aby sprawdzić czy połączenie działa
                            raw_conn.ping(reconnect=False)
                            logger.info("DEBUG: Używam istniejącego połączenia MySQL z session_state")
                            self.conn = test_conn
                            self._init_database()
                            return
                        else:
                            # Połączenie zamknięte - zamknij i usuń z session_state
                            logger.info("DEBUG: Istniejące połączenie MySQL jest zamknięte, zamykam i tworzę nowe")
                            try:
                                raw_conn.close()
                            except:
                                pass
                            if connection_key in st.session_state:
                                del st.session_state[connection_key]
                            if connection_raw_key in st.session_state:
                                del st.session_state[connection_raw_key]
                    except Exception as ping_error:
                        # Połączenie nie działa (ping nie powiódł się) - zamknij i usuń z session_state
                        logger.info(f"DEBUG: Istniejące połączenie MySQL nie działa (ping failed: {ping_error}), zamykam i tworzę nowe")
                        try:
                            raw_conn.close()
                        except:
                            pass
                        if connection_key in st.session_state:
                            del st.session_state[connection_key]
                        if connection_raw_key in st.session_state:
                            del st.session_state[connection_raw_key]
                else:
                    # Brak prawidłowego połączenia
                    logger.info("DEBUG: Istniejące połączenie MySQL nie ma prawidłowej struktury, tworzę nowe")
                    if connection_key in st.session_state:
                        del st.session_state[connection_key]
                    if connection_raw_key in st.session_state:
                        del st.session_state[connection_raw_key]
            except Exception as e:
                logger.info(f"DEBUG: Błąd sprawdzania istniejącego połączenia: {e}")
                if connection_key in st.session_state:
                    del st.session_state[connection_key]
                if connection_raw_key in st.session_state:
                    try:
                        st.session_state[connection_raw_key].close()
                    except:
                        pass
                    del st.session_state[connection_raw_key]
        
        # Najpierw spróbuj odczytać z płaskich zmiennych (MYSQL_HOST, MYSQL_PORT, itd.)
        mysql_config = None
        
        try:
            # Metoda 1: Płaskie zmienne w st.secrets (MYSQL_HOST, MYSQL_PORT, itd.)
            if hasattr(st, 'secrets'):
                try:
                    mysql_host = getattr(st.secrets, 'MYSQL_HOST', None)
                    mysql_port = getattr(st.secrets, 'MYSQL_PORT', None)
                    mysql_database = getattr(st.secrets, 'MYSQL_DATABASE', None)
                    mysql_username = getattr(st.secrets, 'MYSQL_USERNAME', None)
                    mysql_password = getattr(st.secrets, 'MYSQL_PASSWORD', None)
                    
                    if all([mysql_host, mysql_database, mysql_username, mysql_password]):
                        mysql_config = {
                            'host': mysql_host,
                            'port': int(mysql_port) if mysql_port else 3306,
                            'database': mysql_database,
                            'username': mysql_username,
                            'password': mysql_password
                        }
                        logger.info("DEBUG: MySQL config odczytany z płaskich zmiennych w st.secrets")
                except Exception as e:
                    logger.info(f"DEBUG: Błąd odczytu MySQL z płaskich zmiennych: {e}")
            
            # Metoda 2: Sekcja [connections.mysql] (dla kompatybilności)
            if not mysql_config or not all(mysql_config.values()):
                try:
                    if hasattr(st, 'secrets') and hasattr(st.secrets, 'connections'):
                        mysql_obj = getattr(st.secrets.connections, 'mysql', None)
                        if mysql_obj:
                            mysql_config = {
                                'host': getattr(mysql_obj, 'host', None),
                                'port': getattr(mysql_obj, 'port', 3306),
                                'database': getattr(mysql_obj, 'database', None),
                                'username': getattr(mysql_obj, 'username', None),
                                'password': getattr(mysql_obj, 'password', None)
                            }
                            logger.info("DEBUG: MySQL config odczytany z sekcji [connections.mysql]")
                except Exception as e:
                    logger.info(f"DEBUG: Błąd odczytu MySQL z sekcji: {e}")
        except Exception as e:
            logger.info(f"DEBUG: Błąd przy próbie odczytu secrets: {e}")
        
        # Jeśli nie ma w secrets, spróbuj z pliku secrets.toml (lokalnie)
        if not mysql_config or not all(mysql_config.values()):
            try:
                import tomllib
                secrets_path = os.path.join('.streamlit', 'secrets.toml')
                if os.path.exists(secrets_path):
                    with open(secrets_path, 'rb') as f:
                        secrets = tomllib.load(f)
                    
                    # Najpierw płaskie zmienne
                    if 'MYSQL_HOST' in secrets:
                        mysql_config = {
                            'host': secrets.get('MYSQL_HOST'),
                            'port': int(secrets.get('MYSQL_PORT', 3306)),
                            'database': secrets.get('MYSQL_DATABASE'),
                            'username': secrets.get('MYSQL_USERNAME'),
                            'password': secrets.get('MYSQL_PASSWORD')
                        }
                        logger.info("DEBUG: MySQL config odczytany z płaskich zmiennych w secrets.toml")
                    # Potem sekcja [connections.mysql]
                    elif 'connections' in secrets and 'mysql' in secrets['connections']:
                        mysql_config = secrets['connections']['mysql']
                        logger.info("DEBUG: MySQL config odczytany z sekcji [connections.mysql] w secrets.toml")
            except Exception as e:
                logger.info(f"DEBUG: Błąd odczytu z pliku secrets.toml: {e}")
        
        # Jeśli mamy konfigurację, połącz bezpośrednio przez pymysql
        if mysql_config and all(mysql_config.values()):
            try:
                import pymysql
                # Loguj konfigurację (bez hasła)
                logger.info(f"DEBUG: Próba utworzenia nowego połączenia MySQL")
                logger.info(f"DEBUG: Host: {mysql_config['host']}, Port: {mysql_config['port']}, Database: {mysql_config['database']}, User: {mysql_config['username']}")
                
                # Sprawdź czy wszystkie wymagane wartości są niepuste
                if not mysql_config['host'] or not mysql_config['database'] or not mysql_config['username'] or not mysql_config['password']:
                    error_msg = "Brak wymaganych parametrów połączenia MySQL (host, database, username, password)"
                    logger.error(f"ERROR: {error_msg}")
                    raise ValueError(error_msg)
                
                # Połączenie z MySQL (pymysql z cryptography automatycznie obsługuje SSL dla Aiven)
                # Zgodnie z instrukcją Aiven: pymysql + cryptography obsługuje protokół MySQL 11 i SSL
                connection = pymysql.connect(
                    host=mysql_config['host'],
                    port=int(mysql_config['port']),
                    user=mysql_config['username'],
                    password=mysql_config['password'],
                    database=mysql_config['database'],
                    charset='utf8mb4',
                    cursorclass=pymysql.cursors.DictCursor,
                    autocommit=True,  # Włącz autocommit, aby uniknąć problemów z transakcjami
                    connect_timeout=10,  # Timeout połączenia (sekundy) - zgodnie z instrukcją Aiven
                    read_timeout=10,  # Timeout odczytu (sekundy) - zgodnie z instrukcją Aiven
                    write_timeout=10  # Timeout zapisu (sekundy) - zgodnie z instrukcją Aiven
                )
                
                # Użyj wrapper dla kompatybilności z st.connection
                class MySQLConnectionWrapper:
                    def __init__(self, conn, mysql_config):
                        self.conn = conn
                        self.mysql_config = mysql_config
                    
                    def _reconnect(self):
                        """Ponownie łączy się z bazą MySQL"""
                        import pymysql
                        try:
                            logger.info("DEBUG: Próba ponownego połączenia z MySQL")
                            # Zamknij stare połączenie
                            try:
                                if self.conn and hasattr(self.conn, 'close'):
                                    self.conn.close()
                            except:
                                pass
                            
                            # Pobierz konfigurację MySQL (z self.mysql_config lub z session_state)
                            mysql_config = self.mysql_config
                            if not mysql_config:
                                mysql_config_key = 'mysql_config'
                                if mysql_config_key in st.session_state:
                                    mysql_config = st.session_state[mysql_config_key]
                            
                            if not mysql_config:
                                logger.error("DEBUG: Brak konfiguracji MySQL do ponownego połączenia")
                                return False
                            
                            # Utwórz nowe połączenie (pymysql z cryptography automatycznie obsługuje SSL dla Aiven)
                            new_conn = pymysql.connect(
                                host=mysql_config['host'],
                                port=int(mysql_config['port']),
                                user=mysql_config['username'],
                                password=mysql_config['password'],
                                database=mysql_config['database'],
                                charset='utf8mb4',
                                cursorclass=pymysql.cursors.DictCursor,
                                autocommit=True,
                                connect_timeout=10,  # Zgodnie z instrukcją Aiven
                                read_timeout=10,  # Zgodnie z instrukcją Aiven
                                write_timeout=10  # Zgodnie z instrukcją Aiven
                            )
                            
                            self.conn = new_conn
                            # Zaktualizuj połączenie w session_state
                            connection_key = 'mysql_connection_wrapper'
                            connection_raw_key = 'mysql_connection_raw'
                            st.session_state[connection_key] = self
                            st.session_state[connection_raw_key] = new_conn
                            logger.info("DEBUG: Ponownie połączono z MySQL")
                            return True
                        except Exception as e:
                            logger.error(f"DEBUG: Błąd ponownego połączenia z MySQL: {e}")
                            import traceback
                            logger.error(f"Traceback: {traceback.format_exc()}")
                            return False
                    
                    def _check_connection(self):
                        """Sprawdza czy połączenie jest aktywne i ponownie łączy się jeśli potrzeba"""
                        try:
                            # Sprawdź czy połączenie jest otwarte
                            if not self.conn or not hasattr(self.conn, 'open') or not self.conn.open:
                                logger.warning("DEBUG: Połączenie MySQL jest zamknięte, próba ponownego połączenia")
                                return self._reconnect()
                            
                            # Sprawdź czy połączenie działa (ping)
                            try:
                                self.conn.ping(reconnect=False)
                                return True
                            except:
                                # Połączenie zerwane - spróbuj ponownie połączyć
                                logger.warning("DEBUG: Połączenie MySQL nie odpowiada na ping, próba ponownego połączenia")
                                return self._reconnect()
                        except Exception as e:
                            logger.error(f"DEBUG: Błąd sprawdzania połączenia MySQL: {e}")
                            return self._reconnect()
                    
                    def query(self, sql, ttl=600):
                        import pandas as pd
                        import pymysql
                        
                        # Sprawdź połączenie przed zapytaniem
                        if not self._check_connection():
                            logger.error("DEBUG: Nie można połączyć się z MySQL, zwracam pusty DataFrame")
                            return pd.DataFrame()
                        
                        try:
                            with self.conn.cursor() as cursor:
                                cursor.execute(sql)
                                results = cursor.fetchall()
                                if results:
                                    return pd.DataFrame(results)
                                return pd.DataFrame()
                        except (pymysql.err.InterfaceError, pymysql.err.OperationalError) as e:
                            # Połączenie zerwane - spróbuj ponownie połączyć i wykonać zapytanie
                            logger.warning(f"DEBUG: Błąd połączenia MySQL ({type(e).__name__}): {e}, próba ponownego połączenia")
                            if self._reconnect():
                                try:
                                    # Spróbuj ponownie wykonać zapytanie
                                    with self.conn.cursor() as cursor:
                                        cursor.execute(sql)
                                        results = cursor.fetchall()
                                        if results:
                                            return pd.DataFrame(results)
                                        return pd.DataFrame()
                                except Exception as e2:
                                    logger.error(f"Błąd zapytania SQL po ponownym połączeniu: {e2}")
                                    logger.error(f"SQL: {sql[:200]}...")
                                    return pd.DataFrame()
                            else:
                                logger.error(f"Błąd zapytania SQL (nie można ponownie połączyć): {e}")
                                logger.error(f"SQL: {sql[:200]}...")
                                return pd.DataFrame()
                        except Exception as e:
                            logger.error(f"Błąd zapytania SQL: {e}")
                            logger.error(f"SQL: {sql[:200]}...")  # Loguj pierwsze 200 znaków SQL
                            import traceback
                            logger.error(f"Traceback: {traceback.format_exc()}")
                            # Zwróć pusty DataFrame zamiast rzucać wyjątek
                            return pd.DataFrame()
                
                # Zapisz połączenie w session_state, aby było współdzielone
                wrapper = MySQLConnectionWrapper(connection, mysql_config)
                st.session_state[connection_key] = wrapper
                st.session_state[connection_raw_key] = connection  # Zapisz również surowe połączenie do sprawdzania
                self.conn = wrapper
                self._init_database()
                logger.info(f"Połączono z bazą MySQL (bezpośrednio przez pymysql, współdzielone połączenie). Session ID: {id(st.session_state)}")
            except pymysql.err.OperationalError as e:
                # pymysql.err.OperationalError może mieć różne formaty
                if len(e.args) >= 2:
                    error_code, error_message = e.args[0], e.args[1]
                elif len(e.args) == 1:
                    error_code = 0
                    error_message = str(e.args[0])
                else:
                    error_code = 0
                    error_message = str(e)
                
                logger.error(f"Błąd operacyjny MySQL (kod: {error_code}): {error_message}")
                logger.error(f"Host: {mysql_config.get('host', 'N/A')}, Port: {mysql_config.get('port', 'N/A')}, Database: {mysql_config.get('database', 'N/A')}, User: {mysql_config.get('username', 'N/A')}")
                import traceback
                logger.error(f"Traceback: {traceback.format_exc()}")
                # Rzuć bardziej szczegółowy błąd
                if error_code:
                    raise pymysql.err.OperationalError(error_code, f"Błąd połączenia z MySQL: {error_message}. Sprawdź konfigurację w Streamlit Secrets.")
                else:
                    raise pymysql.err.OperationalError(0, f"Błąd połączenia z MySQL: {error_message}. Sprawdź konfigurację w Streamlit Secrets.")
            except Exception as e:
                logger.error(f"Błąd połączenia z MySQL: {type(e).__name__}: {e}")
                logger.error(f"Host: {mysql_config.get('host', 'N/A')}, Port: {mysql_config.get('port', 'N/A')}, Database: {mysql_config.get('database', 'N/A')}, User: {mysql_config.get('username', 'N/A')}")
                import traceback
                logger.error(f"Traceback: {traceback.format_exc()}")
                raise
        else:
            # Fallback: spróbuj st.connection (ma wbudowany pooling)
            try:
                logger.info("DEBUG: Brak konfiguracji MySQL w secrets, próba utworzenia połączenia przez st.connection('mysql')")
                logger.warning("DEBUG: MySQL config nie znaleziony. Sprawdź Streamlit Secrets:")
                logger.warning("DEBUG: Wymagane zmienne: MYSQL_HOST, MYSQL_PORT, MYSQL_DATABASE, MYSQL_USERNAME, MYSQL_PASSWORD")
                logger.warning("DEBUG: LUB sekcja [connections.mysql] z polami: host, port, database, username, password")
                self.conn = st.connection('mysql', type='sql')
                logger.info("DEBUG: Połączenie MySQL utworzone przez st.connection()")
                self._init_database()
                logger.info("Połączono z bazą MySQL (przez st.connection)")
            except Exception as e:
                error_msg = f"Błąd połączenia z MySQL przez st.connection: {e}"
                logger.error(error_msg)
                logger.error("DEBUG: Sprawdź konfigurację MySQL w Streamlit Secrets")
                import traceback
                logger.error(f"Traceback: {traceback.format_exc()}")
                raise RuntimeError(f"{error_msg}. Sprawdź konfigurację MySQL w Streamlit Secrets.")
    
    def _init_database(self):
        """Inicjalizuje strukturę bazy danych (tworzy tabele jeśli nie istnieją)"""
        try:
            # Tabela graczy
            self.conn.query("""
                CREATE TABLE IF NOT EXISTS players (
                    player_name VARCHAR(255) PRIMARY KEY,
                    total_points INT DEFAULT 0,
                    rounds_played INT DEFAULT 0,
                    best_score INT DEFAULT 0,
                    worst_score INT DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
            """, ttl=0)
            
            # Tabela lig
            self.conn.query("""
                CREATE TABLE IF NOT EXISTS leagues (
                    league_id VARCHAR(50) PRIMARY KEY,
                    league_name VARCHAR(255),
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
            """, ttl=0)
            
            # Tabela sezonów
            self.conn.query("""
                CREATE TABLE IF NOT EXISTS seasons (
                    season_id VARCHAR(255) PRIMARY KEY,
                    league_id VARCHAR(50),
                    start_date VARCHAR(50),
                    end_date VARCHAR(50),
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (league_id) REFERENCES leagues(league_id) ON DELETE CASCADE
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
            """, ttl=0)
            
            # Tabela rund
            self.conn.query("""
                CREATE TABLE IF NOT EXISTS rounds (
                    round_id VARCHAR(255) PRIMARY KEY,
                    season_id VARCHAR(255),
                    start_date VARCHAR(50),
                    end_date VARCHAR(50),
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (season_id) REFERENCES seasons(season_id) ON DELETE CASCADE
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
            """, ttl=0)
            
            # Tabela meczów
            self.conn.query("""
                CREATE TABLE IF NOT EXISTS matches (
                    match_id VARCHAR(255),
                    round_id VARCHAR(255),
                    home_team_name VARCHAR(255),
                    away_team_name VARCHAR(255),
                    match_date VARCHAR(50),
                    home_goals INT,
                    away_goals INT,
                    league_id INT,
                    PRIMARY KEY (match_id, round_id),
                    FOREIGN KEY (round_id) REFERENCES rounds(round_id) ON DELETE CASCADE
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
            """, ttl=0)
            
            # Tabela typów (predictions)
            self.conn.query("""
                CREATE TABLE IF NOT EXISTS predictions (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    round_id VARCHAR(255),
                    player_name VARCHAR(255),
                    match_id VARCHAR(255),
                    home_goals INT,
                    away_goals INT,
                    timestamp VARCHAR(50),
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                    UNIQUE KEY unique_prediction (round_id, player_name, match_id),
                    INDEX idx_player_round (player_name, round_id),
                    INDEX idx_round (round_id),
                    INDEX idx_player (player_name),
                    FOREIGN KEY (round_id) REFERENCES rounds(round_id) ON DELETE CASCADE,
                    FOREIGN KEY (player_name) REFERENCES players(player_name) ON DELETE CASCADE
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
            """, ttl=0)
            
            # Tabela punktów za mecze
            self.conn.query("""
                CREATE TABLE IF NOT EXISTS match_points (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    round_id VARCHAR(255),
                    player_name VARCHAR(255),
                    match_id VARCHAR(255),
                    points INT DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                    UNIQUE KEY unique_match_points (round_id, player_name, match_id),
                    INDEX idx_player_round (player_name, round_id),
                    INDEX idx_round (round_id),
                    INDEX idx_player (player_name),
                    FOREIGN KEY (round_id) REFERENCES rounds(round_id) ON DELETE CASCADE,
                    FOREIGN KEY (player_name) REFERENCES players(player_name) ON DELETE CASCADE
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
            """, ttl=0)
            
            # Tabela ustawień
            self.conn.query("""
                CREATE TABLE IF NOT EXISTS settings (
                    setting_key VARCHAR(255) PRIMARY KEY,
                    setting_value TEXT,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
            """, ttl=0)
            
            logger.info("Struktura bazy danych zainicjalizowana")
        except Exception as e:
            logger.error(f"Błąd inicjalizacji bazy danych: {e}")
            raise
    
    @property
    def data(self) -> Dict:
        """Zwraca dane w formacie JSON (dla kompatybilności z TipperStorage)"""
        return self._load_data_cached()
    
    @data.setter
    def data(self, value: Dict):
        """Ustawia dane (dla importu) - automatycznie importuje do MySQL"""
        # Zapisz dane do importu
        self._pending_import_data = value
        # Automatycznie zaimportuj
        self._save_data()
    
    def _load_data_cached(self) -> Dict:
        """Ładuje dane z cache lub z bazy MySQL"""
        import time
        
        # Sprawdź cache w pamięci
        current_time = time.time()
        if (TipperStorageMySQL._memory_cache is not None and 
            TipperStorageMySQL._cache_timestamp is not None and
            (current_time - TipperStorageMySQL._cache_timestamp) < TipperStorageMySQL._cache_ttl):
            logger.info("DEBUG: Używam cache w pamięci (szybko)")
            # Sprawdź czy cache nie jest pusty (może być pusty po błędzie)
            if TipperStorageMySQL._memory_cache and len(TipperStorageMySQL._memory_cache.get('players', {})) > 0:
                return TipperStorageMySQL._memory_cache
            else:
                logger.warning("DEBUG: Cache jest pusty lub nieprawidłowy, przeładowuję z bazy")
        
        # Cache wygasł lub nie istnieje - załaduj z bazy
        logger.info("DEBUG: Ładuję dane z bazy MySQL (cache wygasł lub nie istnieje)")
        try:
            data = self._load_data()
            
            # Sprawdź czy dane nie są puste (może być błąd w _load_data)
            if not data or len(data.get('players', {})) == 0:
                logger.warning("DEBUG: _load_data() zwróciło puste dane, sprawdzam czy to błąd")
                # Spróbuj ponownie załadować dane (może być problem z połączeniem)
                import time
                time.sleep(0.1)  # Krótkie opóźnienie przed ponowną próbą
                data = self._load_data()
            
            # Zaktualizuj cache tylko jeśli dane nie są puste
            if data and len(data.get('players', {})) > 0:
                TipperStorageMySQL._memory_cache = data
                TipperStorageMySQL._cache_timestamp = current_time
                logger.info(f"DEBUG: Zaktualizowano cache - {len(data.get('players', {}))} graczy")
            else:
                logger.error("DEBUG: Nie można załadować danych z bazy - zwracam pusty słownik")
                # Jeśli cache był wcześniej wypełniony, zachowaj go (może być problem z połączeniem)
                if TipperStorageMySQL._memory_cache is not None:
                    logger.warning("DEBUG: Zachowuję stary cache, ponieważ nowe dane są puste")
                    return TipperStorageMySQL._memory_cache
            
            return data
        except Exception as e:
            logger.error(f"DEBUG: Błąd w _load_data_cached: {e}")
            # Jeśli cache był wcześniej wypełniony, zachowaj go (może być problem z połączeniem)
            if TipperStorageMySQL._memory_cache is not None:
                logger.warning("DEBUG: Błąd ładowania danych, zachowuję stary cache")
                return TipperStorageMySQL._memory_cache
            # Jeśli nie ma cache, zwróć pusty słownik
            return self._get_default_data()
    
    def _load_data(self) -> Dict:
        """Ładuje wszystkie dane z bazy MySQL do formatu JSON (bez cache) - zoptymalizowane z równoległymi zapytaniami"""
        try:
            logger.info("DEBUG: _load_data() - rozpoczynam ładowanie danych z MySQL")
            data = {
                'players': {},
                'rounds': {},
                'seasons': {},
                'leagues': {},
                'settings': {}
            }
            
            # Równoległe ładowanie głównych tabel (players, leagues, seasons, rounds, settings)
            def load_players():
                players_df = self.conn.query("SELECT * FROM players", ttl=0)
                logger.info(f"DEBUG: load_players() - znaleziono {len(players_df)} graczy w bazie")
                players_dict = {}
                for _, row in players_df.iterrows():
                    players_dict[row['player_name']] = {
                        'total_points': int(row['total_points']) if row['total_points'] else 0,
                        'rounds_played': int(row['rounds_played']) if row['rounds_played'] else 0,
                        'best_score': int(row['best_score']) if row['best_score'] else 0,
                        'worst_score': int(row['worst_score']) if row['worst_score'] else 0,
                        'predictions': {}
                    }
                logger.info(f"DEBUG: load_players() - zwracam {len(players_dict)} graczy")
                return players_dict
            
            def load_leagues():
                leagues_df = self.conn.query("SELECT * FROM leagues", ttl=0)
                leagues_dict = {}
                for _, row in leagues_df.iterrows():
                    leagues_dict[row['league_id']] = {
                        'name': row['league_name'],
                        'seasons': []
                    }
                return leagues_dict
            
            def load_seasons():
                seasons_df = self.conn.query("SELECT * FROM seasons", ttl=0)
                seasons_dict = {}
                for _, row in seasons_df.iterrows():
                    seasons_dict[row['season_id']] = {
                        'league_id': row['league_id'],
                        'rounds': [],
                        'start_date': row['start_date'],
                        'end_date': row['end_date']
                    }
                return seasons_dict
            
            def load_rounds():
                rounds_df = self.conn.query("SELECT * FROM rounds", ttl=0)
                rounds_dict = {}
                for _, row in rounds_df.iterrows():
                    rounds_dict[row['round_id']] = {
                        'season_id': row['season_id'],
                        'start_date': row['start_date'],
                        'end_date': row['end_date'],
                        'matches': [],
                        'predictions': {},
                        'match_points': {}
                    }
                return rounds_dict
            
            def load_settings():
                settings_df = self.conn.query("SELECT * FROM settings", ttl=0)
                settings_dict = {}
                for _, row in settings_df.iterrows():
                    key = row['setting_key']
                    value = row['setting_value']
                    try:
                        settings_dict[key] = json.loads(value)
                    except:
                        settings_dict[key] = value
                return settings_dict
            
            # Wykonaj zapytania sekwencyjnie (MySQL połączenie nie jest thread-safe)
            # TODO: Można użyć connection pool, ale na razie sekwencyjnie dla stabilności
            data['players'] = load_players()
            data['leagues'] = load_leagues()
            data['seasons'] = load_seasons()
            data['rounds'] = load_rounds()
            data['settings'] = load_settings()
            
            logger.info(f"DEBUG: _load_data() - załadowano: {len(data['players'])} graczy, {len(data['rounds'])} rund, {len(data['leagues'])} lig, {len(data['seasons'])} sezonów")
            
            # Teraz załaduj dane dla rund (mecze, typy, punkty) - batch queries zamiast pętli + równoległe ładowanie
            if data['rounds']:
                round_ids = list(data['rounds'].keys())
                round_ids_str = "', '".join(round_ids)
                
                def load_matches():
                    all_matches_df = self.conn.query(
                        f"SELECT * FROM matches WHERE round_id IN ('{round_ids_str}')", ttl=0
                    )
                    matches_dict = {}
                    for _, match_row in all_matches_df.iterrows():
                        round_id = match_row['round_id']
                        if round_id not in matches_dict:
                            matches_dict[round_id] = []
                        matches_dict[round_id].append({
                            'match_id': match_row['match_id'],
                            'home_team_name': match_row['home_team_name'],
                            'away_team_name': match_row['away_team_name'],
                            'match_date': match_row['match_date'],
                            'home_goals': match_row['home_goals'],
                            'away_goals': match_row['away_goals'],
                            'league_id': match_row['league_id']
                        })
                    return matches_dict
                
                def load_predictions():
                    logger.info(f"DEBUG: load_predictions() - szukam typów dla rund: {round_ids[:5]}... (pokazuję pierwsze 5)")
                    all_predictions_df = self.conn.query(
                        f"SELECT * FROM predictions WHERE round_id IN ('{round_ids_str}')", ttl=0
                    )
                    logger.info(f"DEBUG: load_predictions() - znaleziono {len(all_predictions_df)} typów w bazie")
                    predictions_dict = {}
                    for _, pred_row in all_predictions_df.iterrows():
                        round_id = pred_row['round_id']
                        player_name = pred_row['player_name']
                        match_id = pred_row['match_id']
                        
                        if round_id not in predictions_dict:
                            predictions_dict[round_id] = {}
                        if player_name not in predictions_dict[round_id]:
                            predictions_dict[round_id][player_name] = {}
                        predictions_dict[round_id][player_name][match_id] = {
                            'home': int(pred_row['home_goals']),
                            'away': int(pred_row['away_goals']),
                            'timestamp': pred_row['timestamp']
                        }
                    logger.info(f"DEBUG: load_predictions() - zwracam typy dla {len(predictions_dict)} rund")
                    return predictions_dict
                
                def load_match_points():
                    all_match_points_df = self.conn.query(
                        f"SELECT * FROM match_points WHERE round_id IN ('{round_ids_str}')", ttl=0
                    )
                    points_dict = {}
                    for _, points_row in all_match_points_df.iterrows():
                        round_id = points_row['round_id']
                        player_name = points_row['player_name']
                        match_id = points_row['match_id']
                        
                        if round_id not in points_dict:
                            points_dict[round_id] = {}
                        if player_name not in points_dict[round_id]:
                            points_dict[round_id][player_name] = {}
                        points_dict[round_id][player_name][match_id] = int(points_row['points'])
                    return points_dict
                
                # Wykonaj zapytania sekwencyjnie (MySQL połączenie nie jest thread-safe)
                matches_dict = load_matches()
                predictions_dict = load_predictions()
                points_dict = load_match_points()
                
                # Połącz dane z rundami
                logger.info(f"DEBUG: Łączę dane z rundami - {len(data['rounds'])} rund")
                for round_id in data['rounds']:
                    if round_id in matches_dict:
                        data['rounds'][round_id]['matches'] = matches_dict[round_id]
                        logger.info(f"DEBUG: Dodano {len(matches_dict[round_id])} meczów do rundy {round_id}")
                    if round_id in predictions_dict:
                        data['rounds'][round_id]['predictions'] = predictions_dict[round_id]
                        logger.info(f"DEBUG: Dodano typy dla {len(predictions_dict[round_id])} graczy do rundy {round_id}")
                        # Dodaj typy do graczy
                        for player_name, player_predictions in predictions_dict[round_id].items():
                            if player_name in data['players']:
                                if round_id not in data['players'][player_name]['predictions']:
                                    data['players'][player_name]['predictions'][round_id] = {}
                                # player_predictions to dict {match_id: {home, away, timestamp}}
                                for match_id, pred_data in player_predictions.items():
                                    data['players'][player_name]['predictions'][round_id][match_id] = pred_data
                                logger.info(f"DEBUG: Dodano {len(player_predictions)} typów dla gracza {player_name} w rundzie {round_id}")
                            else:
                                logger.warning(f"DEBUG: Gracz {player_name} nie istnieje w data['players']")
                    else:
                        logger.info(f"DEBUG: Brak typów dla rundy {round_id} w predictions_dict")
                    if round_id in points_dict:
                        data['rounds'][round_id]['match_points'] = points_dict[round_id]
                        logger.info(f"DEBUG: Dodano punkty dla {len(points_dict[round_id])} graczy do rundy {round_id}")
            
            logger.info(f"Załadowano dane z MySQL (zoptymalizowane): {len(data.get('players', {}))} graczy, {len(data.get('rounds', {}))} rund")
            return data
        except Exception as e:
            logger.error(f"Błąd ładowania danych z MySQL: {e}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            return self._get_default_data()
    
    def _get_default_data(self) -> Dict:
        """Zwraca domyślną strukturę danych"""
        return {
            'players': {},
            'rounds': {},
            'seasons': {},
            'leagues': {},
            'settings': {
                'selected_teams': []
            }
        }
    
    def reload_data(self):
        """Przeładowuje dane z bazy i czyści cache (dla kompatybilności)"""
        # Wyczyść cache, aby wymusić przeładowanie z bazy
        TipperStorageMySQL._memory_cache = None
        TipperStorageMySQL._cache_timestamp = None
        logger.info("Przeładowano dane z MySQL (cache wyczyszczony)")
    
    def _save_data(self):
        """Zapisuje dane do bazy (dla kompatybilności - dane są zapisywane na bieżąco)"""
        # W MySQL dane są zapisywane na bieżąco, więc ta metoda jest pusta
        # Ale jeśli self.data został ustawiony (import), to zaimportuj dane
        if hasattr(self, '_pending_import_data'):
            self._import_data_to_mysql(self._pending_import_data)
            delattr(self, '_pending_import_data')
            # Wyczyść cache po zapisie, aby wymusić przeładowanie
            TipperStorageMySQL._memory_cache = None
            TipperStorageMySQL._cache_timestamp = None
    
    def _import_data_to_mysql(self, data: Dict):
        """Importuje dane JSON do MySQL"""
        try:
            logger.info("Rozpoczynam import danych do MySQL...")
            
            # Import lig
            for league_id, league_data in data.get('leagues', {}).items():
                self.add_league(int(league_id) if league_id.isdigit() else 0, league_data.get('name'))
            
            # Import sezonów
            for season_id, season_data in data.get('seasons', {}).items():
                league_id = season_data.get('league_id')
                if league_id:
                    self.add_season(int(league_id) if str(league_id).isdigit() else 0, season_id, 
                                  season_data.get('start_date'), season_data.get('end_date'))
                else:
                    self.add_season(None, season_id, season_data.get('start_date'), season_data.get('end_date'))
            
            # Import rund i meczów
            for round_id, round_data in data.get('rounds', {}).items():
                season_id = round_data.get('season_id', 'current_season')
                matches = round_data.get('matches', [])
                start_date = round_data.get('start_date')
                
                # Dodaj rundę
                self.add_round(season_id, round_id, matches, start_date)
                
                # Import typów
                predictions = round_data.get('predictions', {})
                for player_name, player_predictions in predictions.items():
                    for match_id, pred_data in player_predictions.items():
                        prediction = (pred_data.get('home', 0), pred_data.get('away', 0))
                        self.add_prediction(round_id, player_name, str(match_id), prediction)
                
                # Import punktów za mecze
                match_points = round_data.get('match_points', {})
                for player_name, player_points in match_points.items():
                    for match_id, points in player_points.items():
                        self.conn.query(
                            f"INSERT INTO match_points (round_id, player_name, match_id, points) "
                            f"VALUES ('{round_id}', '{player_name}', '{match_id}', {points}) "
                            f"ON DUPLICATE KEY UPDATE points = {points}",
                            ttl=0
                        )
                
                # Aktualizuj wyniki meczów jeśli są
                for match in matches:
                    match_id = str(match.get('match_id', ''))
                    home_goals = match.get('home_goals')
                    away_goals = match.get('away_goals')
                    if home_goals is not None and away_goals is not None:
                        self.update_match_result(round_id, match_id, int(home_goals), int(away_goals))
            
            # Import ustawień
            settings = data.get('settings', {})
            for key, value in settings.items():
                if isinstance(value, (list, dict)):
                    value_str = json.dumps(value)
                else:
                    value_str = str(value)
                # Escapuj pojedyncze cudzysłowy dla SQL
                value_str_escaped = value_str.replace("'", "''")
                self.conn.query(
                    f"INSERT INTO settings (setting_key, setting_value) VALUES ('{key}', '{value_str_escaped}') "
                    f"ON DUPLICATE KEY UPDATE setting_value = '{value_str_escaped}'",
                    ttl=0
                )
            
            # Przelicz całkowite punkty graczy
            self._recalculate_player_totals()
            
            logger.info("Import danych do MySQL zakonczony pomyslnie!")
        except Exception as e:
            logger.error(f"Blad importu danych do MySQL: {e}")
            raise
    
    def add_league(self, league_id: int, league_name: str = None):
        """Dodaje ligę do systemu"""
        try:
            league_id_str = str(league_id)
            # Użyj podanej nazwy lub domyślnej
            final_league_name = league_name or f"Liga {league_id}"
            self.conn.query(
                f"INSERT INTO leagues (league_id, league_name) VALUES ('{league_id_str}', '{final_league_name}') "
                f"ON DUPLICATE KEY UPDATE league_name = '{final_league_name}'",
                ttl=0
            )
            logger.info(f"Dodano ligę: {league_id}")
        except Exception as e:
            logger.error(f"Błąd dodawania ligi: {e}")
    
    def add_season(self, league_id: int, season_id: str, start_date: str = None, end_date: str = None):
        """Dodaje sezon do ligi"""
        try:
            league_id_str = str(league_id)
            self.add_league(league_id, None)
            
            self.conn.query(
                f"INSERT INTO seasons (season_id, league_id, start_date, end_date) "
                f"VALUES ('{season_id}', '{league_id_str}', '{start_date or ''}', '{end_date or ''}') "
                f"ON DUPLICATE KEY UPDATE league_id = '{league_id_str}', start_date = '{start_date or ''}', end_date = '{end_date or ''}'",
                ttl=0
            )
            logger.info(f"Dodano sezon: {season_id}")
        except Exception as e:
            logger.error(f"Błąd dodawania sezonu: {e}")
    
    def add_round(self, season_id: str, round_id: str, matches: List[Dict], start_date: str = None):
        """Dodaje rundę do sezonu"""
        try:
            # Dodaj sezon jeśli nie istnieje
            if not self.conn.query(f"SELECT * FROM seasons WHERE season_id = '{season_id}'", ttl=0).empty:
                pass
            else:
                self.add_season(None, season_id, None, None)
            
            # Dodaj rundę
            self.conn.query(
                f"INSERT INTO rounds (round_id, season_id, start_date, end_date) "
                f"VALUES ('{round_id}', '{season_id}', '{start_date or ''}', '{start_date or ''}') "
                f"ON DUPLICATE KEY UPDATE season_id = '{season_id}', start_date = '{start_date or ''}', end_date = '{start_date or ''}'",
                ttl=0
            )
            
            # Dodaj mecze
            for match in matches:
                match_id = str(match.get('match_id', ''))
                home_team = match.get('home_team_name', '').replace("'", "''")
                away_team = match.get('away_team_name', '').replace("'", "''")
                match_date = match.get('match_date', '').replace("'", "''")
                home_goals = match.get('home_goals') if match.get('home_goals') is not None else 'NULL'
                away_goals = match.get('away_goals') if match.get('away_goals') is not None else 'NULL'
                league_id = match.get('league_id', 'NULL')
                
                self.conn.query(
                    f"INSERT INTO matches (match_id, round_id, home_team_name, away_team_name, match_date, home_goals, away_goals, league_id) "
                    f"VALUES ('{match_id}', '{round_id}', '{home_team}', '{away_team}', '{match_date}', {home_goals}, {away_goals}, {league_id}) "
                    f"ON DUPLICATE KEY UPDATE home_team_name = '{home_team}', away_team_name = '{away_team}', "
                    f"match_date = '{match_date}', home_goals = {home_goals}, away_goals = {away_goals}, league_id = {league_id}",
                    ttl=0
                )
            
            logger.info(f"Dodano rundę: {round_id} z {len(matches)} meczami")
        except Exception as e:
            logger.error(f"Błąd dodawania rundy: {e}")
            raise
    
    def add_prediction(self, round_id: str, player_name: str, match_id: str, prediction: tuple):
        """Dodaje lub aktualizuje typ gracza dla meczu"""
        try:
            # Upewnij się, że gracz istnieje
            self.conn.query(
                f"INSERT INTO players (player_name, total_points, rounds_played, best_score, worst_score) "
                f"VALUES ('{player_name}', 0, 0, 0, 0) "
                f"ON DUPLICATE KEY UPDATE player_name = '{player_name}'",
                ttl=0
            )
            
            # Dodaj lub zaktualizuj typ
            timestamp = datetime.now().isoformat()
            self.conn.query(
                f"INSERT INTO predictions (round_id, player_name, match_id, home_goals, away_goals, timestamp) "
                f"VALUES ('{round_id}', '{player_name}', '{match_id}', {prediction[0]}, {prediction[1]}, '{timestamp}') "
                f"ON DUPLICATE KEY UPDATE home_goals = {prediction[0]}, away_goals = {prediction[1]}, timestamp = '{timestamp}'",
                ttl=0
            )
            
            # Jeśli mecz jest rozegrany, przelicz punkty
            match_result = self.conn.query(
                f"SELECT home_goals, away_goals FROM matches WHERE match_id = '{match_id}' AND round_id = '{round_id}'",
                ttl=0
            )
            if not match_result.empty and match_result.iloc[0]['home_goals'] is not None and match_result.iloc[0]['away_goals'] is not None:
                from tipper import Tipper
                home_goals = int(match_result.iloc[0]['home_goals'])
                away_goals = int(match_result.iloc[0]['away_goals'])
                points = Tipper.calculate_points(prediction, (home_goals, away_goals))
                
                # Zapisz punkty
                self.conn.query(
                    f"INSERT INTO match_points (round_id, player_name, match_id, points) "
                    f"VALUES ('{round_id}', '{player_name}', '{match_id}', {points}) "
                    f"ON DUPLICATE KEY UPDATE points = {points}",
                    ttl=0
                )
                
                # Przelicz całkowite punkty gracza
                self._recalculate_player_totals()
            
            # Wyczyść cache po zapisie
            TipperStorageMySQL._memory_cache = None
            TipperStorageMySQL._cache_timestamp = None
            
            logger.info(f"Dodano typ: {player_name} dla meczu {match_id} w rundzie {round_id}")
            return True
        except Exception as e:
            logger.error(f"Błąd dodawania typu: {e}")
            return False
    
    def update_match_result(self, round_id: str, match_id: str, home_goals: int, away_goals: int):
        """Aktualizuje wynik meczu i przelicza punkty"""
        try:
            # Aktualizuj wynik meczu
            self.conn.query(
                f"UPDATE matches SET home_goals = {home_goals}, away_goals = {away_goals} "
                f"WHERE match_id = '{match_id}' AND round_id = '{round_id}'",
                ttl=0
            )
            
            # Przelicz punkty dla wszystkich graczy
            from tipper import Tipper
            predictions_df = self.conn.query(
                f"SELECT * FROM predictions WHERE round_id = '{round_id}' AND match_id = '{match_id}'",
                ttl=0
            )
            
            for _, pred_row in predictions_df.iterrows():
                player_name = pred_row['player_name']
                prediction = (int(pred_row['home_goals']), int(pred_row['away_goals']))
                points = Tipper.calculate_points(prediction, (home_goals, away_goals))
                
                # Zapisz punkty
                self.conn.query(
                    f"INSERT INTO match_points (round_id, player_name, match_id, points) "
                    f"VALUES ('{round_id}', '{player_name}', '{match_id}', {points}) "
                    f"ON DUPLICATE KEY UPDATE points = {points}",
                    ttl=0
                )
            
            # Przelicz całkowite punkty graczy
            self._recalculate_player_totals()
            
            # Wyczyść cache po zapisie
            TipperStorageMySQL._memory_cache = None
            TipperStorageMySQL._cache_timestamp = None
            
            logger.info(f"Zaktualizowano wynik meczu {match_id} w rundzie {round_id}")
        except Exception as e:
            logger.error(f"Błąd aktualizacji wyniku meczu: {e}")
    
    def _recalculate_player_totals(self):
        """Przelicza całkowite punkty dla wszystkich graczy"""
        try:
            from tipper import Tipper
            
            # Pobierz wszystkich graczy
            players_df = self.conn.query("SELECT player_name FROM players", ttl=0)
            
            for _, player_row in players_df.iterrows():
                player_name = player_row['player_name']
                
                # Pobierz wszystkie punkty gracza
                points_df = self.conn.query(
                    f"SELECT points FROM match_points WHERE player_name = '{player_name}'",
                    ttl=0
                )
                
                total_points = int(points_df['points'].sum()) if not points_df.empty else 0
                
                # Pobierz punkty per runda
                round_points_df = self.conn.query(
                    f"SELECT round_id, SUM(points) as round_total FROM match_points WHERE player_name = '{player_name}' GROUP BY round_id",
                    ttl=0
                )
                
                rounds_played = len(round_points_df) if not round_points_df.empty else 0
                best_score = int(round_points_df['round_total'].max()) if not round_points_df.empty and len(round_points_df) > 0 else 0
                worst_score = int(round_points_df['round_total'].min()) if not round_points_df.empty and len(round_points_df) > 0 else 0
                
                # Aktualizuj gracza
                self.conn.query(
                    f"UPDATE players SET total_points = {total_points}, rounds_played = {rounds_played}, "
                    f"best_score = {best_score}, worst_score = {worst_score} WHERE player_name = '{player_name}'",
                    ttl=0
                )
            
            logger.info("Przeliczono całkowite punkty dla wszystkich graczy")
        except Exception as e:
            logger.error(f"Błąd przeliczania punktów: {e}")
    
    def get_round_predictions(self, round_id: str) -> Dict:
        """Zwraca typy dla rundy"""
        try:
            predictions_df = self.conn.query(
                f"SELECT * FROM predictions WHERE round_id = '{round_id}'",
                ttl=0
            )
            
            result = {}
            for _, row in predictions_df.iterrows():
                player_name = row['player_name']
                match_id = row['match_id']
                if player_name not in result:
                    result[player_name] = {}
                result[player_name][match_id] = {
                    'home': int(row['home_goals']),
                    'away': int(row['away_goals']),
                    'timestamp': row['timestamp']
                }
            
            return result
        except Exception as e:
            logger.error(f"Błąd pobierania typów dla rundy: {e}")
            return {}
    
    def get_player_predictions(self, player_name: str, round_id: str = None, use_cache: bool = True) -> Dict:
        """Zwraca typy gracza
        
        Args:
            player_name: Nazwa gracza
            round_id: ID rundy (opcjonalne)
            use_cache: Czy używać cache (domyślnie True dla lepszej wydajności)
        """
        try:
            # Spróbuj użyć cache jeśli jest dostępny
            if use_cache and TipperStorageMySQL._memory_cache is not None:
                cache = TipperStorageMySQL._memory_cache
                if round_id:
                    # Pobierz z cache
                    if round_id in cache.get('rounds', {}):
                        round_data = cache['rounds'][round_id]
                        if 'predictions' in round_data and player_name in round_data['predictions']:
                            return round_data['predictions'][player_name]
                else:
                    # Pobierz wszystkie typy gracza z cache
                    result = {}
                    for r_id, round_data in cache.get('rounds', {}).items():
                        if 'predictions' in round_data and player_name in round_data['predictions']:
                            result[r_id] = round_data['predictions'][player_name]
                    if result:
                        return result
            
            # Jeśli cache nie zawiera danych, pobierz z bazy
            if round_id:
                query = f"SELECT * FROM predictions WHERE player_name = '{player_name}' AND round_id = '{round_id}'"
            else:
                query = f"SELECT * FROM predictions WHERE player_name = '{player_name}'"
            
            # Użyj cache dla zapytania (ttl=60 sekund) zamiast ttl=0
            predictions_df = self.conn.query(query, ttl=60 if use_cache else 0)
            
            if round_id:
                result = {}
                for _, row in predictions_df.iterrows():
                    result[row['match_id']] = {
                        'home': int(row['home_goals']),
                        'away': int(row['away_goals']),
                        'timestamp': row['timestamp']
                    }
                return result
            else:
                result = {}
                for _, row in predictions_df.iterrows():
                    r_id = row['round_id']
                    if r_id not in result:
                        result[r_id] = {}
                    result[r_id][row['match_id']] = {
                        'home': int(row['home_goals']),
                        'away': int(row['away_goals']),
                        'timestamp': row['timestamp']
                    }
                return result
        except Exception as e:
            logger.error(f"Błąd pobierania typów gracza: {e}")
            return {}
    
    def get_current_season(self) -> Optional[str]:
        """Zwraca aktualny sezon (z settings) - używa cache dla lepszej wydajności"""
        try:
            # Spróbuj użyć cache jeśli jest dostępny
            if TipperStorageMySQL._memory_cache is not None:
                cache = TipperStorageMySQL._memory_cache
                if 'settings' in cache and 'current_season' in cache['settings']:
                    return cache['settings']['current_season']
            
            # Jeśli cache nie zawiera danych, pobierz z bazy z cache (ttl=60 sekund)
            result = self.conn.query(
                "SELECT setting_value FROM settings WHERE setting_key = 'current_season'",
                ttl=60  # Użyj cache dla lepszej wydajności
            )
            if not result.empty:
                value = result.iloc[0]['setting_value']
                return value if value else None
            return None
        except Exception as e:
            logger.error(f"Błąd pobierania aktualnego sezonu: {e}")
            return None
    
    def set_current_season(self, season_id: str):
        """Ustawia aktualny sezon"""
        try:
            self.conn.query(
                f"INSERT INTO settings (setting_key, setting_value) VALUES ('current_season', '{season_id}') "
                f"ON DUPLICATE KEY UPDATE setting_value = '{season_id}'",
                ttl=0
            )
            # Wyczyść cache po zapisie
            TipperStorageMySQL._memory_cache = None
            TipperStorageMySQL._cache_timestamp = None
            logger.info(f"Ustawiono aktualny sezon: {season_id}")
        except Exception as e:
            logger.error(f"Błąd ustawiania aktualnego sezonu: {e}")
    
    def get_leaderboard(self, exclude_worst: bool = True, season_id: Optional[str] = None) -> List[Dict]:
        """Zwraca ranking graczy (z opcją odrzucenia najgorszego wyniku) dla danego sezonu - zoptymalizowane"""
        try:
            # Jeśli nie podano sezonu, użyj aktualnego sezonu
            if season_id is None:
                season_id = self.get_current_season()
            
            # Pobierz wszystkie rundy posortowane po dacie (najstarsza pierwsza) - z cache
            # Filtruj tylko rundy z aktualnego sezonu (jeśli sezon jest ustawiony)
            if season_id:
                rounds_df = self.conn.query(
                    f"SELECT r.round_id, r.start_date FROM rounds r "
                    f"INNER JOIN seasons s ON r.season_id = s.season_id "
                    f"WHERE s.season_id = '{season_id}' "
                    f"ORDER BY r.start_date ASC",
                    ttl=120  # Użyj cache dla lepszej wydajności
                )
            else:
                rounds_df = self.conn.query("SELECT round_id, start_date FROM rounds ORDER BY start_date ASC", ttl=120)
            all_rounds = []
            if not rounds_df.empty:
                for _, round_row in rounds_df.iterrows():
                    all_rounds.append((round_row['round_id'], round_row['start_date']))
            
            # Pobierz wszystkich graczy - z cache
            players_df = self.conn.query("SELECT * FROM players ORDER BY total_points DESC", ttl=120)
            
            # Zoptymalizowane: Pobierz wszystkie punkty per runda dla wszystkich graczy w jednym zapytaniu
            # Filtruj tylko rundy z aktualnego sezonu jeśli sezon jest ustawiony
            if season_id and all_rounds:
                round_ids_str = "', '".join([r[0] for r in all_rounds])
                all_round_points_df = self.conn.query(
                    f"SELECT player_name, round_id, SUM(points) as round_total "
                    f"FROM match_points "
                    f"WHERE round_id IN ('{round_ids_str}') "
                    f"GROUP BY player_name, round_id",
                    ttl=120  # Użyj cache dla lepszej wydajności
                )
            else:
                all_round_points_df = self.conn.query(
                    "SELECT player_name, round_id, SUM(points) as round_total "
                    "FROM match_points "
                    "GROUP BY player_name, round_id",
                    ttl=120  # Użyj cache dla lepszej wydajności
                )
            
            # Stwórz mapę player_name -> {round_id: points}
            player_round_points_map = {}
            if not all_round_points_df.empty:
                for _, row in all_round_points_df.iterrows():
                    player_name = row['player_name']
                    round_id = row['round_id']
                    points = int(row['round_total'])
                    if player_name not in player_round_points_map:
                        player_round_points_map[player_name] = {}
                    player_round_points_map[player_name][round_id] = points
            
            leaderboard = []
            for _, row in players_df.iterrows():
                player_name = row['player_name']
                
                # Pobierz punkty per runda z mapy (zamiast osobnego zapytania dla każdego gracza)
                round_points_map = player_round_points_map.get(player_name, {})
                
                # Zbierz punkty z każdej kolejki w kolejności (najstarsza pierwsza)
                # Jeśli gracz nie typował w rundzie, dodaj 0
                round_points_list = []
                for round_id, _ in all_rounds:
                    round_points = round_points_map.get(round_id, 0)
                    round_points_list.append(round_points)
                
                original_total = int(row['total_points'])
                worst_score = int(row['worst_score']) if row['worst_score'] else 0
                
                if exclude_worst and worst_score > 0 and len(round_points_list) > 1:
                    total_points = original_total - worst_score
                    excluded_worst = True
                else:
                    total_points = original_total
                    excluded_worst = False
                
                leaderboard.append({
                    'player_name': player_name,
                    'total_points': total_points,
                    'original_total': original_total,
                    'rounds_played': int(row['rounds_played']),
                    'best_score': int(row['best_score']),
                    'worst_score': worst_score,
                    'excluded_worst': excluded_worst,
                    'round_points': round_points_list  # Lista punktów z każdej kolejki (w kolejności dat)
                })
            
            leaderboard.sort(key=lambda x: x['total_points'], reverse=True)
            return leaderboard
        except Exception as e:
            logger.error(f"Błąd pobierania rankingu: {e}")
            return []
    
    def get_round_leaderboard(self, round_id: str) -> List[Dict]:
        """Zwraca ranking dla rundy - wszyscy gracze, nawet ci bez typów (z 0 punktami) - zoptymalizowane"""
        try:
            # Pobierz wszystkich graczy - z cache
            players_df = self.conn.query("SELECT player_name FROM players", ttl=120)
            all_players = set()
            if not players_df.empty:
                for _, row in players_df.iterrows():
                    all_players.add(row['player_name'])
            
            # Jeśli nie ma graczy, zwróć pustą listę
            if not all_players:
                return []
            
            # Sprawdź jakie round_id są w bazie - z cache
            all_rounds_df = self.conn.query("SELECT DISTINCT round_id FROM rounds", ttl=120)
            all_round_ids = []
            if not all_rounds_df.empty:
                all_round_ids = [str(row['round_id']) for _, row in all_rounds_df.iterrows()]
            
            # Jeśli nie znaleziono dokładnego round_id, spróbuj znaleźć podobny (bez prefiksu round_)
            actual_round_id = round_id
            if round_id not in all_round_ids:
                # Spróbuj znaleźć round_id bez prefiksu "round_"
                round_id_without_prefix = round_id.replace("round_", "", 1) if round_id.startswith("round_") else round_id
                # Szukaj round_id, który zawiera datę
                for db_round_id in all_round_ids:
                    if round_id_without_prefix in db_round_id or db_round_id in round_id:
                        actual_round_id = db_round_id
                        break
            
            # Pobierz mecze w rundzie (aby wiedzieć ile meczów było) - z cache
            matches_df = self.conn.query(
                f"SELECT match_id, match_date FROM matches WHERE round_id = '{actual_round_id}' ORDER BY match_date ASC",
                ttl=120  # Użyj cache dla lepszej wydajności
            )
            matches_count = len(matches_df) if not matches_df.empty else 0
            match_ids = []
            if not matches_df.empty:
                match_ids = [str(row['match_id']) for _, row in matches_df.iterrows()]
            
            # Pobierz punkty per gracz dla rundy - z cache
            points_df = self.conn.query(
                f"SELECT player_name, match_id, points FROM match_points WHERE round_id = '{actual_round_id}' ORDER BY player_name, match_id",
                ttl=120  # Użyj cache dla lepszej wydajności
            )
            
            player_totals = {}
            player_match_points = {}
            
            # Inicjalizuj wszystkich graczy z 0 punktami
            for player_name in all_players:
                player_totals[player_name] = 0
                player_match_points[player_name] = [0] * matches_count if matches_count > 0 else []
            
            # Wypełnij punkty dla graczy, którzy typowali
            if not points_df.empty:
                for _, row in points_df.iterrows():
                    player_name = row['player_name']
                    match_id = str(row['match_id'])
                    points = int(row['points'])
                    
                    # Znajdź indeks meczu w liście
                    if match_id in match_ids:
                        match_idx = match_ids.index(match_id)
                        if player_name in player_match_points and match_idx < len(player_match_points[player_name]):
                            player_match_points[player_name][match_idx] = points
                            player_totals[player_name] += points
            
            # Stwórz ranking (wszyscy gracze, nawet z 0 punktami)
            leaderboard = []
            for player_name in all_players:
                total_points = player_totals.get(player_name, 0)
                match_points_list = player_match_points.get(player_name, [])
                # Policz ile meczów z typami (nie 0)
                matches_with_predictions = sum(1 for p in match_points_list if p > 0)
                
                leaderboard.append({
                    'player_name': player_name,
                    'total_points': total_points,
                    'match_points': match_points_list,
                    'matches_count': matches_with_predictions
                })
            
            # Sortuj po punktach (malejąco)
            leaderboard.sort(key=lambda x: x['total_points'], reverse=True)
            
            return leaderboard
        except Exception as e:
            logger.error(f"Błąd pobierania rankingu rundy: {e}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            return []
    
    def get_selected_teams(self) -> List[str]:
        """Zwraca listę wybranych drużyn - używa cache dla lepszej wydajności"""
        try:
            # Spróbuj użyć cache jeśli jest dostępny
            if TipperStorageMySQL._memory_cache is not None:
                cache = TipperStorageMySQL._memory_cache
                if 'settings' in cache and 'selected_teams' in cache['settings']:
                    return cache['settings']['selected_teams']
            
            # Jeśli cache nie zawiera danych, pobierz z bazy z cache (ttl=60 sekund)
            result = self.conn.query(
                "SELECT setting_value FROM settings WHERE setting_key = 'selected_teams'",
                ttl=60  # Użyj cache dla lepszej wydajności
            )
            if not result.empty:
                value = result.iloc[0]['setting_value']
                return json.loads(value) if value else []
            return []
        except Exception as e:
            logger.error(f"Błąd pobierania wybranych drużyn: {e}")
            return []
    
    def set_selected_teams(self, teams: List[str]):
        """Zapisuje listę wybranych drużyn"""
        try:
            value = json.dumps(teams)
            self.conn.query(
                f"INSERT INTO settings (setting_key, setting_value) VALUES ('selected_teams', '{value}') "
                f"ON DUPLICATE KEY UPDATE setting_value = '{value}'",
                ttl=0
            )
            # Wyczyść cache po zapisie
            TipperStorageMySQL._memory_cache = None
            TipperStorageMySQL._cache_timestamp = None
            
            logger.info(f"Zapisano wybrane drużyny: {len(teams)}")
        except Exception as e:
            logger.error(f"Błąd zapisywania wybranych drużyn: {e}")
    
    def get_selected_leagues(self) -> List[int]:
        """Zwraca listę ID wybranych lig - używa cache dla lepszej wydajności"""
        try:
            # Spróbuj użyć cache jeśli jest dostępny
            if TipperStorageMySQL._memory_cache is not None:
                cache = TipperStorageMySQL._memory_cache
                if 'settings' in cache and 'selected_leagues' in cache['settings']:
                    leagues_data = cache['settings']['selected_leagues']
                    # Obsługa starego formatu (słownik) - konwersja do listy
                    if isinstance(leagues_data, dict):
                        leagues_data = list(leagues_data.keys())
                    # Konwertuj na int jeśli są stringi
                    return [int(league_id) if isinstance(league_id, str) else league_id for league_id in leagues_data]
            
            # Jeśli cache nie zawiera danych, pobierz z bazy z cache (ttl=60 sekund)
            result = self.conn.query(
                "SELECT setting_value FROM settings WHERE setting_key = 'selected_leagues'",
                ttl=60  # Użyj cache dla lepszej wydajności
            )
            if not result.empty:
                value = result.iloc[0]['setting_value']
                if value:
                    leagues_data = json.loads(value)
                    # Obsługa starego formatu (słownik) - konwersja do listy
                    if isinstance(leagues_data, dict):
                        leagues_data = list(leagues_data.keys())
                        # Zaktualizuj w bazie do nowego formatu
                        self.set_selected_leagues(leagues_data)
                    # Konwertuj na int jeśli są stringi
                    return [int(league_id) if isinstance(league_id, str) else league_id for league_id in leagues_data]
            return [32612, 9399]  # Domyślne ligi
        except Exception as e:
            logger.error(f"Błąd pobierania wybranych lig: {e}")
            return [32612, 9399]
    
    def set_selected_leagues(self, league_ids: List[int]):
        """Zapisuje listę ID wybranych lig"""
        try:
            value = json.dumps(league_ids)
            self.conn.query(
                f"INSERT INTO settings (setting_key, setting_value) VALUES ('selected_leagues', '{value}') "
                f"ON DUPLICATE KEY UPDATE setting_value = '{value}'",
                ttl=0
            )
            # Wyczyść cache po zapisie
            TipperStorageMySQL._memory_cache = None
            TipperStorageMySQL._cache_timestamp = None
            
            logger.info(f"Zapisano wybrane ligi: {len(league_ids)}")
        except Exception as e:
            logger.error(f"Błąd zapisywania wybranych lig: {e}")

