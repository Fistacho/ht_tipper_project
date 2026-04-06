# 🔧 Konfiguracja GitHub API dla zapisu danych

Aplikacja może zapisywać dane bezpośrednio do repozytorium GitHub przez GitHub API. To pozwala na trwałe przechowywanie danych na Streamlit Cloud.

## 📋 Wymagania

1. **GitHub Personal Access Token (PAT)** z uprawnieniami do zapisu w repozytorium
2. **Nazwa właściciela repozytorium** (np. `twoja-nazwa-uzytkownika`)
3. **Nazwa repozytorium** (np. `ht_tipper_project`)

## 🔑 Jak utworzyć GitHub Personal Access Token

1. Przejdź do **GitHub Settings** → **Developer settings** → **Personal access tokens** → **Tokens (classic)**
2. Kliknij **"Generate new token"** → **"Generate new token (classic)"**
3. Nadaj tokenowi nazwę (np. `Streamlit Tipper App`)
4. Wybierz uprawnienia:
   - ✅ **`repo`** (pełny dostęp do repozytorium) - **WYMAGANE**
5. Kliknij **"Generate token"**
6. **Skopiuj token** (będzie widoczny tylko raz!)

## ⚙️ Konfiguracja

### Dla lokalnego rozwoju (`.env`)

Dodaj do pliku `.env`:

```env
GITHUB_TOKEN=ghp_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
GITHUB_REPO_OWNER=twoja-nazwa-uzytkownika
GITHUB_REPO_NAME=ht_tipper_project
```

### Dla Streamlit Cloud (Secrets)

1. Przejdź do **Streamlit Cloud Dashboard**
2. Wybierz swoją aplikację
3. Kliknij **"Settings"** → **"Secrets"**
4. Dodaj:

```toml
GITHUB_TOKEN = "ghp_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
GITHUB_REPO_OWNER = "twoja-nazwa-uzytkownika"
GITHUB_REPO_NAME = "ht_tipper_project"
```

## ✅ Jak to działa

1. **Stan roboczy aplikacji**: aplikacja pracuje na lokalnym pliku JSON i przy rerunach przeładowuje lokalny stan, a nie GitHub.
2. **Ręczny zapis**: `flush_save()` zapisuje lokalnie i od razu wysyła backup do GitHub.
3. **Backup okresowy**: jeśli lokalny stan zmienił się od ostatniego backupu, aplikacja spróbuje wysłać go do GitHub przy następnym rerunie po upływie 1 godziny.
4. **Pierwsze uruchomienie / recovery**: jeśli lokalny plik nie istnieje, aplikacja może pobrać stan startowy z GitHub i odtworzyć lokalny plik roboczy.
5. **Fallback**: jeśli GitHub API nie jest skonfigurowane albo backup się nie uda, aplikacja dalej działa na lokalnym pliku.

## ⏱️ Interwał backupu

Domyślny interwał okresowego backupu do GitHub wynosi 3600 sekund (1 godzina).

Możesz go zmienić przez zmienną środowiskową:

```env
TIPPER_GITHUB_BACKUP_INTERVAL_SECONDS=3600
```

Uwaga: w Streamlit backup okresowy wykona się przy kolejnym rerunie aplikacji po przekroczeniu tego interwału. Aplikacja nie uruchamia osobnego procesu w tle.

## 🔒 Bezpieczeństwo

- **NIGDY** nie commituj tokenu do repozytorium!
- Token powinien być tylko w `.env` (lokalnie) lub Streamlit Secrets (Cloud)
- Jeśli token zostanie ujawniony, natychmiast go odwołaj i utwórz nowy

## 📝 Przykład

Jeśli Twoje repozytorium to: `https://github.com/jan-kowalski/ht_tipper_project`

To w `.env` lub Secrets wpisz:

```env
GITHUB_TOKEN=ghp_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
GITHUB_REPO_OWNER=jan-kowalski
GITHUB_REPO_NAME=ht_tipper_project
```

## 🐛 Rozwiązywanie problemów

### Błąd: "Bad credentials"

- Sprawdź czy token jest poprawny
- Sprawdź czy token ma uprawnienia `repo`

### Błąd: "Not found"

- Sprawdź czy `GITHUB_REPO_OWNER` i `GITHUB_REPO_NAME` są poprawne
- Sprawdź czy repozytorium istnieje i masz do niego dostęp

### Dane nie zapisują się

- Sprawdź logi aplikacji (`tipper.log`)
- Sprawdź czy token ma uprawnienia do zapisu (`repo`)

Jeśli problem nadal występuje, sprawdź odpowiedź GitHub API zapisaną w `tipper.log`.
To zwykle wystarcza do ustalenia, czy problem dotyczy tokenu, uprawnień albo ścieżki pliku.
