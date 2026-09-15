-- Tournament database schema and data for Zephyr Invitational 2026
-- 16-player Swiss chess tournament, 4 completed rounds

CREATE TABLE tournament_info (
    name TEXT NOT NULL,
    city TEXT NOT NULL,
    country TEXT NOT NULL,
    start_date TEXT NOT NULL,
    end_date TEXT NOT NULL,
    num_players INTEGER NOT NULL,
    num_rated INTEGER NOT NULL,
    num_teams INTEGER NOT NULL,
    type TEXT NOT NULL,
    chief_arbiter TEXT NOT NULL,
    deputy_arbiter TEXT NOT NULL,
    time_control TEXT NOT NULL,
    round_dates TEXT NOT NULL,
    num_rounds INTEGER NOT NULL,
    initial_colour TEXT NOT NULL DEFAULT 'white1'
);

CREATE TABLE players (
    tpn INTEGER PRIMARY KEY,
    sex CHAR(1) NOT NULL,
    title VARCHAR(4) NOT NULL,
    name VARCHAR(33) NOT NULL,
    rating INTEGER NOT NULL,
    federation CHAR(3) NOT NULL,
    fide_id VARCHAR(11) NOT NULL,
    birth_date VARCHAR(10) NOT NULL,
    score REAL NOT NULL,
    rank INTEGER NOT NULL
);

CREATE TABLE round_results (
    tpn INTEGER NOT NULL,
    round_num INTEGER NOT NULL,
    opponent_tpn INTEGER NOT NULL,
    colour CHAR(1) NOT NULL,
    result VARCHAR(1) NOT NULL,
    PRIMARY KEY (tpn, round_num),
    FOREIGN KEY (tpn) REFERENCES players(tpn),
    FOREIGN KEY (opponent_tpn) REFERENCES players(tpn)
);

INSERT INTO tournament_info VALUES (
    'Zephyr Invitational 2026', 'Vienna, Austria', 'AUT',
    '2026/05/01', '2026/05/05', 16, 16, 0,
    'Individual: Open', 'IA Thomas Richter', 'FA Anna Kowalczyk',
    '90/40+30+30', '2026/05/01  2026/05/02  2026/05/03  2026/05/04',
    4, 'white1'
);

INSERT INTO players VALUES (1, 'm', 'GM', 'Petrov, Alexei', 2645, 'RUS', '00001001111', '1990/03/15', 3.5, 1);
INSERT INTO players VALUES (2, 'm', 'GM', 'Nakamura, Hikaru', 2630, 'USA', '00001002222', '1987/12/09', 2.5, 3);
INSERT INTO players VALUES (3, 'm', 'GM', 'Andersson, Lars', 2598, 'SWE', '00001003333', '1992/06/21', 3.5, 2);
INSERT INTO players VALUES (4, 'm', 'GM', 'Fernandez, Carlos', 2575, 'ESP', '00001004444', '1995/01/30', 2.0, 6);
INSERT INTO players VALUES (5, 'm', 'IM', 'Kim, Sung-Ho', 2561, 'KOR', '00001005555', '1998/08/14', 1.5, 12);
INSERT INTO players VALUES (6, 'w', 'IM', 'Ivanova, Maria', 2544, 'BUL', '00001006666', '1993/11/05', 2.5, 4);
INSERT INTO players VALUES (7, 'm', 'IM', 'Mueller, Thomas', 2520, 'GER', '00001007777', '1991/04/22', 2.5, 5);
INSERT INTO players VALUES (8, 'm', 'IM', 'Dubois, Pierre', 2503, 'FRA', '00001008888', '1994/07/18', 2.0, 7);
INSERT INTO players VALUES (9, 'm', 'FM', 'Yamamoto, Kenji', 2487, 'JPN', '00001009999', '1996/02/28', 2.0, 8);
INSERT INTO players VALUES (10, 'm', 'FM', 'Kowalski, Jan', 2465, 'POL', '00001011110', '1989/09/03', 2.0, 9);
INSERT INTO players VALUES (11, 'm', 'FM', 'Singh, Arjun', 2442, 'IND', '00001012221', '1997/05/12', 1.5, 13);
INSERT INTO players VALUES (12, 'm', 'FM', 'Hernandez, Miguel', 2418, 'MEX', '00001013332', '1988/10/25', 2.0, 10);
INSERT INTO players VALUES (13, 'm', 'CM', 'Okonkwo, Chidera', 2395, 'NGR', '00001014443', '2000/01/07', 2.0, 11);
INSERT INTO players VALUES (14, 'm', 'CM', 'Bjornsson, Erik', 2380, 'ISL', '00001015554', '1999/03/19', 1.0, 15);
INSERT INTO players VALUES (15, 'w', 'WGM', 'Alvarez, Sofia', 2358, 'ARG', '00001016665', '1995/07/31', 0.0, 16);
INSERT INTO players VALUES (16, 'm', 'FM', 'Zhang, Wei', 2340, 'CHN', '00001017776', '2001/06/14', 1.5, 14);

-- Player 1: Petrov (W B B W) opponents: 9 2 6 4
INSERT INTO round_results VALUES (1, 1, 9, 'w', '1');
INSERT INTO round_results VALUES (1, 2, 2, 'b', '=');
INSERT INTO round_results VALUES (1, 3, 6, 'b', '1');
INSERT INTO round_results VALUES (1, 4, 4, 'w', '1');

-- Player 2: Nakamura (B W W W) opponents: 10 1 3 5
INSERT INTO round_results VALUES (2, 1, 10, 'b', '1');
INSERT INTO round_results VALUES (2, 2, 1, 'w', '=');
INSERT INTO round_results VALUES (2, 3, 3, 'w', '0');
INSERT INTO round_results VALUES (2, 4, 5, 'w', '1');

