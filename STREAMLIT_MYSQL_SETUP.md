# 🗄️ Konfiguracja MySQL na Streamlit Cloud - Krok po kroku

## 📋 Wymagania

- Konto na Streamlit Cloud
- Dostęp do bazy danych MySQL (lokalnej lub w chmurze)

## 🚀 Krok 1: Utwórz bazę danych MySQL

### Opcja A: Darmowe bazy danych w chmurze (Zalecane)

#### 1. PlanetScale (Darmowy tier - 5GB)
1. Przejdź na https://planetscale.com
2. Zarejestruj się (można przez GitHub)
3. Utwórz nową bazę danych:
   - Kliknij "Create database"
   - Wybierz plan "Free"
   - Podaj nazwę bazy (np. `hattrick_typer`)
   - Wybierz region (najbliższy)
4. Po utworzeniu, kliknij "Connect" i skopiuj dane:
   - Host
   - Username
   - Password
   - Database name
   - Port (domyślnie 3306)

#### 2. Railway (Darmowy tier - $5 kredytów miesięcznie)
1. Przejdź na https://railway.app
2. Zarejestruj się
3. Kliknij "New Project" → "Provision MySQL"
4. Po utworzeniu, kliknij na bazę danych → "Variables"
5. Skopiuj dane:
   - `MYSQLHOST` (host)
   - `MYSQLPORT` (port)
   - `MYSQLDATABASE` (nazwa bazy)
   - `MYSQLUSER` (użytkownik)
   - `MYSQLPASSWORD` (hasło)

#### 3. Aiven (Darmowy tier - $300 kredytów)
1. Przejdź na https://aiven.io
2. Zarejestruj się
3. Utwórz nowy serwis MySQL
4. Skopiuj dane połączenia

### Opcja B: Lokalna baza MySQL

Jeśli masz lokalną bazę MySQL, musisz:
1. Upewnić się, że jest dostępna z internetu (port forwarding lub VPN)
2. Skonfigurować firewall aby pozwolić połączenia z Streamlit Cloud

## 🗃️ Krok 2: Utwórz strukturę bazy danych

1. **Połącz się z bazą danych** (użyj narzędzia jak MySQL Workbench, phpMyAdmin, lub terminal):
   ```bash
   mysql -h twoj_host -u uzytkownik -p nazwa_bazy
   ```

2. **Uruchom skrypt SQL** z pliku `database_schema.sql`:
   ```sql
   -- Skopiuj zawartość pliku database_schema.sql i wklej w konsoli MySQL
   ```
   
   Lub zaimportuj plik:
   ```bash
   mysql -h twoj_host -u uzytkownik -p nazwa_bazy < database_schema.sql
   ```

3. **Sprawdź czy tabele zostały utworzone**:
   ```sql
   SHOW TABLES;
   ```
   
   Powinieneś zobaczyć:
   - `players`
   - `leagues`
   - `seasons`
   - `rounds`
   - `matches`
   - `predictions`
   - `match_points`
   - `settings`

## 🔐 Krok 3: Skonfiguruj Streamlit Secrets

### W Streamlit Cloud:

1. **Zaloguj się** do Streamlit Cloud: https://share.streamlit.io
2. **Przejdź do swojej aplikacji** (lub utwórz nową)
3. **Kliknij "Manage app"** (⚙️ ikona)
4. **Kliknij "Secrets"** w menu po lewej
5. **Wklej następującą konfigurację**:

```toml
[connections.mysql]
dialect = "mysql"
host = "twoj_host_mysql"
port = 3306
database = "nazwa_bazy_danych"
username = "nazwa_uzytkownika"
password = "twoje_haslo"
```

**Przykład dla PlanetScale:**
```toml
[connections.mysql]
dialect = "mysql"
host = "aws.connect.psdb.cloud"
port = 3306
database = "hattrick_typer"
username = "abc123xyz"
password = "pscale_pw_xyz123"
```

