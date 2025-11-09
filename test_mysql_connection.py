"""
Skrypt do testowania połączenia z MySQL
Używa danych z pliku .env (linie 9-15)
"""
import os
from dotenv import load_dotenv
import streamlit as st

# Załaduj zmienne środowiskowe
load_dotenv()

# Pobierz dane MySQL z .env (linie 9-15)
# Zakładam format:
# MYSQL_HOST=host
# MYSQL_PORT=3306
# MYSQL_DATABASE=nazwa_bazy
# MYSQL_USER=uzytkownik
# MYSQL_PASSWORD=haslo

mysql_host = os.getenv('MYSQL_HOST')
mysql_port = os.getenv('MYSQL_PORT', '3306')
mysql_database = os.getenv('MYSQL_DATABASE')
mysql_user = os.getenv('MYSQL_USER')
mysql_password = os.getenv('MYSQL_PASSWORD')

print("=" * 50)
print("Test połączenia z MySQL")
print("=" * 50)
print(f"Host: {mysql_host}")
print(f"Port: {mysql_port}")
print(f"Database: {mysql_database}")
print(f"User: {mysql_user}")
print(f"Password: {'*' * len(mysql_password) if mysql_password else 'BRAK'}")
print("=" * 50)

if not all([mysql_host, mysql_database, mysql_user, mysql_password]):
    print("BLAD: Brakuje wymaganych danych MySQL w pliku .env")
    print("\nUpewnij się, że w pliku .env są następujące zmienne:")
    print("MYSQL_HOST=twoj_host")
    print("MYSQL_PORT=3306")
    print("MYSQL_DATABASE=nazwa_bazy")
    print("MYSQL_USER=uzytkownik")
    print("MYSQL_PASSWORD=haslo")
    exit(1)

# Test połączenia
try:
    import pymysql
    
    print("\n🔌 Próba połączenia z MySQL...")
    connection = pymysql.connect(
        host=mysql_host,
        port=int(mysql_port),
        user=mysql_user,
        password=mysql_password,
        database=mysql_database,
        charset='utf8mb4',
        cursorclass=pymysql.cursors.DictCursor
    )
    
    print("OK: Polaczenie z MySQL udane!")
    
    # Test zapytania
    with connection.cursor() as cursor:
        cursor.execute("SELECT VERSION()")
        version = cursor.fetchone()
        print(f"Wersja MySQL: {version['VERSION()']}")
        
        # Sprawdź czy tabele istnieją
        cursor.execute("SHOW TABLES")
        tables = cursor.fetchall()
        table_names = [list(table.values())[0] for table in tables]
        
        print(f"\nZnalezione tabele ({len(table_names)}):")
        required_tables = ['players', 'leagues', 'seasons', 'rounds', 'matches', 'predictions', 'match_points', 'settings']
        
        for table in required_tables:
            if table in table_names:
                print(f"  OK: {table}")
            else:
                print(f"  BRAK: {table}")
        
        if len(table_names) == 0:
            print("\nUWAGA: Baza danych jest pusta!")
            print("   Uruchom skrypt database_schema.sql aby utworzyc tabele")
        elif len([t for t in required_tables if t in table_names]) < len(required_tables):
            print("\nUWAGA: Brakuje niektorych tabel!")
            print("   Uruchom skrypt database_schema.sql aby utworzyc brakujace tabele")
        else:
            print("\nOK: Wszystkie wymagane tabele istnieja!")
    
    connection.close()
    print("\nOK: Test zakonczony pomyslnie!")
    
    # Wygeneruj konfigurację dla Streamlit Secrets
    print("\n" + "=" * 50)
    print("Konfiguracja dla Streamlit Secrets:")
    print("=" * 50)
    print("\nSkopiuj poniższą konfigurację do Streamlit Secrets:")
    print("\n```toml")
    print("[connections.mysql]")
    print(f'dialect = "mysql"')
    print(f'host = "{mysql_host}"')
    print(f'port = {mysql_port}')
    print(f'database = "{mysql_database}"')
    print(f'username = "{mysql_user}"')
    print(f'password = "{mysql_password}"')
    print("```")
    print("\n" + "=" * 50)
    
except ImportError:
    print("BLAD: Brak biblioteki pymysql")
    print("   Zainstaluj: pip install pymysql")
    exit(1)
except Exception as e:
    print(f"\nBLAD polaczenia z MySQL: {e}")
    print("\nSprawdź:")
    print("  - Czy dane w .env są poprawne")
    print("  - Czy baza danych jest dostępna z internetu")
    print("  - Czy firewall pozwala połączenia")
    print("  - Czy użytkownik ma uprawnienia do bazy danych")
    exit(1)

