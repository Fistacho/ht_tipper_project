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
        
        # Normalizuj nazwy drużyn (usuń białe znaki, zamień na małe litery, usuń dodatkowe spacje)
        def normalize_name(name: str) -> str:
            # Usuń białe znaki na początku i końcu
            name = name.strip()
            # Zamień na małe litery
            name = name.lower()
            # Usuń wielokrotne spacje
            name = re.sub(r'\s+', ' ', name)
            # Usuń znaki interpunkcyjne na końcu (np. kropki, przecinki)
            name = re.sub(r'[.,;:!?]+$', '', name)
            return name
        
        # Stwórz mapę nazw drużyn -> mecze (z różnymi wariantami normalizacji)
        matches_by_names = {}
        logger.info(f"parse_match_predictions: Przetwarzam {len(matches)} meczów")
        for match in matches:
            home_name_raw = match.get('home_team_name', '')
            away_name_raw = match.get('away_team_name', '')
            match_id = str(match.get('match_id', ''))
            
            # Normalizuj nazwy
            home_name = normalize_name(home_name_raw)
            away_name = normalize_name(away_name_raw)
            
            logger.debug(f"  Mecz {match_id}: '{home_name_raw}' -> '{home_name}' vs '{away_name_raw}' -> '{away_name}'")
            
            # Klucz podstawowy: "home_name - away_name"
            key = f"{home_name} - {away_name}"
            matches_by_names[key] = match_id
            
            # Również odwrotna kolejność (na wypadek gdyby ktoś podał odwrotnie)
            key_reverse = f"{away_name} - {home_name}"
            matches_by_names[key_reverse] = match_id
            
            # Dodatkowe warianty: bez spacji wokół "-"
            key_no_spaces = f"{home_name}-{away_name}"
            matches_by_names[key_no_spaces] = match_id
            key_reverse_no_spaces = f"{away_name}-{home_name}"
            matches_by_names[key_reverse_no_spaces] = match_id
        
        logger.info(f"parse_match_predictions: Utworzono {len(matches_by_names)} kluczy dopasowania")
        
        for line in lines:
            line = line.strip()
            if not line:
                continue
            
            # Szukaj wzorca: "Nazwa1 - Nazwa2 Wynik"
            # Wynik może być w formacie: 7:0, 7-0, 7 0
            # Najpierw spróbuj znaleźć wynik na końcu linii (obsługuj zarówno ":" jak i "-")
            result_pattern = r'(\d+)\s*[-:]\s*(\d+)\s*$'
            result_match = re.search(result_pattern, line)
            
            if result_match:
                home_goals = int(result_match.group(1))
                away_goals = int(result_match.group(2))
                
                # Wyciągnij nazwy drużyn (wszystko przed wynikiem)
                teams_part = line[:result_match.start()].strip()
                
                # Podziel na dwie drużyny (separator: " - " lub " -" lub "-" bez spacji)
                # Użyj bardziej elastycznego wzorca
                team_split = re.split(r'\s*-\s*', teams_part, 1)
                
                # Jeśli nie znaleziono separatora z spacjami, spróbuj bez spacji
                if len(team_split) < 2:
                    team_split = re.split(r'-', teams_part, 1)
                
                if len(team_split) == 2:
                    team1_name = normalize_name(team_split[0])
                    team2_name = normalize_name(team_split[1])
                    
                    # Walidacja: wyniki powinny być nieujemne i rozsądne (max 20)
                    if 0 <= home_goals <= 20 and 0 <= away_goals <= 20:
                        # Spróbuj dopasować do meczu (sprawdź różne warianty)
                        match_id = None
                        
                        # Wariant 1: "team1 - team2" (ze spacjami)
                        key = f"{team1_name} - {team2_name}"
                        match_id = matches_by_names.get(key)
                        
                        # Wariant 2: "team1-team2" (bez spacji)
                        if not match_id:
                            key_no_spaces = f"{team1_name}-{team2_name}"
                            match_id = matches_by_names.get(key_no_spaces)
                        
                        # Wariant 3: odwrotna kolejność ze spacjami
                        if not match_id:
                            key_reverse = f"{team2_name} - {team1_name}"
                            match_id = matches_by_names.get(key_reverse)
                            if match_id:
                                # Jeśli odwrotna kolejność, zamień wyniki
                                home_goals, away_goals = away_goals, home_goals
                        
                        # Wariant 4: odwrotna kolejność bez spacji
                        if not match_id:
                            key_reverse_no_spaces = f"{team2_name}-{team1_name}"
                            match_id = matches_by_names.get(key_reverse_no_spaces)
                            if match_id:
                                # Jeśli odwrotna kolejność, zamień wyniki
                                home_goals, away_goals = away_goals, home_goals
                        
                        # Wariant 5: częściowe dopasowanie (jeśli dokładne nie działa)
                        if not match_id:
                            # Spróbuj znaleźć mecz przez częściowe dopasowanie nazw
                            # Najpierw znajdź najlepsze dopasowanie (najwięcej wspólnych słów)
                            best_match = None
                            best_score = 0
                            
                            for key, mid in matches_by_names.items():
                                # Podziel klucz na części
                                key_parts = re.split(r'\s*-\s*', key)
                                if len(key_parts) != 2:
                                    continue
                                
                                key_team1 = key_parts[0].strip()
                                key_team2 = key_parts[1].strip()
                                
                                # Sprawdź dopasowanie dla pierwszej drużyny (normalna kolejność)
                                team1_words = set(team1_name.split())
                                team2_words = set(team2_name.split())
                                key_team1_words = set(key_team1.split())
                                key_team2_words = set(key_team2.split())
                                
                                # Normalna kolejność: team1 vs team2
                                # Użyj podobieństwa Jaccard (wspólne słowa / wszystkie słowa)
                                team1_intersection = len(team1_words & key_team1_words)
                                team1_union = len(team1_words | key_team1_words)
                                team1_match_score = team1_intersection / max(team1_union, 1)
                                
                                team2_intersection = len(team2_words & key_team2_words)
                                team2_union = len(team2_words | key_team2_words)
                                team2_match_score = team2_intersection / max(team2_union, 1)
                                
                                # Obniż próg dopasowania do 0.3 (30%) dla każdej drużyny
                                if team1_match_score >= 0.3 and team2_match_score >= 0.3:
                                    total_score = team1_match_score + team2_match_score
                                    if total_score > best_score:
                                        best_score = total_score
                                        best_match = (mid, False)  # False = normalna kolejność
                                
                                # Odwrotna kolejność: team1 vs team2 (zamienione)
                                team1_intersection_rev = len(team1_words & key_team2_words)
                                team1_union_rev = len(team1_words | key_team2_words)
                                team1_match_score_rev = team1_intersection_rev / max(team1_union_rev, 1)
                                
                                team2_intersection_rev = len(team2_words & key_team1_words)
                                team2_union_rev = len(team2_words | key_team1_words)
                                team2_match_score_rev = team2_intersection_rev / max(team2_union_rev, 1)
                                
                                if team1_match_score_rev >= 0.3 and team2_match_score_rev >= 0.3:
                                    total_score = team1_match_score_rev + team2_match_score_rev
                                    if total_score > best_score:
                                        best_score = total_score
                                        best_match = (mid, True)  # True = odwrotna kolejność
                            
                            # Obniż próg całkowitego dopasowania do 0.6 (zamiast 1.0)
                            if best_match and best_score >= 0.6:  # Minimum 30% dopasowania dla każdej drużyny, łącznie 60%
                                match_id, is_reversed = best_match
                                if is_reversed:
                                    home_goals, away_goals = away_goals, home_goals
                                logger.info(f"✅ Częściowe dopasowanie dla: {line} -> match_id={match_id}, score={best_score:.2f}")
                            elif best_match:
                                logger.debug(f"⚠️ Częściowe dopasowanie zbyt niskie: {line} -> score={best_score:.2f} (wymagane >= 0.6)")
                        
                        if match_id:
                            result[match_id] = (home_goals, away_goals)
                            logger.info(f"✅ Znaleziono mecz dla: {line} -> match_id={match_id}, wynik={home_goals}-{away_goals}")
                        else:
                            logger.warning(f"❌ Nie znaleziono meczu dla: {line}")
                            logger.warning(f"  Znormalizowane nazwy: '{team1_name}' - '{team2_name}'")
                            # Debug: pokaż wszystkie dostępne mecze
                            logger.warning(f"  Dostępne mecze ({len(matches_by_names)}):")
                            for i, (key, mid) in enumerate(list(matches_by_names.items())[:20]):
                                logger.warning(f"    {i+1}. {key} (match_id={mid})")
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