**Przykład dla Railway:**
```toml
[connections.mysql]
dialect = "mysql"
host = "containers-us-west-123.railway.app"
port = 3306
database = "railway"
username = "root"
password = "xyz123"
```

6. **Kliknij "Save"** aby zapisać secrets

### Lokalnie (opcjonalnie, do testów):

1. **Utwórz folder `.streamlit`** w katalogu głównym projektu:
   ```bash
   mkdir .streamlit
   ```

2. **Utwórz plik `secrets.toml`** w folderze `.streamlit`:
   ```toml
   [connections.mysql]
   dialect = "mysql"
   host = "localhost"
   port = 3306
   database = "hattrick_typer"
   username = "root"
   password = "twoje_haslo"
   ```

3. **Dodaj do `.gitignore`** (WAŻNE!):
   ```
   .streamlit/secrets.toml
   ```

## ✅ Krok 4: Sprawdź konfigurację

1. **Zrestartuj aplikację** w Streamlit Cloud (kliknij "Reboot app")
2. **Sprawdź logi** aplikacji - powinieneś zobaczyć:
   ```
   Używam MySQL jako storage
   Połączono z bazą MySQL
   Struktura bazy danych zainicjalizowana
   ```

3. **Jeśli widzisz błędy**, sprawdź:
   - Czy dane w Secrets są poprawne
   - Czy baza danych jest dostępna z internetu
   - Czy firewall pozwala połączenia z Streamlit Cloud
   - Czy struktura bazy danych została utworzona

## 🔄 Krok 5: Migracja danych (opcjonalnie)

Jeśli masz już dane w pliku `tipper_data.json`:

1. **Eksportuj dane** z aplikacji:
   - Zaloguj się do aplikacji
   - Kliknij "📥 Pobierz backup danych"
   - Pobierz plik `tipper_data.json`

2. **Zaimportuj dane** do MySQL:
   - Zaloguj się do aplikacji (z MySQL skonfigurowanym)
   - Kliknij "📤 Import danych z pliku"
   - Wgraj plik `tipper_data.json`
   - Kliknij "💾 Zaimportuj dane"

3. **Sprawdź czy dane zostały zaimportowane**:
   - Sprawdź ranking - powinny być widoczne wszystkie gracze i rundy

## 🛠️ Rozwiązywanie problemów

### Błąd: "Błąd połączenia z MySQL"

**Rozwiązanie:**
- Sprawdź czy dane w Secrets są poprawne
- Sprawdź czy baza danych jest dostępna z internetu
- Sprawdź czy firewall pozwala połączenia

### Błąd: "Table doesn't exist"

**Rozwiązanie:**
- Uruchom ponownie skrypt `database_schema.sql`
- Sprawdź czy wszystkie tabele zostały utworzone

### Błąd: "Access denied"

**Rozwiązanie:**
- Sprawdź czy użytkownik ma uprawnienia do bazy danych
- Sprawdź czy hasło jest poprawne
- Sprawdź czy użytkownik może łączyć się z zewnętrznych hostów

### Dane nie są zapisywane

**Rozwiązanie:**
- Sprawdź logi aplikacji
- Sprawdź czy MySQL jest używane (powinno być w logach: "Używam MySQL jako storage")
- Sprawdź czy nie ma błędów w konsoli Streamlit

## 📝 Notatki

- **Bezpieczeństwo**: Hasła w Streamlit Secrets są szyfrowane
- **Backup**: Regularnie rób backup danych używając funkcji eksportu
- **Testowanie**: Możesz testować lokalnie używając `.streamlit/secrets.toml`
- **Darmowe opcje**: PlanetScale, Railway, Aiven oferują darmowe tery dla małych projektów

## 🔗 Przydatne linki

- [Streamlit Secrets Documentation](https://docs.streamlit.io/develop/concepts/connections/secrets-management)
- [PlanetScale](https://planetscale.com)
- [Railway](https://railway.app)
- [Aiven](https://aiven.io)