-- Player 3: Andersson (W B B W) opponents: 11 4 2 8
INSERT INTO round_results VALUES (3, 1, 11, 'w', '1');
INSERT INTO round_results VALUES (3, 2, 4, 'b', '=');
INSERT INTO round_results VALUES (3, 3, 2, 'b', '1');
INSERT INTO round_results VALUES (3, 4, 8, 'w', '1');

-- Player 4: Fernandez (B W W B) opponents: 12 3 7 1
INSERT INTO round_results VALUES (4, 1, 12, 'b', '1');
INSERT INTO round_results VALUES (4, 2, 3, 'w', '=');
INSERT INTO round_results VALUES (4, 3, 7, 'w', '=');
INSERT INTO round_results VALUES (4, 4, 1, 'b', '0');

-- Player 5: Kim (W B B B) opponents: 13 6 8 2
INSERT INTO round_results VALUES (5, 1, 13, 'w', '1');
INSERT INTO round_results VALUES (5, 2, 6, 'b', '0');
INSERT INTO round_results VALUES (5, 3, 8, 'b', '=');
INSERT INTO round_results VALUES (5, 4, 2, 'b', '0');

-- Player 6: Ivanova (B W W W) opponents: 14 5 1 7
INSERT INTO round_results VALUES (6, 1, 14, 'b', '1');
INSERT INTO round_results VALUES (6, 2, 5, 'w', '1');
INSERT INTO round_results VALUES (6, 3, 1, 'w', '0');
INSERT INTO round_results VALUES (6, 4, 7, 'w', '=');

-- Player 7: Mueller (W B B B) opponents: 15 8 4 6
INSERT INTO round_results VALUES (7, 1, 15, 'w', '1');
INSERT INTO round_results VALUES (7, 2, 8, 'b', '=');
INSERT INTO round_results VALUES (7, 3, 4, 'b', '=');
INSERT INTO round_results VALUES (7, 4, 6, 'b', '=');

-- Player 8: Dubois (B W W B) opponents: 16 7 5 3
INSERT INTO round_results VALUES (8, 1, 16, 'b', '1');
INSERT INTO round_results VALUES (8, 2, 7, 'w', '=');
INSERT INTO round_results VALUES (8, 3, 5, 'w', '=');
INSERT INTO round_results VALUES (8, 4, 3, 'b', '0');

-- Player 9: Yamamoto (B W W B) opponents: 1 10 16 12
INSERT INTO round_results VALUES (9, 1, 1, 'b', '0');
INSERT INTO round_results VALUES (9, 2, 10, 'w', '1');
INSERT INTO round_results VALUES (9, 3, 16, 'w', '=');
INSERT INTO round_results VALUES (9, 4, 12, 'b', '=');

-- Player 10: Kowalski (W B B W) opponents: 2 9 11 15
INSERT INTO round_results VALUES (10, 1, 2, 'w', '0');
INSERT INTO round_results VALUES (10, 2, 9, 'b', '0');
INSERT INTO round_results VALUES (10, 3, 11, 'b', '1');
INSERT INTO round_results VALUES (10, 4, 15, 'w', '1');

-- Player 11: Singh (B W W W) opponents: 3 12 10 14
INSERT INTO round_results VALUES (11, 1, 3, 'b', '0');
INSERT INTO round_results VALUES (11, 2, 12, 'w', '=');
INSERT INTO round_results VALUES (11, 3, 10, 'w', '0');
INSERT INTO round_results VALUES (11, 4, 14, 'w', '1');

-- Player 12: Hernandez (W B B W) opponents: 4 11 13 9
INSERT INTO round_results VALUES (12, 1, 4, 'w', '0');
INSERT INTO round_results VALUES (12, 2, 11, 'b', '=');
INSERT INTO round_results VALUES (12, 3, 13, 'b', '1');
INSERT INTO round_results VALUES (12, 4, 9, 'w', '=');

-- Player 13: Okonkwo (B W W B) opponents: 5 14 12 16
INSERT INTO round_results VALUES (13, 1, 5, 'b', '0');
INSERT INTO round_results VALUES (13, 2, 14, 'w', '1');
INSERT INTO round_results VALUES (13, 3, 12, 'w', '0');
INSERT INTO round_results VALUES (13, 4, 16, 'b', '1');

-- Player 14: Bjornsson (W B B B) opponents: 6 13 15 11
INSERT INTO round_results VALUES (14, 1, 6, 'w', '0');
INSERT INTO round_results VALUES (14, 2, 13, 'b', '0');
INSERT INTO round_results VALUES (14, 3, 15, 'b', '1');
INSERT INTO round_results VALUES (14, 4, 11, 'b', '0');

-- Player 15: Alvarez (B W W B) opponents: 7 16 14 10
INSERT INTO round_results VALUES (15, 1, 7, 'b', '0');
INSERT INTO round_results VALUES (15, 2, 16, 'w', '0');
INSERT INTO round_results VALUES (15, 3, 14, 'w', '0');
INSERT INTO round_results VALUES (15, 4, 10, 'b', '0');

-- Player 16: Zhang (W B B W) opponents: 8 15 9 13
INSERT INTO round_results VALUES (16, 1, 8, 'w', '0');
INSERT INTO round_results VALUES (16, 2, 15, 'b', '1');
INSERT INTO round_results VALUES (16, 3, 9, 'b', '=');
INSERT INTO round_results VALUES (16, 4, 13, 'w', '0');
