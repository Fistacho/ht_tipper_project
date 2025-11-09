"""
Moduł typera - logika punktacji i parsowania typów
"""
import re
from typing import Dict, Optional, Tuple, List
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


class Tipper:
    """Klasa obsługująca logikę typera"""
    
    @staticmethod
    def parse_prediction(prediction_text: str) -> Optional[Tuple[int, int]]:
        """
        Parsuje typ z tekstu w różnych formatach
        
        Obsługiwane formaty:
        - 2-0, 2:0
        - 2 - 0, 2 : 0
        - 2:0, 2-0 (z dodatkowymi spacjami)
        
        Returns:
            Tuple[int, int] lub None jeśli nie można sparsować
        """
        if not prediction_text:
            return None
        
        # Usuń białe znaki
        text = prediction_text.strip()
        
        # Spróbuj różne separatory: -, :, spacja
        patterns = [
            r'(\d+)\s*[-:]\s*(\d+)',  # 2-0, 2:0, 2 - 0, 2 : 0
            r'(\d+)\s+(\d+)',  # 2 0 (spacja jako separator)
        ]
        
        for pattern in patterns:
            match = re.match(pattern, text)
            if match:
                try:
                    home = int(match.group(1))
                    away = int(match.group(2))
                    # Walidacja: wyniki powinny być nieujemne i rozsądne (max 20)
                    if 0 <= home <= 20 and 0 <= away <= 20:
                        return (home, away)
                except ValueError:
                    continue
        
        return None
    
    @staticmethod
    def calculate_points(prediction: Tuple[int, int], actual_result: Tuple[int, int]) -> int:
        """
        Oblicza punkty za typ zgodnie z regulaminem:
        - Dokładny wynik: 12 punktów
        - Prawidłowy rezultat (zwycięstwo/remis): 10 punktów
        - Nieprawidłowy rezultat: 5 punktów
        - Odejmujemy różnicę bramek (gospodarze i goście osobno)
        - Nie dopuszcza się wartości ujemnych
        
        Args:
            prediction: (home_goals, away_goals) - typ
            actual_result: (home_goals, away_goals) - rzeczywisty wynik
            
        Returns:
            Liczba punktów (minimum 0)
        """
        pred_home, pred_away = prediction
        actual_home, actual_away = actual_result
        
        # Sprawdź dokładny wynik
        if pred_home == actual_home and pred_away == actual_away:
            return 12
        
        # Określ rezultat (zwycięstwo gospodarzy, remis, zwycięstwo gości)
        def get_result(home: int, away: int) -> str:
            if home > away:
                return 'home_win'
            elif home < away:
                return 'away_win'
            else:
                return 'draw'
        
        pred_result = get_result(pred_home, pred_away)
        actual_result_type = get_result(actual_home, actual_away)
        
        # Sprawdź czy rezultat jest prawidłowy
        if pred_result == actual_result_type:
            base_points = 10
        else:
            base_points = 5
        
        # Odejmij różnicę bramek (gospodarze i goście osobno)
        home_diff = abs(pred_home - actual_home)
        away_diff = abs(pred_away - actual_away)
        
        total_points = base_points - home_diff - away_diff
        
        # Nie dopuszcza się wartości ujemnych
        return max(0, total_points)
    
    @staticmethod
    def get_result_type(home_goals: int, away_goals: int) -> str:
        """Zwraca typ rezultatu: 'home_win', 'away_win', 'draw'"""
        if home_goals > away_goals:
            return 'home_win'
        elif home_goals < away_goals:
            return 'away_win'
        else:
            return 'draw'
    
    @staticmethod
    def format_prediction(prediction: Tuple[int, int]) -> str:
        """Formatuje typ do wyświetlenia: 2-0"""
        return f"{prediction[0]}-{prediction[1]}"
    
    @staticmethod
    def parse_bulk_predictions(text: str) -> Dict[str, Tuple[int, int]]:
        """
        Parsuje wiele typów z tekstu (jeden typ na linię)
        
        Format:
        Nazwa gracza: 2-0
        Lub:
        Nazwa gracza 2-0
        Lub:
        2-0 (tylko wynik, bez nazwy)
        
        Returns:
            Dict z nazwą gracza -> (home, away) lub None jeśli nie można sparsować
        """
        predictions = {}
        lines = text.strip().split('\n')
        
        for line in lines:
            line = line.strip()
            if not line:
                continue
            
            # Spróbuj znaleźć typ w linii
            prediction = Tipper.parse_prediction(line)
            if prediction:
                # Spróbuj wyciągnąć nazwę gracza (wszystko przed typem)
                # Usuń typ z linii, zostanie nazwa
                pattern = r'(\d+)\s*[-:]\s*(\d+)'
                match = re.search(pattern, line)
                if match:
                    # Nazwa gracza to wszystko przed typem
                    player_name = line[:match.start()].strip()
                    # Usuń dwukropek i inne znaki interpunkcyjne na końcu
                    player_name = re.sub(r'[:;,\-]+$', '', player_name).strip()
                    
                    if not player_name:
                        # Jeśli nie ma nazwy, użyj "Gracz {numer}"
                        player_name = f"Gracz {len(predictions) + 1}"
                    
                    predictions[player_name] = prediction
        
        return predictions
    
    @staticmethod
    def parse_match_predictions(text: str, matches: List[Dict]) -> Dict[str, Tuple[int, int]]:
        """
        Parsuje typy w formacie: "Nazwa drużyny1 - Nazwa drużyny2 Wynik"
        i dopasowuje je do meczów na podstawie nazw drużyn
        
        Args:
            text: Tekst z typami (jeden typ na linię)
            matches: Lista meczów z polami 'home_team_name' i 'away_team_name'
            
        Returns:
            Dict z match_id -> (home, away) dla dopasowanych meczów
        """
        result = {}
        # Podziel na linie i usuń puste linie na początku/końcu
        lines = [line.strip() for line in text.strip().split('\n')]
        # Usuń puste linie
        lines = [line for line in lines if line]
        
        # Normalizuj nazwy drużyn (usuń białe znaki, zamień na małe litery)
        def normalize_name(name: str) -> str:
            return name.strip().lower()
        
        # Stwórz mapę nazw drużyn -> mecze
        matches_by_names = {}
        for match in matches:
            home_name = normalize_name(match.get('home_team_name', ''))
            away_name = normalize_name(match.get('away_team_name', ''))
            match_id = str(match.get('match_id', ''))
            
            # Klucz: "home_name - away_name"
            key = f"{home_name} - {away_name}"
            matches_by_names[key] = match_id
            
            # Również odwrotna kolejność (na wypadek gdyby ktoś podał odwrotnie)
            key_reverse = f"{away_name} - {home_name}"
            matches_by_names[key_reverse] = match_id
        
        for line in lines:
            line = line.strip()
            if not line:
                continue
            
            # Szukaj wzorca: "Nazwa1 - Nazwa2 Wynik"
            # Wynik może być w formacie: 7:0, 7-0, 7 0
            # Najpierw spróbuj znaleźć wynik na końcu linii
            result_pattern = r'(\d+)\s*[-:]\s*(\d+)\s*$'
            result_match = re.search(result_pattern, line)
            
            if result_match:
                home_goals = int(result_match.group(1))
                away_goals = int(result_match.group(2))
                
                # Wyciągnij nazwy drużyn (wszystko przed wynikiem)
                teams_part = line[:result_match.start()].strip()
                
                # Podziel na dwie drużyny (separator: " - " lub " -")
                team_split = re.split(r'\s*-\s*', teams_part, 1)
                
                if len(team_split) == 2:
                    team1_name = normalize_name(team_split[0])
                    team2_name = normalize_name(team_split[1])
                    
                    # Walidacja: wyniki powinny być nieujemne i rozsądne (max 20)
                    if 0 <= home_goals <= 20 and 0 <= away_goals <= 20:
                        # Spróbuj dopasować do meczu
                        key = f"{team1_name} - {team2_name}"
                        match_id = matches_by_names.get(key)
                        
                        if match_id:
                            result[match_id] = (home_goals, away_goals)
                        else:
                            # Spróbuj odwrotną kolejność
                            key_reverse = f"{team2_name} - {team1_name}"
                            match_id = matches_by_names.get(key_reverse)
                            if match_id:
                                # Jeśli odwrotna kolejność, zamień wyniki
                                result[match_id] = (away_goals, home_goals)
                            else:
                                logger.warning(f"Nie znaleziono meczu dla: {line}")
                                # Debug: pokaż dostępne mecze
                                available_keys = list(matches_by_names.keys())[:5]
                                logger.debug(f"Dostępne mecze (pierwsze 5): {available_keys}")
                else:
                    logger.warning(f"Nieprawidłowy format linii (brak separatora '-'): {line}")
            else:
                # Spróbuj prostszy format: tylko wynik (bez nazw drużyn)
                prediction = Tipper.parse_prediction(line)
                if prediction:
                    # Jeśli nie ma nazw drużyn, nie możemy dopasować do meczu
                    logger.warning(f"Nie można sparsować linii (brak nazw drużyn): {line}")
        
        return result
    
    @staticmethod
    def validate_match_time(match_date: str, prediction_time: Optional[datetime] = None) -> bool:
        """
        Sprawdza czy typ został oddany przed rozpoczęciem meczu
        
        Args:
            match_date: Data meczu w formacie Hattrick (np. "2024-10-26 09:00:00")
            prediction_time: Czas oddania typów (domyślnie teraz)
            
        Returns:
            True jeśli typ jest przed meczem, False w przeciwnym razie
        """
        if not match_date:
            return False
        
        try:
            # Parsuj datę meczu
            match_dt = datetime.strptime(match_date, "%Y-%m-%d %H:%M:%S")
            
            # Jeśli nie podano czasu typów, użyj teraz
            if prediction_time is None:
                prediction_time = datetime.now()
            
            return prediction_time < match_dt
        except ValueError:
            logger.error(f"Nie można sparsować daty meczu: {match_date}")
            return False

