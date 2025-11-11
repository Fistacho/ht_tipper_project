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

1. **Przy starcie aplikacji**: Dane są ładowane z GitHub (jeśli plik istnieje) lub lokalnie
2. **Przy zapisie danych**: Dane są zapisywane do GitHub przez API (jeśli skonfigurowane) lub lokalnie
3. **Fallback**: Jeśli GitHub API nie jest skonfigurowane, aplikacja działa normalnie z lokalnym plikiem

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

