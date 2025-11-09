"""
Skrypt pomocniczy do generowania hash hasła dla konfiguracji
"""
from auth import generate_password_hash

if __name__ == "__main__":
    print("=" * 50)
    print("Generator hash hasła dla Hattrick Typer")
    print("=" * 50)
    print()
    
    password = input("Wprowadź hasło: ")
    
    if not password:
        print("❌ Hasło nie może być puste")
        exit(1)
    
    hashed, salt = generate_password_hash(password)
    
    print()
    print("=" * 50)
    print("Skopiuj poniższe wartości do pliku .env:")
    print("=" * 50)
    print()
    print(f"APP_PASSWORD_HASH={hashed}")
    print(f"APP_PASSWORD_SALT={salt}")
    print()
    print("=" * 50)

