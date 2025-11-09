# 🎯 Hattrick Typer

Aplikacja do prowadzenia typera dla lig Hattrick. Pozwala na wprowadzanie typów, śledzenie wyników i wyświetlanie rankingów.

## 📋 Funkcje

- 🔐 **Autentykacja** - zabezpieczenie aplikacji loginem i hasłem
- ✅ Wprowadzanie typów dla meczów (pojedyncze lub bulk)
- ✅ Automatyczny zapis po wyjściu z pola tekstowego
- ✅ Ranking per kolejka i ranking całości
- ✅ Wybór drużyn do typowania
- ✅ Synchronizacja wyboru rundy między sekcjami
- ✅ Automatyczne pobieranie wyników z API Hattrick
- ✅ Punktacja zgodna z regulaminem typera

## 🚀 Instalacja

1. Sklonuj lub pobierz projekt
2. Zainstaluj zależności:
```bash
pip install -r requirements.txt
```

3. Skonfiguruj zmienne środowiskowe:
   - Skopiuj `env_example.txt` do `.env`
   - Wypełnij klucze OAuth Hattrick:
     ```
     HATTRICK_CONSUMER_KEY=twoj_consumer_key
     HATTRICK_CONSUMER_SECRET=twoj_consumer_secret
     HATTRICK_ACCESS_TOKEN=twoj_access_token
     HATTRICK_ACCESS_TOKEN_SECRET=twoj_access_token_secret
     ```
   - Skonfiguruj autentykację (login i hasło):
     - Wygeneruj hash hasła: `python generate_password.py`
     - Dodaj do `.env`:
       ```
       APP_USERNAME=admin
       APP_PASSWORD_HASH=wygenerowany_hash
       APP_PASSWORD_SALT=wygenerowana_sol
       ```
     - Domyślnie: login `admin`, hasło `admin` (zmień przed użyciem!)

4. Uruchom aplikację:
```bash
streamlit run app.py
```

## ⚙️ Konfiguracja

### Autentykacja (Login i Hasło)

Aplikacja wymaga logowania przed dostępem do funkcji.

**Konfiguracja użytkownika:**

1. Wygeneruj hash hasła:
   ```bash
   python generate_password.py
   ```

2. Dodaj do pliku `.env`:
   ```
   APP_USERNAME=twoja_nazwa_uzytkownika
   APP_PASSWORD_HASH=wygenerowany_hash
   APP_PASSWORD_SALT=wygenerowana_sol
   ```

3. Dla wielu użytkowników (opcjonalnie):
   ```
   APP_USER_1_USERNAME=user1
   APP_USER_1_PASSWORD_HASH=hash1
   APP_USER_1_PASSWORD_SALT=salt1
   APP_USER_2_USERNAME=user2
   APP_USER_2_PASSWORD_HASH=hash2
   APP_USER_2_PASSWORD_SALT=salt2
   ```

**Domyślne dane logowania:**
- Login: `admin`
- Hasło: `admin`
- ⚠️ **Zmień przed użyciem w produkcji!**

### Klucze OAuth Hattrick

Aby uzyskać klucze OAuth:
1. Zarejestruj aplikację na https://www.hattrick.org/Community/CHPP/Default.aspx
2. Uzyskaj `consumer_key` i `consumer_secret`
3. Użyj skryptu do autoryzacji (lub ręcznie) aby uzyskać `access_token` i `access_token_secret`

### Ligi

Domyślnie aplikacja pobiera mecze z lig:
- Liga 1: 32612
- Liga 2: 9399

Możesz zmienić te wartości w sidebarze aplikacji.

## 📊 Punktacja

Zgodnie z regulaminem typera:
- **Dokładny wynik**: 12 punktów
- **Prawidłowy rezultat** (zwycięstwo/remis): 10 punktów
- **Nieprawidłowy rezultat**: 5 punktów
- **Odejmowanie**: minus różnica bramek (gospodarze i goście osobno)
- **Minimum**: 0 punktów (nie dopuszcza się wartości ujemnych)

