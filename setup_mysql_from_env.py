"""
Skrypt do konfiguracji MySQL używając danych z .env
Sprawdza dane MySQL w .env i generuje konfigurację dla Streamlit Secrets
"""
import os
from dotenv import load_dotenv

# Załaduj zmienne środowiskowe
load_dotenv()

print("=" * 60)
print("Konfiguracja MySQL z pliku .env")
print("=" * 60)

# Sprawdź różne możliwe nazwy zmiennych dla MySQL
mysql_configs = [
    ('MYSQL_HOST', 'MYSQL_PORT', 'MYSQL_DATABASE', 'MYSQL_USER', 'MYSQL_PASSWORD'),
    ('DB_HOST', 'DB_PORT', 'DB_NAME', 'DB_USER', 'DB_PASSWORD'),
    ('DATABASE_HOST', 'DATABASE_PORT', 'DATABASE_NAME', 'DATABASE_USER', 'DATABASE_PASSWORD'),
]

mysql_host = None
mysql_port = None
mysql_database = None
mysql_user = None
mysql_password = None

# Spróbuj znaleźć dane MySQL w .env
for host_var, port_var, db_var, user_var, pass_var in mysql_configs:
    if os.getenv(host_var):
        mysql_host = os.getenv(host_var)
        mysql_port = os.getenv(port_var, '3306')
        mysql_database = os.getenv(db_var)
        mysql_user = os.getenv(user_var)
        mysql_password = os.getenv(pass_var)
        print(f"Znaleziono konfiguracje MySQL uzywajac zmiennych:")
        print(f"  {host_var}, {port_var}, {db_var}, {user_var}, {pass_var}")
        break

# Jeśli nie znaleziono, sprawdź linie 9-15 (autentykacja aplikacji)
if not mysql_host:
    print("\nNie znaleziono danych MySQL w .env")
    print("Sprawdzam linie 9-15 (autentykacja aplikacji)...")
    
    app_username = os.getenv('APP_USERNAME')
    app_password_hash = os.getenv('APP_PASSWORD_HASH')
    app_password_salt = os.getenv('APP_PASSWORD_SALT')
    
    if app_username:
        print(f"\nZnaleziono dane autentykacji aplikacji:")
        print(f"  APP_USERNAME: {app_username}")
        print(f"  APP_PASSWORD_HASH: {'*' * 20 if app_password_hash else 'BRAK'}")
        print(f"  APP_PASSWORD_SALT: {'*' * 20 if app_password_salt else 'BRAK'}")
        print("\nUWAGA: Te dane to autentykacja aplikacji, nie MySQL!")
        print("Aby skonfigurowac MySQL, dodaj do .env:")
        print("  MYSQL_HOST=twoj_host")
        print("  MYSQL_PORT=3306")
        print("  MYSQL_DATABASE=nazwa_bazy")
        print("  MYSQL_USER=uzytkownik")
        print("  MYSQL_PASSWORD=haslo")
    else:
        print("\nNie znaleziono danych MySQL ani autentykacji w .env")
        print("\nDodaj do pliku .env:")
        print("  MYSQL_HOST=twoj_host")
        print("  MYSQL_PORT=3306")
        print("  MYSQL_DATABASE=nazwa_bazy")
        print("  MYSQL_USER=uzytkownik")
        print("  MYSQL_PASSWORD=haslo")
    
    exit(0)

# Wyświetl znalezione dane
print("\n" + "=" * 60)
print("Znalezione dane MySQL:")
print("=" * 60)
print(f"Host: {mysql_host}")
print(f"Port: {mysql_port}")
print(f"Database: {mysql_database}")
print(f"User: {mysql_user}")
print(f"Password: {'*' * len(mysql_password) if mysql_password else 'BRAK'}")
print("=" * 60)

if not all([mysql_host, mysql_database, mysql_user, mysql_password]):
    print("\nBLAD: Brakuje wymaganych danych MySQL!")
    print("Upewnij sie, ze w pliku .env sa wszystkie zmienne:")
    print("  MYSQL_HOST")
    print("  MYSQL_DATABASE")
    print("  MYSQL_USER")
    print("  MYSQL_PASSWORD")
    exit(1)

# Test połączenia
print("\nProba polaczenia z MySQL...")
try:
    import pymysql
    
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
    
    # Sprawdź tabele
    with connection.cursor() as cursor:
        cursor.execute("SHOW TABLES")
        tables = cursor.fetchall()
        table_names = [list(table.values())[0] for table in tables]
        
        required_tables = ['players', 'leagues', 'seasons', 'rounds', 'matches', 'predictions', 'match_points', 'settings']
        missing_tables = [t for t in required_tables if t not in table_names]
        
        if missing_tables:
            print(f"\nUWAGA: Brakuje tabel: {', '.join(missing_tables)}")
            print("Uruchom skrypt database_schema.sql aby utworzyc tabele")
        else:
            print("\nOK: Wszystkie wymagane tabele istnieja!")
    
    connection.close()
    
except ImportError:
    print("BLAD: Brak biblioteki pymysql")
    print("Zainstaluj: pip install pymysql")
    exit(1)
except Exception as e:
    print(f"BLAD polaczenia: {e}")
    print("\nSprawdz:")
    print("  - Czy dane w .env sa poprawne")
    print("  - Czy baza danych jest dostepna")
    print("  - Czy firewall pozwala polaczenia")
    exit(1)

# Wygeneruj konfigurację dla Streamlit Secrets
print("\n" + "=" * 60)
print("Konfiguracja dla Streamlit Secrets:")
print("=" * 60)
print("\nSkopiuj ponizsza konfiguracje do Streamlit Secrets:")
print("\n```toml")
print("[connections.mysql]")
print(f'dialect = "mysql"')
print(f'host = "{mysql_host}"')
print(f'port = {mysql_port}')
print(f'database = "{mysql_database}"')
print(f'username = "{mysql_user}"')
print(f'password = "{mysql_password}"')
print("```")
print("\n" + "=" * 60)
print("\nOK: Konfiguracja gotowa!")

