"""
Moduł autentykacji dla aplikacji Hattrick Typer
"""
import streamlit as st
import hashlib
import os
from typing import Optional, Dict
from dotenv import load_dotenv
import logging

logger = logging.getLogger(__name__)


def hash_password(password: str, salt: str = None) -> tuple:
    """
    Haszuje hasło używając SHA256 z solą
    
    Args:
        password: Hasło do zahaszowania
        salt: Opcjonalna sól (jeśli None, zostanie wygenerowana)
        
    Returns:
        Tuple (hashed_password, salt)
    """
    if salt is None:
        # Generuj sól z hasła (dla prostoty, w produkcji użyj secrets.token_hex)
        salt = hashlib.sha256(password.encode()).hexdigest()[:16]
    
    # Haszuj hasło z solą
    hashed = hashlib.sha256((password + salt).encode()).hexdigest()
    return hashed, salt


def verify_password(password: str, hashed_password: str, salt: str) -> bool:
    """
    Weryfikuje hasło
    
    Args:
        password: Hasło do sprawdzenia
        hashed_password: Zahaszowane hasło
        salt: Sól użyta do haszowania
        
    Returns:
        True jeśli hasło jest poprawne, False w przeciwnym razie
    """
    hashed, _ = hash_password(password, salt)
    return hashed == hashed_password


def load_users() -> Dict[str, Dict[str, str]]:
    """
    Ładuje użytkowników z zmiennych środowiskowych
    
    Format w .env:
    APP_USERNAME=admin
    APP_PASSWORD_HASH=hashed_password
    APP_PASSWORD_SALT=salt
    
    Lub dla wielu użytkowników:
    APP_USER_1_USERNAME=user1
    APP_USER_1_PASSWORD_HASH=hash1
    APP_USER_1_PASSWORD_SALT=salt1
    APP_USER_2_USERNAME=user2
    APP_USER_2_PASSWORD_HASH=hash2
    APP_USER_2_PASSWORD_SALT=salt2
    
    Returns:
        Dict z username -> {password_hash, salt}
    """
    load_dotenv()
    users = {}
    
    # Sprawdź pojedynczego użytkownika (stary format)
    username = os.getenv('APP_USERNAME')
    password_hash = os.getenv('APP_PASSWORD_HASH')
    password_salt = os.getenv('APP_PASSWORD_SALT')
    
    if username and password_hash and password_salt:
        users[username] = {
            'password_hash': password_hash,
            'salt': password_salt
        }
    
    # Sprawdź wielu użytkowników (nowy format)
    i = 1
    while True:
        user_username = os.getenv(f'APP_USER_{i}_USERNAME')
        user_password_hash = os.getenv(f'APP_USER_{i}_PASSWORD_HASH')
        user_password_salt = os.getenv(f'APP_USER_{i}_PASSWORD_SALT')
        
        if not user_username:
            break
        
        if user_password_hash and user_password_salt:
            users[user_username] = {
                'password_hash': user_password_hash,
                'salt': user_password_salt
            }
        i += 1
    
    # Jeśli nie ma żadnych użytkowników, utwórz domyślnego
    if not users:
        logger.warning("Brak skonfigurowanych użytkowników, używam domyślnego (admin/admin)")
        default_hash, default_salt = hash_password("admin")
        users["admin"] = {
            'password_hash': default_hash,
            'salt': default_salt
        }
    
    return users


def check_authentication() -> bool:
    """
    Sprawdza czy użytkownik jest zalogowany
    
    Returns:
        True jeśli użytkownik jest zalogowany, False w przeciwnym razie
    """
    return st.session_state.get('authenticated', False)


def login_page() -> bool:
    """
    Wyświetla stronę logowania i weryfikuje dane
    
    Returns:
        True jeśli logowanie się powiodło, False w przeciwnym razie
    """
    st.title("🔐 Logowanie do Hattrick Typer")
    st.markdown("---")
    
    users = load_users()
    
    if not users:
        st.error("❌ Brak skonfigurowanych użytkowników. Skonfiguruj użytkowników w pliku .env")
        return False
    
    with st.form("login_form"):
        username = st.text_input("👤 Nazwa użytkownika", key="login_username")
        password = st.text_input("🔒 Hasło", type="password", key="login_password")
        submit_button = st.form_submit_button("🚀 Zaloguj się", use_container_width=True)
        
        if submit_button:
            if not username or not password:
                st.error("❌ Wprowadź nazwę użytkownika i hasło")
                return False
            
            if username in users:
                user_data = users[username]
                if verify_password(password, user_data['password_hash'], user_data['salt']):
                    st.session_state['authenticated'] = True
                    st.session_state['username'] = username
                    st.success(f"✅ Zalogowano jako {username}")
                    st.rerun()
                else:
                    st.error("❌ Nieprawidłowe hasło")
                    return False
            else:
                st.error("❌ Nieprawidłowa nazwa użytkownika")
                return False
    
    return False


def logout():
    """Wylogowuje użytkownika"""
    if 'authenticated' in st.session_state:
        del st.session_state['authenticated']
    if 'username' in st.session_state:
        del st.session_state['username']
    st.rerun()


def require_auth(func):
    """
    Dekorator wymagający autentykacji przed wykonaniem funkcji
    
    Usage:
        @require_auth
        def my_function():
            ...
    """
    def wrapper(*args, **kwargs):
        if not check_authentication():
            if not login_page():
                return
        return func(*args, **kwargs)
    return wrapper


def generate_password_hash(password: str) -> tuple:
    """
    Generuje hash i sól dla hasła (użyteczne do konfiguracji)
    
    Args:
        password: Hasło do zahaszowania
        
    Returns:
        Tuple (hashed_password, salt) - użyj tych wartości w .env
    """
    hashed, salt = hash_password(password)
    return hashed, salt