## 📁 Struktura projektu

```
tipper_project/
├── app.py                    # Główna aplikacja Streamlit
├── auth.py                   # Moduł autentykacji (login/hasło)
├── tipper.py                 # Logika punktacji i parsowania
├── tipper_storage.py         # Przechowywanie danych (JSON)
├── hattrick_oauth_simple.py  # Klient OAuth dla Hattrick API
├── generate_password.py      # Skrypt do generowania hash hasła
├── requirements.txt          # Zależności Python
├── README.md                # Ten plik
├── .env                      # Zmienne środowiskowe (nie commituj!)
└── tipper_data.json         # Dane typera (tworzy się automatycznie)
```

## 🔧 Użycie

1. **Wybór drużyn**: W sidebarze zaznacz drużyny, które chcesz uwzględnić w typerze
2. **Wybór rundy**: Wybierz kolejkę z listy
3. **Wprowadzanie typów**:
   - Wybierz gracza z listy (lub dodaj nowego)
   - Wprowadź typy pojedynczo lub wklej wszystkie naraz (bulk)
   - Typy zapisują się automatycznie po wyjściu z pola
4. **Ranking**: Sprawdź ranking per kolejka lub ranking całości

## ☁️ Wgrywanie danych do Streamlit Community Cloud

Jeśli opublikowałeś aplikację w Streamlit Community Cloud i chcesz wgrać już zapisane dane (`tipper_data.json`), masz kilka opcji:

### Metoda 1: Przez interfejs aplikacji (Zalecane) ⭐

1. **Zaloguj się** do aplikacji w Streamlit Cloud
2. W **sidebarze** znajdź sekcję **"💾 Import/Eksport danych"**
3. Kliknij **"📤 Import danych z pliku"** (expander)
4. **Wgraj plik** `tipper_data.json` z komputera
5. Sprawdź podsumowanie danych (liczba graczy, rund)
6. Kliknij **"💾 Zaimportuj dane"**
7. ✅ Dane zostały zaimportowane!

### Metoda 2: Przez GitHub (jeśli repo jest połączone)

1. **Dodaj plik** `tipper_data.json` do repozytorium GitHub
2. **Commit i push** zmian
3. Streamlit Cloud **automatycznie zaktualizuje** aplikację
4. Plik zostanie wczytany przy następnym uruchomieniu

⚠️ **Uwaga**: Jeśli używasz `.gitignore`, upewnij się że `tipper_data.json` **nie jest** ignorowany (lub usuń go z `.gitignore` tymczasowo).

### Metoda 3: Przez Streamlit Cloud File Manager

1. Wejdź do **Streamlit Cloud Dashboard**
2. Wybierz swoją aplikację
3. Przejdź do **"Files"** lub **"Manage app"**
4. **Wgraj plik** `tipper_data.json` przez interfejs
5. Plik zostanie zapisany w katalogu głównym aplikacji

### Eksport danych (Backup)

Aby pobrać backup danych z aplikacji:
1. W sidebarze kliknij **"📥 Pobierz backup danych"**
2. Kliknij **"⬇️ Pobierz plik JSON"**
3. Plik zostanie pobrany na Twój komputer

💡 **Wskazówka**: Regularnie rób backup danych używając funkcji eksportu!

## 🗄️ Konfiguracja bazy danych MySQL (dla Streamlit Cloud)

Aby zapewnić trwałość danych na Streamlit Cloud, możesz użyć zewnętrznej bazy danych MySQL. Aplikacja automatycznie wykryje konfigurację MySQL i użyje jej zamiast pliku JSON.

### Krok 1: Utwórz bazę danych MySQL

