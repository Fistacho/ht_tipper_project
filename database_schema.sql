-- Schemat bazy danych MySQL dla Hattrick Typer
-- Uruchom ten skrypt w swojej bazie MySQL przed pierwszym użyciem

-- Tabela graczy
CREATE TABLE IF NOT EXISTS players (
    player_name VARCHAR(255) PRIMARY KEY,
    total_points INT DEFAULT 0,
    rounds_played INT DEFAULT 0,
    best_score INT DEFAULT 0,
    worst_score INT DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Tabela lig
CREATE TABLE IF NOT EXISTS leagues (
    league_id VARCHAR(50) PRIMARY KEY,
    league_name VARCHAR(255),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Tabela sezonów
CREATE TABLE IF NOT EXISTS seasons (
    season_id VARCHAR(255) PRIMARY KEY,
    league_id VARCHAR(50),
    start_date VARCHAR(50),
    end_date VARCHAR(50),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (league_id) REFERENCES leagues(league_id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Tabela rund
CREATE TABLE IF NOT EXISTS rounds (
    round_id VARCHAR(255) PRIMARY KEY,
    season_id VARCHAR(255),
    start_date VARCHAR(50),
    end_date VARCHAR(50),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (season_id) REFERENCES seasons(season_id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Tabela meczów
CREATE TABLE IF NOT EXISTS matches (
    match_id VARCHAR(255),
    round_id VARCHAR(255),
    home_team_name VARCHAR(255),
    away_team_name VARCHAR(255),
    match_date VARCHAR(50),
    home_goals INT,
    away_goals INT,
    league_id INT,
    PRIMARY KEY (match_id, round_id),
    FOREIGN KEY (round_id) REFERENCES rounds(round_id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Tabela typów (predictions)
CREATE TABLE IF NOT EXISTS predictions (
    id INT AUTO_INCREMENT PRIMARY KEY,
    round_id VARCHAR(255),
    player_name VARCHAR(255),
    match_id VARCHAR(255),
    home_goals INT,
    away_goals INT,
    timestamp VARCHAR(50),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY unique_prediction (round_id, player_name, match_id),
    INDEX idx_player_round (player_name, round_id),
    INDEX idx_round (round_id),
    INDEX idx_player (player_name),
    FOREIGN KEY (round_id) REFERENCES rounds(round_id) ON DELETE CASCADE,
    FOREIGN KEY (player_name) REFERENCES players(player_name) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Tabela punktów za mecze
CREATE TABLE IF NOT EXISTS match_points (
    id INT AUTO_INCREMENT PRIMARY KEY,
    round_id VARCHAR(255),
    player_name VARCHAR(255),
    match_id VARCHAR(255),
    points INT DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY unique_match_points (round_id, player_name, match_id),
    INDEX idx_player_round (player_name, round_id),
    INDEX idx_round (round_id),
    INDEX idx_player (player_name),
    FOREIGN KEY (round_id) REFERENCES rounds(round_id) ON DELETE CASCADE,
    FOREIGN KEY (player_name) REFERENCES players(player_name) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Tabela ustawień
CREATE TABLE IF NOT EXISTS settings (
    setting_key VARCHAR(255) PRIMARY KEY,
    setting_value TEXT,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

