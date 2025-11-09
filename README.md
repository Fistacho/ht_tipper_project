# 🎯 Hattrick Typer

Aplikacja do prowadzenia typera dla lig Hattrick. Pozwala na wprowadzanie typów, śledzenie wyników i wyświetlanie rankingów.

## 📋 Funkcje

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

4. Uruchom aplikację:
```bash
streamlit run app.py
```

## ⚙️ Konfiguracja

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
├── tipper.py                 # Logika punktacji i parsowania
├── tipper_storage.py         # Przechowywanie danych (JSON)
├── hattrick_oauth_simple.py  # Klient OAuth dla Hattrick API
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

