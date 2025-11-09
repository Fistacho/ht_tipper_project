"""
Prosty klient OAuth 1.0a dla Hattrick używający requests-oauthlib
"""
import requests
import xml.etree.ElementTree as ET
from typing import Dict, List, Optional, Any
import logging
from requests_oauthlib import OAuth1Session
import webbrowser
from urllib.parse import parse_qs

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class HattrickOAuthSimple:
    """Prosty klient OAuth 1.0a dla Hattrick używający requests-oauthlib"""
    
    def __init__(self, consumer_key: str, consumer_secret: str):
        self.consumer_key = consumer_key
        self.consumer_secret = consumer_secret
        self.access_token = None
        self.access_token_secret = None
        self.session = None
        
        # Endpointy OAuth zgodnie z dokumentacją
        self.base_url = "https://chpp.hattrick.org"
        self.request_token_url = f"{self.base_url}/oauth/request_token.ashx"
        self.authorize_url = f"{self.base_url}/oauth/authorize.aspx"
        self.access_token_url = f"{self.base_url}/oauth/access_token.ashx"
        self.api_url = f"{self.base_url}/chppxml.ashx"
    
    def get_authorization_url(self) -> Optional[str]:
        """Pobiera URL do autoryzacji"""
        try:
            # Utwórz sesję OAuth
            oauth = OAuth1Session(
                self.consumer_key,
                client_secret=self.consumer_secret,
                callback_uri='oob'  # out-of-band callback
            )
            
            # Pobierz request token
            request_token = oauth.fetch_request_token(self.request_token_url)
            
            # Zapisz tokeny tymczasowo
            self.access_token = request_token['oauth_token']
            self.access_token_secret = request_token['oauth_token_secret']
            
            # Wygeneruj URL autoryzacji
            authorization_url = oauth.authorization_url(self.authorize_url)
            
            return authorization_url
            
        except Exception as e:
            logger.error(f"Błąd pobierania URL autoryzacji: {e}")
            return None
    
    def get_access_token(self, verifier: str) -> Optional[Dict[str, str]]:
        """Pobiera access token"""
        try:
            # Utwórz sesję OAuth z request token
            oauth = OAuth1Session(
                self.consumer_key,
                client_secret=self.consumer_secret,
                resource_owner_key=self.access_token,
                resource_owner_secret=self.access_token_secret,
                verifier=verifier
            )
            
            # Pobierz access token
            access_token = oauth.fetch_access_token(self.access_token_url)
            
            # Zapisz tokeny
            self.access_token = access_token['oauth_token']
            self.access_token_secret = access_token['oauth_token_secret']
            
            # Utwórz sesję z access token
            self.session = OAuth1Session(
                self.consumer_key,
                client_secret=self.consumer_secret,
                resource_owner_key=self.access_token,
                resource_owner_secret=self.access_token_secret
            )
            
            return {
                'oauth_token': self.access_token,
                'oauth_token_secret': self.access_token_secret
            }
            
        except Exception as e:
            logger.error(f"Błąd pobierania access token: {e}")
            return None
    
    def set_access_tokens(self, access_token: str, access_token_secret: str):
        """Ustawia access tokeny"""
        self.access_token = access_token
        self.access_token_secret = access_token_secret
        
        # Utwórz sesję z tokenami
        self.session = OAuth1Session(
            self.consumer_key,
            client_secret=self.consumer_secret,
            resource_owner_key=self.access_token,
            resource_owner_secret=self.access_token_secret
        )
    
    def make_api_request(self, file: str, params: Dict[str, str] = None) -> Optional[ET.Element]:
        """Wykonuje zapytanie do API CHPP"""
        if not self.session:
            logger.error("Brak sesji OAuth")
            return None
        
        if params is None:
            params = {}
        
        # Dodaj parametr file
        params['file'] = file
        params['version'] = '1.0'
        
        try:
            response = self.session.get(self.api_url, params=params, timeout=30)
            response.raise_for_status()
            
            # Parsuj XML
            root = ET.fromstring(response.content)
            
            # Sprawdź czy nie ma błędów
            error = root.find('.//Error')
            if error is not None:
                logger.error(f"Błąd API: {error.text}")
                return None
            
            return root
            
        except Exception as e:
            logger.error(f"Błąd API request: {e}")
            return None
    
    def get_team_details(self, team_id: int) -> Optional[Dict[str, Any]]:
        """Pobiera szczegóły drużyny"""
        params = {'TeamID': str(team_id)}
        root = self.make_api_request('teamdetails', params)
        
        if root is None:
            return None
        
        team_info = {}
        team = root.find('.//Team')
        if team is not None:
            team_info['team_id'] = team.find('TeamID').text if team.find('TeamID') is not None else None
            team_info['team_name'] = team.find('TeamName').text if team.find('TeamName') is not None else None
            team_info['league_id'] = team.find('LeagueID').text if team.find('LeagueID') is not None else None
            team_info['league_name'] = team.find('LeagueName').text if team.find('LeagueName') is not None else None
        
        return team_info
    
    def get_league_details(self, league_level_unit_id: int) -> Optional[Dict[str, Any]]:
        """Pobiera szczegóły ligi"""
        params = {'LeagueLevelUnitID': str(league_level_unit_id)}
        root = self.make_api_request('leaguedetails', params)
        
        if root is None:
            return None
        
        # Pobierz sezon i rundę z leaguefixtures
        fixtures_root = self.make_api_request('leaguefixtures', params)
        season = None
        match_round = None
        
        if fixtures_root is not None:
            season = fixtures_root.find('Season').text if fixtures_root.find('Season') is not None else None
            # Znajdź aktualną rundę (najwyższą)
            rounds = []
            for match in fixtures_root.findall('.//Match'):
                round_elem = match.find('MatchRound')
                if round_elem is not None and round_elem.text:
                    rounds.append(int(round_elem.text))
            if rounds:
                match_round = max(rounds)
        
        # Prawdziwa struktura XML - dane są bezpośrednio w root
        league_info = {
            'league_id': root.find('LeagueLevelUnitID').text if root.find('LeagueLevelUnitID') is not None else None,  # Używamy LeagueLevelUnitID zamiast LeagueID
            'league_name': root.find('LeagueLevelUnitName').text if root.find('LeagueLevelUnitName') is not None else None,  # Używamy LeagueLevelUnitName zamiast LeagueName
            'league_level': root.find('LeagueLevel').text if root.find('LeagueLevel') is not None else None,
            'league_level_unit_name': root.find('LeagueLevelUnitName').text if root.find('LeagueLevelUnitName') is not None else None,
            'season': season or 'Current',
            'match_round': match_round or 'Unknown'
        }
        
        return league_info
    
    def get_league_table(self, league_level_unit_id: int) -> Optional[List[Dict[str, Any]]]:
        """Pobiera tabelę ligi z prawdziwymi danymi"""
        params = {'LeagueLevelUnitID': str(league_level_unit_id)}
        root = self.make_api_request('leaguedetails', params)
        
        if root is None:
            return None
        
        teams = []
        for team in root.findall('.//Team'):
            team_data = {
                'team_id': int(team.find('TeamID').text) if team.find('TeamID') is not None and team.find('TeamID').text is not None else None,
                'team_name': team.find('TeamName').text if team.find('TeamName') is not None else None,
                'position': int(team.find('Position').text) if team.find('Position') is not None and team.find('Position').text is not None else None,
                'position_change': int(team.find('PositionChange').text) if team.find('PositionChange') is not None and team.find('PositionChange').text is not None else None,
                'matches': int(team.find('Matches').text) if team.find('Matches') is not None and team.find('Matches').text is not None else None,
                'goals_for': int(team.find('GoalsFor').text) if team.find('GoalsFor') is not None and team.find('GoalsFor').text is not None else None,
                'goals_against': int(team.find('GoalsAgainst').text) if team.find('GoalsAgainst') is not None and team.find('GoalsAgainst').text is not None else None,
                'points': int(team.find('Points').text) if team.find('Points') is not None and team.find('Points').text is not None else None,
                'goal_difference': 0,  # Obliczymy to
                'wins': 0,  # Obliczymy to z meczów
                'draws': 0,  # Obliczymy to z meczów
                'losses': 0  # Obliczymy to z meczów
            }
            
            # Oblicz różnicę bramek
            if team_data['goals_for'] is not None and team_data['goals_against'] is not None:
                team_data['goal_difference'] = team_data['goals_for'] - team_data['goals_against']
            
            teams.append(team_data)
        
        return teams
    
    def get_league_fixtures(self, league_level_unit_id: int) -> Optional[Dict[str, Any]]:
        """Pobiera terminarz ligi wraz z informacją o sezonie"""
        params = {'LeagueLevelUnitID': str(league_level_unit_id)}
        root = self.make_api_request('leaguefixtures', params)
        
        if root is None:
            return None
        
        # Pobierz sezon z root
        season = root.find('Season').text if root.find('Season') is not None else None
        
        fixtures = []
        for match in root.findall('.//Match'):
            match_info = {
                'match_id': match.find('MatchID').text if match.find('MatchID') is not None else None,
                'home_team_id': match.find('HomeTeam/HomeTeamID').text if match.find('HomeTeam/HomeTeamID') is not None else None,
                'home_team_name': match.find('HomeTeam/HomeTeamName').text if match.find('HomeTeam/HomeTeamName') is not None else None,
                'away_team_id': match.find('AwayTeam/AwayTeamID').text if match.find('AwayTeam/AwayTeamID') is not None else None,
                'away_team_name': match.find('AwayTeam/AwayTeamName').text if match.find('AwayTeam/AwayTeamName') is not None else None,
                'match_date': match.find('MatchDate').text if match.find('MatchDate') is not None else None,
                'status': match.find('Status').text if match.find('Status') is not None else None,
                'home_goals': match.find('HomeGoals').text if match.find('HomeGoals') is not None else None,
                'away_goals': match.find('AwayGoals').text if match.find('AwayGoals') is not None else None
            }
            fixtures.append(match_info)
        
        return {
            'season': season,
            'fixtures': fixtures
        }
    
    def get_team_matches(self, team_id: int, season: int = None, match_types: List[int] = None, max_seasons_back: int = 2) -> Optional[List[Dict[str, Any]]]:
        """Pobiera mecze drużyny z opcjonalnym filtrowaniem według typów meczów
        
        Args:
            team_id: ID drużyny
            season: Sezon (opcjonalny)
            match_types: Lista typów meczów do uwzględnienia (opcjonalny)
                       1 = Liga, 3 = Puchar, 8 = Puchar (inne)
            max_seasons_back: Liczba sezonów wstecz do pobrania (domyślnie 2)
        """
        all_matches_list = []
        
        # Jeśli nie podano sezonu, pobierz z aktualnego i poprzednich sezonów
        if season is None:
            seasons_to_try = []
            # Najpierw pobierz aktualny sezon (bez parametru Season)
            seasons_to_try.append(None)
            # Potem próbuj poprzednie sezony
            for i in range(max_seasons_back):
                # Próbuj sezony wstecz (69, 68, 67...)
                season_num = 69 - i
                seasons_to_try.append(season_num)
            logger.info(f"Pobieranie meczów z {max_seasons_back + 1} ostatnich sezonów")
        else:
            seasons_to_try = [season]
        
        for season_num in seasons_to_try:
            params = {'TeamID': str(team_id)}
            if season_num is not None:
                params['Season'] = str(season_num)
            
            root = self.make_api_request('matches', params)
            
            if root is None:
                continue
            
            all_matches = list(root.findall('.//Match'))
            logger.info(f"API zwróciło {len(all_matches)} meczów dla drużyny {team_id} w sezonie {season_num}")
            
            for match in all_matches:
                match_type = match.find('MatchType')
                match_type_value = int(match_type.text) if match_type is not None and match_type.text is not None else None
                
                # Filtruj według typów meczów jeśli podano
                if match_types is not None and match_type_value not in match_types:
                    continue
                
                match_info = {
                    'match_id': match.find('MatchID').text if match.find('MatchID') is not None else None,
                    'home_team_id': match.find('HomeTeam/HomeTeamID').text if match.find('HomeTeam/HomeTeamID') is not None else None,
                    'home_team_name': match.find('HomeTeam/HomeTeamName').text if match.find('HomeTeam/HomeTeamName') is not None else None,
                    'away_team_id': match.find('AwayTeam/AwayTeamID').text if match.find('AwayTeam/AwayTeamID') is not None else None,
                    'away_team_name': match.find('AwayTeam/AwayTeamName').text if match.find('AwayTeam/AwayTeamName') is not None else None,
                    'match_date': match.find('MatchDate').text if match.find('MatchDate') is not None else None,
                    'status': match.find('Status').text if match.find('Status') is not None else None,
                    'home_goals': match.find('HomeGoals').text if match.find('HomeGoals') is not None else None,
                    'away_goals': match.find('AwayGoals').text if match.find('AwayGoals') is not None else None,
                    'match_type': match_type_value,
                    'is_home': match.find('HomeTeam/HomeTeamID').text == str(team_id) if match.find('HomeTeam/HomeTeamID') is not None else False,
                    
                    # Sprawdź czy są dostępne statystyki formacji
                    'home_formation': match.find('HomeTeam/Formation').text if match.find('HomeTeam/Formation') is not None else None,
                    'away_formation': match.find('AwayTeam/Formation').text if match.find('AwayTeam/Formation') is not None else None,
                    'home_tactic': match.find('HomeTeam/Tactic').text if match.find('HomeTeam/Tactic') is not None else None,
                    'away_tactic': match.find('AwayTeam/Tactic').text if match.find('AwayTeam/Tactic') is not None else None,
                    'home_tactic_level': match.find('HomeTeam/TacticLevel').text if match.find('HomeTeam/TacticLevel') is not None else None,
                    'away_tactic_level': match.find('AwayTeam/TacticLevel').text if match.find('AwayTeam/TacticLevel') is not None else None,
                    
                    # Ratingi drużyn
                    'home_rating_left_def': match.find('HomeTeam/RatingLeftDef').text if match.find('HomeTeam/RatingLeftDef') is not None else None,
                    'home_rating_central_def': match.find('HomeTeam/RatingCentralDef').text if match.find('HomeTeam/RatingCentralDef') is not None else None,
                    'home_rating_right_def': match.find('HomeTeam/RatingRightDef').text if match.find('HomeTeam/RatingRightDef') is not None else None,
                    'home_rating_midfield': match.find('HomeTeam/RatingMidfield').text if match.find('HomeTeam/RatingMidfield') is not None else None,
                    'home_rating_left_att': match.find('HomeTeam/RatingLeftAtt').text if match.find('HomeTeam/RatingLeftAtt') is not None else None,
                    'home_rating_central_att': match.find('HomeTeam/RatingCentralAtt').text if match.find('HomeTeam/RatingCentralAtt') is not None else None,
                    'home_rating_right_att': match.find('HomeTeam/RatingRightAtt').text if match.find('HomeTeam/RatingRightAtt') is not None else None,
                    
                    'away_rating_left_def': match.find('AwayTeam/RatingLeftDef').text if match.find('AwayTeam/RatingLeftDef') is not None else None,
                    'away_rating_central_def': match.find('AwayTeam/RatingCentralDef').text if match.find('AwayTeam/RatingCentralDef') is not None else None,
                    'away_rating_right_def': match.find('AwayTeam/RatingRightDef').text if match.find('AwayTeam/RatingRightDef') is not None else None,
                    'away_rating_midfield': match.find('AwayTeam/RatingMidfield').text if match.find('AwayTeam/RatingMidfield') is not None else None,
                    'away_rating_left_att': match.find('AwayTeam/RatingLeftAtt').text if match.find('AwayTeam/RatingLeftAtt') is not None else None,
                    'away_rating_central_att': match.find('AwayTeam/RatingCentralAtt').text if match.find('AwayTeam/RatingCentralAtt') is not None else None,
                    'away_rating_right_att': match.find('AwayTeam/RatingRightAtt').text if match.find('AwayTeam/RatingRightAtt') is not None else None,
                }
                
                # Oblicz ratingi formacji (obrona, pomoc, atak)
                match_info.update(self._calculate_formation_ratings(match_info))
                
                # DEBUG: Sprawdź czy ratingi są pusty
                if match_info.get('home_rating_midfield') is None:
                    logger.debug(f"Mecz {match_info.get('match_id')}: brak ratingów w matches API")
                
                all_matches_list.append(match_info)
        
        matches = all_matches_list
        
        logger.info(f"API zwróciło {len(matches)} meczów po filtrowaniu dla drużyny {team_id}")
        
        # DEBUG: Sprawdź ile meczów ma ratingi
        matches_with_ratings = [m for m in matches if m.get('home_rating_midfield') or m.get('away_rating_midfield')]
        logger.info(f"Z tych {len(matches)} meczów, {len(matches_with_ratings)} ma ratingi")
        
        return matches
    
    def get_match_details(self, match_id: int) -> Optional[Dict[str, Any]]:
        """Pobiera szczegółowe dane meczu"""
        params = {'MatchID': str(match_id)}
        root = self.make_api_request('matchdetails', params)
        
        if root is None:
            return None
        
        # Debug: zapisz surowy XML do pliku
        try:
            import xml.etree.ElementTree as ET
            xml_string = ET.tostring(root, encoding='unicode')
            with open(f'match_{match_id}_debug.xml', 'w', encoding='utf-8') as f:
                f.write(xml_string)
            logger.info(f"Zapisano surowy XML do pliku match_{match_id}_debug.xml")
        except Exception as e:
            logger.error(f"Błąd zapisu XML: {e}")
        
        # Parsuj szczegółowe dane meczu
        match_details = {
            'match_id': match_id,
            'home_team_id': root.find('.//HomeTeam/HomeTeamID').text if root.find('.//HomeTeam/HomeTeamID') is not None else None,
            'away_team_id': root.find('.//AwayTeam/AwayTeamID').text if root.find('.//AwayTeam/AwayTeamID') is not None else None,
            'home_team_name': root.find('.//HomeTeam/HomeTeamName').text if root.find('.//HomeTeam/HomeTeamName') is not None else None,
            'away_team_name': root.find('.//AwayTeam/AwayTeamName').text if root.find('.//AwayTeam/AwayTeamName') is not None else None,
            'home_goals': root.find('.//HomeTeam/HomeGoals').text if root.find('.//HomeTeam/HomeGoals') is not None else None,
            'away_goals': root.find('.//AwayTeam/AwayGoals').text if root.find('.//AwayTeam/AwayGoals') is not None else None,
            'match_date': root.find('.//MatchDate').text if root.find('.//MatchDate') is not None else None,
            'status': root.find('.//Status').text if root.find('.//Status') is not None else None,
        }
        
        # Debug: sprawdź co zwraca API
        logger.info(f"Debug API matchdetails dla meczu {match_id}:")
        logger.info(f"  - home_team_id: {match_details['home_team_id']}")
        logger.info(f"  - away_team_id: {match_details['away_team_id']}")
        logger.info(f"  - home_goals: {match_details['home_goals']}")
        logger.info(f"  - away_goals: {match_details['away_goals']}")
        logger.info(f"  - match_date: {match_details['match_date']}")
        logger.info(f"  - status: {match_details['status']}")
        
        # Sprawdź czy mamy dane o typie meczu
        match_type_elem = root.find('.//MatchType')
        if match_type_elem is not None:
            match_details['match_type'] = int(match_type_elem.text) if match_type_elem.text else None
            logger.info(f"  - match_type: {match_details['match_type']}")
        else:
            logger.warning("Brak danych o typie meczu w API")
        
        # Debug: sprawdź czy mamy dane o taktykach w głównym elemencie
        tactic_elem = root.find('.//Tactic')
        if tactic_elem is not None:
            logger.info(f"  - Tactic: {tactic_elem.text}")
        else:
            logger.warning("Brak danych o taktyce w głównym elemencie")
        
        # Debug: sprawdź czy mamy dane o formacji w głównym elemencie
        formation_elem = root.find('.//Formation')
        if formation_elem is not None:
            logger.info(f"  - Formation: {formation_elem.text}")
        else:
            logger.warning("Brak danych o formacji w głównym elemencie")
        
        # Debug: sprawdź strukturę XML
        logger.info("Struktura XML:")
        for child in root:
            logger.info(f"  - {child.tag}: {child.text if child.text else 'brak tekstu'}")
        
        # Debug: sprawdź szczegółowo element Match
        match_elem = root.find('.//Match')
        if match_elem is not None:
            logger.info("Element Match znaleziony:")
            for child in match_elem:
                logger.info(f"    - {child.tag}: {child.text if child.text else 'brak tekstu'}")
                
            # Sprawdź czy są dane o taktykach w Match (PIC/MOTS)
            tactic_elem = match_elem.find('.//Tactic')
            if tactic_elem is not None:
                logger.info(f"    - Tactic w Match: {tactic_elem.text}")
            else:
                logger.warning("    - Brak danych o taktyce w Match")
                
            # Sprawdź czy są dane o formacji w Match
            formation_elem = match_elem.find('.//Formation')
            if formation_elem is not None:
                logger.info(f"    - Formation w Match: {formation_elem.text}")
            else:
                logger.warning("    - Brak danych o formacji w Match")
                
            # Sprawdź czy mamy dane o pogodzie
            arena_elem = match_elem.find('.//Arena')
            if arena_elem is not None:
                weather_elem = arena_elem.find('.//WeatherID')
                if weather_elem is not None:
                    weather_id = int(weather_elem.text) if weather_elem.text else None
                    match_details['weather_id'] = weather_id
                    # 0 = Rain, 1 = Unsettled, 2 = Partly cloudy, 3 = Overcast, 4 = Nice, 5 = Sunny
                    weather_names = {0: 'Rain', 1: 'Unsettled', 2: 'Partly cloudy', 3: 'Overcast', 4: 'Nice', 5: 'Sunny'}
                    match_details['weather'] = weather_names.get(weather_id, 'Unknown')
                    logger.info(f"  - WeatherID: {weather_id} ({match_details['weather']})")
            
            # Sprawdź szczegółowo elementy HomeTeam i AwayTeam
            home_team_elem = match_elem.find('.//HomeTeam')
            if home_team_elem is not None:
                logger.info("Element HomeTeam znaleziony:")
                for child in home_team_elem:
                    logger.info(f"      - {child.tag}: {child.text if child.text else 'brak tekstu'}")
                    
                # Sprawdź czy jest sekcja Lineup w HomeTeam
                lineup_elem = home_team_elem.find('.//Lineup')
                if lineup_elem is not None:
                    logger.info("Sekcja Lineup w HomeTeam znaleziona:")
                    for child in lineup_elem:
                        logger.info(f"        - {child.tag}: {child.text if child.text else 'brak tekstu'}")
                else:
                    logger.warning("Brak sekcji Lineup w HomeTeam")
            else:
                logger.warning("Element HomeTeam nie znaleziony!")
                
            away_team_elem = match_elem.find('.//AwayTeam')
            if away_team_elem is not None:
                logger.info("Element AwayTeam znaleziony:")
                for child in away_team_elem:
                    logger.info(f"      - {child.tag}: {child.text if child.text else 'brak tekstu'}")
                    
                # Sprawdź czy jest sekcja Lineup w AwayTeam
                lineup_elem = away_team_elem.find('.//Lineup')
                if lineup_elem is not None:
                    logger.info("Sekcja Lineup w AwayTeam znaleziona:")
                    for child in lineup_elem:
                        logger.info(f"        - {child.tag}: {child.text if child.text else 'brak tekstu'}")
                else:
                    logger.warning("Brak sekcji Lineup w AwayTeam")
            else:
                logger.warning("Element AwayTeam nie znaleziony!")
        else:
            logger.warning("Element Match nie znaleziony!")
        
        # Pobierz ratingi pozycji i taktyki
        home_team = root.find('.//HomeTeam')
        away_team = root.find('.//AwayTeam')
        
        if home_team is not None:
            # Pobierz ratingi pozycji
            match_details.update({
                'home_rating_left_def': home_team.find('RatingLeftDef').text if home_team.find('RatingLeftDef') is not None else None,
                'home_rating_central_def': home_team.find('RatingMidDef').text if home_team.find('RatingMidDef') is not None else None,
                'home_rating_right_def': home_team.find('RatingRightDef').text if home_team.find('RatingRightDef') is not None else None,
                'home_rating_midfield': home_team.find('RatingMidfield').text if home_team.find('RatingMidfield') is not None else None,
                'home_rating_left_att': home_team.find('RatingLeftAtt').text if home_team.find('RatingLeftAtt') is not None else None,
                'home_rating_central_att': home_team.find('RatingMidAtt').text if home_team.find('RatingMidAtt') is not None else None,
                'home_rating_right_att': home_team.find('RatingRightAtt').text if home_team.find('RatingRightAtt') is not None else None,
            })
            
            # Pobierz taktykę (TacticType)
            tactic_type = home_team.find('TacticType').text if home_team.find('TacticType') is not None else None
            tactic_skill = home_team.find('TacticSkill').text if home_team.find('TacticSkill') is not None else None
            
            # Konwertuj TacticType na nazwę
            tactic_names = {
                '0': 'Normal',
                '1': 'Pressing', 
                '2': 'Counter',
                '3': 'Attack Middle',
                '4': 'Attack Wings',
                '5': 'Creative'
            }
            
            match_details.update({
                'home_tactic': tactic_names.get(tactic_type, 'Unknown'),
                'home_tactic_level': tactic_skill,
                'home_tactic_type': tactic_type
            })
            
            # Pobierz dane o zawodnikach dla obliczenia formacji
            home_players = []
            players_found = home_team.findall('Player')
            logger.info(f"Znaleziono {len(players_found)} zawodników drużyny domowej")
            
            for i, player in enumerate(players_found):
                player_data = {
                    'player_id': player.find('PlayerID').text if player.find('PlayerID') is not None else None,
                    'position': player.find('Position').text if player.find('Position') is not None else None,
                    'position_code': player.find('PositionCode').text if player.find('PositionCode') is not None else None,
                }
                home_players.append(player_data)
                if i < 3:  # Loguj pierwszych 3 zawodników
                    logger.info(f"  Zawodnik {i+1}: {player_data}")
            
            match_details['home_players'] = home_players
        
        if away_team is not None:
            # Pobierz ratingi pozycji
            match_details.update({
                'away_rating_left_def': away_team.find('RatingLeftDef').text if away_team.find('RatingLeftDef') is not None else None,
                'away_rating_central_def': away_team.find('RatingMidDef').text if away_team.find('RatingMidDef') is not None else None,
                'away_rating_right_def': away_team.find('RatingRightDef').text if away_team.find('RatingRightDef') is not None else None,
                'away_rating_midfield': away_team.find('RatingMidfield').text if away_team.find('RatingMidfield') is not None else None,
                'away_rating_left_att': away_team.find('RatingLeftAtt').text if away_team.find('RatingLeftAtt') is not None else None,
                'away_rating_central_att': away_team.find('RatingMidAtt').text if away_team.find('RatingMidAtt') is not None else None,
                'away_rating_right_att': away_team.find('RatingRightAtt').text if away_team.find('RatingRightAtt') is not None else None,
            })
            
            # Pobierz taktykę (TacticType)
            tactic_type = away_team.find('TacticType').text if away_team.find('TacticType') is not None else None
            tactic_skill = away_team.find('TacticSkill').text if away_team.find('TacticSkill') is not None else None
            
            # Konwertuj TacticType na nazwę
            tactic_names = {
                '0': 'Normal',
                '1': 'Pressing', 
                '2': 'Counter',
                '3': 'Attack Middle',
                '4': 'Attack Wings',
                '5': 'Creative'
            }
            
            match_details.update({
                'away_tactic': tactic_names.get(tactic_type, 'Unknown'),
                'away_tactic_level': tactic_skill,
                'away_tactic_type': tactic_type
            })
            
            # Pobierz dane o zawodnikach dla obliczenia formacji
            away_players = []
            players_found = away_team.findall('Player')
            logger.info(f"Znaleziono {len(players_found)} zawodników drużyny wyjazdowej")
            
            for i, player in enumerate(players_found):
                player_data = {
                    'player_id': player.find('PlayerID').text if player.find('PlayerID') is not None else None,
                    'position': player.find('Position').text if player.find('Position') is not None else None,
                    'position_code': player.find('PositionCode').text if player.find('PositionCode') is not None else None,
                }
                away_players.append(player_data)
                if i < 3:  # Loguj pierwszych 3 zawodników
                    logger.info(f"  Zawodnik {i+1}: {player_data}")
            
            match_details['away_players'] = away_players
        
        # Oblicz ratingi formacji
        match_details.update(self._calculate_formation_ratings(match_details))
        
        # Spróbuj pobrać dane o składzie z matchlineup
        if match_details.get('home_team_id') and match_details.get('away_team_id'):
            try:
                lineup_data = self._get_lineup_data(match_id, match_details['home_team_id'], match_details['away_team_id'])
                if lineup_data:
                    match_details.update(lineup_data)
                    logger.info(f"Pobrano dane lineup dla meczu {match_id}")
                else:
                    logger.warning(f"Brak danych lineup dla meczu {match_id}")
                    # Jeśli nie ma lineup, NIE szacuj formacji (jest niedokładna)
                    match_details['home_formation'] = None
                    match_details['away_formation'] = None
            except Exception as e:
                logger.error(f"Błąd pobierania lineup: {e}")
                match_details['home_formation'] = None
                match_details['away_formation'] = None
        
        # UWAGA: Nie szacuj formacji automatycznie - jest niedokładna!
        # Tylko jeśli mamy lineup z API - wtedy obliczamy dokładną formację
        
        return match_details
    
    def _get_lineup_data(self, match_id: int, home_team_id: int, away_team_id: int) -> Optional[Dict[str, Any]]:
        """Pobiera dane lineup dla meczu"""
        try:
            # Spróbuj pobrać lineup dla drużyny domowej
            params = {'MatchID': str(match_id), 'TeamID': str(home_team_id)}
            home_lineup_root = self.make_api_request('matchlineup', params)
            
            params = {'MatchID': str(match_id), 'TeamID': str(away_team_id)}
            away_lineup_root = self.make_api_request('matchlineup', params)
            
            if home_lineup_root is not None or away_lineup_root is not None:
                lineup_data = {}
                
                # Parsuj lineup drużyny domowej
                if home_lineup_root is not None:
                    home_players = self._parse_lineup_players(home_lineup_root)
                    lineup_data['home_players'] = home_players
                    lineup_data['home_formation'] = self._calculate_formation_from_lineup(home_players)
                
                # Parsuj lineup drużyny wyjazdowej
                if away_lineup_root is not None:
                    away_players = self._parse_lineup_players(away_lineup_root)
                    lineup_data['away_players'] = away_players
                    lineup_data['away_formation'] = self._calculate_formation_from_lineup(away_players)
                
                return lineup_data
            
        except Exception as e:
            logger.error(f"Błąd pobierania lineup: {e}")
        
        return None
    
    def _parse_lineup_players(self, lineup_root) -> List[Dict]:
        """Parsuje dane o zawodnikach z lineup"""
        players = []
        
        # Debug: zapisz cały lineup XML
        try:
            import xml.etree.ElementTree as ET
            xml_string = ET.tostring(lineup_root, encoding='unicode')
            logger.info(f"Lineup XML:\n{xml_string}")
        except Exception as e:
            logger.error(f"Błąd zapisu lineup XML: {e}")
        
        # Sprawdź różne możliwe struktury
        # Może być .//Lineup lub .//Team/Lineup lub .//LineupOrder
        lineup = lineup_root.find('.//Lineup')
        if lineup is None:
            lineup = lineup_root.find('.//LineupOrder')
        if lineup is None:
            lineup = lineup_root.find('.//Team')
        
        if lineup is None:
            logger.warning("Brak sekcji Lineup w XML")
            return players
        
        # Parsuj zawodników
        for player in lineup.findall('.//Player'):
            player_data = {
                'player_id': player.find('PlayerID').text if player.find('PlayerID') is not None else None,
                'player_name': player.find('PlayerName').text if player.find('PlayerName') is not None else None,
                'role_id': player.find('RoleID').text if player.find('RoleID') is not None else None,
                'position_code': player.find('PositionCode').text if player.find('PositionCode') is not None else None,
            }
            players.append(player_data)
            logger.info(f"Znaleziono zawodnika: {player_data}")
        
        logger.info(f"Znaleziono {len(players)} zawodników w lineup")
        return players
    
    def _calculate_formation_from_lineup(self, players: List[Dict]) -> Optional[str]:
        """Oblicza formację na podstawie lineup"""
        if not players:
            return None
        
        # W Hattricku PositionCode oznacza pozycję:
        # Obrońcy: PositionCode 2-5 (RightDef=2, CentralDef=3, LeftDef=4, atak wyjściowy=5)
        # Pomocnicy: PositionCode 6-9 (RightMid=6, CentralMid=7, LeftMid=8, ofensywny=9)
        # Napastnicy: PositionCode 10-11 (RightAtt=10, LeftAtt=11)
        
        defenders = sum(1 for p in players if p.get('position_code') and 2 <= int(p.get('position_code', 0)) <= 5)
        midfielders = sum(1 for p in players if p.get('position_code') and 6 <= int(p.get('position_code', 0)) <= 9)
        attackers = sum(1 for p in players if p.get('position_code') and 10 <= int(p.get('position_code', 0)) <= 11)
        
        logger.info(f"Formacja: Defenders={defenders}, Midfielders={midfielders}, Attackers={attackers}")
        
        return f"{defenders}-{midfielders}-{attackers}"
    
    def _calculate_formation_ratings(self, match_info: Dict[str, Any]) -> Dict[str, Any]:
        """Oblicza ratingi formacji (obrona, pomoc, atak) na podstawie ratingów pozycji"""
        def safe_float(value):
            """Bezpieczne konwertowanie na float"""
            if value is None or value == '':
                return 0.0
            try:
                return float(value)
            except (ValueError, TypeError):
                return 0.0
        
        # Oblicz ratingi dla drużyny domowej
        home_def_left = safe_float(match_info.get('home_rating_left_def'))
        home_def_central = safe_float(match_info.get('home_rating_central_def'))
        home_def_right = safe_float(match_info.get('home_rating_right_def'))
        home_midfield = safe_float(match_info.get('home_rating_midfield'))
        home_att_left = safe_float(match_info.get('home_rating_left_att'))
        home_att_central = safe_float(match_info.get('home_rating_central_att'))
        home_att_right = safe_float(match_info.get('home_rating_right_att'))
        
        # Oblicz ratingi dla drużyny wyjazdowej
        away_def_left = safe_float(match_info.get('away_rating_left_def'))
        away_def_central = safe_float(match_info.get('away_rating_central_def'))
        away_def_right = safe_float(match_info.get('away_rating_right_def'))
        away_midfield = safe_float(match_info.get('away_rating_midfield'))
        away_att_left = safe_float(match_info.get('away_rating_left_att'))
        away_att_central = safe_float(match_info.get('away_rating_central_att'))
        away_att_right = safe_float(match_info.get('away_rating_right_att'))
        
        return {
            # Ratingi formacji drużyny domowej
            'home_defense_rating': (home_def_left + home_def_central + home_def_right) / 3.0,
            'home_midfield_rating': home_midfield,
            'home_attack_rating': (home_att_left + home_att_central + home_att_right) / 3.0,
            
            # Ratingi formacji drużyny wyjazdowej
            'away_defense_rating': (away_def_left + away_def_central + away_def_right) / 3.0,
            'away_midfield_rating': away_midfield,
            'away_attack_rating': (away_att_left + away_att_central + away_att_right) / 3.0,
        }
    
    def _calculate_formation_from_players(self, match_details: Dict[str, Any]) -> Dict[str, Any]:
        """Oblicza formację na podstawie pozycji zawodników"""
        def count_players_by_position(players: List[Dict], position_type: str) -> int:
            """Liczy zawodników na danej pozycji"""
            if not players:
                return 0
            
            count = 0
            for player in players:
                position_code = player.get('position_code', '')
                if position_type == 'defender' and position_code in ['CD', 'LD', 'RD']:
                    count += 1
                elif position_type == 'midfielder' and position_code in ['CM', 'LM', 'RM', 'CDM', 'CAM']:
                    count += 1
                elif position_type == 'attacker' and position_code in ['CF', 'LF', 'RF', 'ST']:
                    count += 1
            return count
        
        # Oblicz formację dla drużyny domowej
        home_players = match_details.get('home_players', [])
        home_def_count = count_players_by_position(home_players, 'defender')
        home_mid_count = count_players_by_position(home_players, 'midfielder')
        home_att_count = count_players_by_position(home_players, 'attacker')
        home_formation = f"{home_def_count}-{home_mid_count}-{home_att_count}" if home_players else None
        
        # Oblicz formację dla drużyny wyjazdowej
        away_players = match_details.get('away_players', [])
        away_def_count = count_players_by_position(away_players, 'defender')
        away_mid_count = count_players_by_position(away_players, 'midfielder')
        away_att_count = count_players_by_position(away_players, 'attacker')
        away_formation = f"{away_def_count}-{away_mid_count}-{away_att_count}" if away_players else None
        
        return {
            'home_formation': home_formation,
            'away_formation': away_formation,
            'home_formation_details': {
                'defenders': home_def_count,
                'midfielders': home_mid_count,
                'attackers': home_att_count
            },
            'away_formation_details': {
                'defenders': away_def_count,
                'midfielders': away_mid_count,
                'attackers': away_att_count
            }
        }
    
    def _estimate_formation_from_ratings(self, match_details: Dict[str, Any]) -> Dict[str, Any]:
        """Oszacowuje formację na podstawie proporcji ratingów pozycji"""
        def estimate_formation_ratios(def_rating: float, mid_rating: float, att_rating: float) -> str:
            """Oszacowuje formację na podstawie sumy ratingów pozycji"""
            if def_rating == 0 or mid_rating == 0 or att_rating == 0:
                return "Unknown"
            
            # W Hattricku rating pozycji reprezentuje SIŁĘ linii, nie liczbę graczy
            # Ale możemy szacować na podstawie tego jak siła jest rozłożona
            
            # Metoda 1: Szacowanie na podstawie proporcji siły
            # Jeśli jedna linia jest dominująca, oznacza to więcej graczy
            
            total_strength = def_rating + mid_rating + att_rating
            def_strength_pct = def_rating / total_strength
            mid_strength_pct = mid_rating / total_strength
            att_strength_pct = att_rating / total_strength
            
            # Szacuj liczbę graczy na podstawie procentowej siły
            # Zakładając standardowe rozłożenie: 35% obrona, 40% pomoc, 25% atak dla 4-4-2
            
            # Obrońcy: 3-5 graczy (20-40% siły)
            if def_strength_pct < 0.25:
                defenders = 3
            elif def_strength_pct < 0.35:
                defenders = 4
            else:
                defenders = 5
            
            # Pomocnicy: 3-6 graczy (30-50% siły)
            if mid_strength_pct < 0.30:
                midfielders = 3
            elif mid_strength_pct < 0.40:
                midfielders = 4
            elif mid_strength_pct < 0.50:
                midfielders = 5
            else:
                midfielders = 6
            
            # Napastnicy: 1-3 graczy (15-30% siły)
            if att_strength_pct < 0.20:
                attackers = 1
            elif att_strength_pct < 0.30:
                attackers = 2
            else:
                attackers = 3
            
            return f"{defenders}-{midfielders}-{attackers}"
        
        # Oszacuj formację dla drużyny domowej
        home_def = match_details.get('home_defense_rating', 0)
        home_mid = match_details.get('home_midfield_rating', 0)
        home_att = match_details.get('home_attack_rating', 0)
        
        home_formation = estimate_formation_ratios(home_def, home_mid, home_att) if home_def and home_mid and home_att else "Unknown"
        
        # Oszacuj formację dla drużyny wyjazdowej
        away_def = match_details.get('away_defense_rating', 0)
        away_mid = match_details.get('away_midfield_rating', 0)
        away_att = match_details.get('away_attack_rating', 0)
        
        away_formation = estimate_formation_ratios(away_def, away_mid, away_att) if away_def and away_mid and away_att else "Unknown"
        
        return {
            'home_formation': home_formation,
            'away_formation': away_formation,
            'home_formation_estimated': True,
            'away_formation_estimated': True
        }