1. **Wybierz dostawcę bazy danych:**
   - **Amazon RDS** (AWS)
   - **Google Cloud SQL**
   - **Azure Database for MySQL**
   - **PlanetScale** (darmowy tier)
   - **Railway** (darmowy tier)
   - **Aiven** (darmowy tier)
   - Inne dostawcy MySQL

2. **Utwórz bazę danych** i zapisz dane dostępowe:
   - Host (adres serwera)
   - Port (domyślnie 3306)
   - Nazwa bazy danych
   - Nazwa użytkownika
   - Hasło

### Krok 2: Utwórz strukturę bazy danych

Uruchom skrypt SQL z pliku `database_schema.sql` w swojej bazie danych:

```sql
-- Skopiuj zawartość pliku database_schema.sql i uruchom w swojej bazie MySQL
```

Lub użyj narzędzia do zarządzania bazą danych (np. phpMyAdmin, MySQL Workbench) i zaimportuj plik `database_schema.sql`.

### Krok 3: Skonfiguruj Streamlit Secrets

1. **W Streamlit Cloud:**
   - Przejdź do **Dashboard** → **Manage app** → **Secrets**
   - Dodaj następującą konfigurację:

```toml
[connections.mysql]
dialect = "mysql"
host = "twoj_host_mysql"
port = 3306
database = "nazwa_bazy_danych"
username = "nazwa_uzytkownika"
password = "haslo"
```

2. **Lokalnie (opcjonalnie):**
   - Utwórz folder `.streamlit` w katalogu głównym projektu
   - Utwórz plik `secrets.toml` z powyższą konfiguracją
   - ⚠️ **Uwaga**: Dodaj `.streamlit/secrets.toml` do `.gitignore` aby nie commitować haseł!

### Krok 4: Zainstaluj zależności

Zależności MySQL są już dodane do `requirements.txt`:
- `sqlalchemy>=2.0.0`
- `pymysql>=1.1.0`

### Jak to działa?

- **Bez MySQL**: Aplikacja używa pliku `tipper_data.json` (działa lokalnie, ale dane znikają po restarcie na Streamlit Cloud)
- **Z MySQL**: Aplikacja automatycznie wykrywa konfigurację MySQL w Streamlit Secrets i używa bazy danych (dane są trwałe na Streamlit Cloud)

### Migracja danych z JSON do MySQL

Jeśli masz już dane w pliku `tipper_data.json`:

1. **Eksportuj dane** z aplikacji (przycisk "📥 Pobierz backup danych")
2. **Skonfiguruj MySQL** (kroki powyżej)
3. **Zaimportuj dane** przez interfejs aplikacji (przycisk "📤 Import danych z pliku")
4. ✅ Dane zostaną automatycznie zapisane do MySQL

### Bezpieczeństwo

- ✅ Hasła są przechowywane w Streamlit Secrets (szyfrowane)
- ✅ Połączenia z bazą danych są szyfrowane (SSL/TLS)
- ✅ Użyj silnych haseł dla bazy danych
- ✅ Ogranicz dostęp do bazy danych tylko z IP Streamlit Cloud (jeśli możliwe)

## 📝 Format wprowadzania typów (bulk)

```
Nazwa drużyny1 - Nazwa drużyny2 Wynik
```

Przykład:
```
Borciuchy International - WKS BRONEK 50 7:0
Moli Team - Szmacianka Szynwałdzian 1:1
LegiaWawa - ks Jastrowie 2:1
```

## 🐛 Rozwiązywanie problemów

### Błąd: "Brak kluczy OAuth"
- Sprawdź czy plik `.env` istnieje i zawiera wszystkie wymagane klucze
- Uruchom skrypt autoryzacji OAuth

### Błąd: "Nie udało się pobrać meczów"
- Sprawdź połączenie z internetem
- Sprawdź czy ID lig są poprawne
- Sprawdź czy klucze OAuth są ważne

## 📄 Licencja

Ten projekt jest częścią większego projektu Hattrick Predictor.

