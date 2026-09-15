CREATE TABLE levels (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    grid TEXT NOT NULL,
    num_boxes INTEGER NOT NULL
);

INSERT INTO levels (id, name, grid, num_boxes) VALUES (1, 'warmup', '#####
#.  #
#   #
# $ #
# @ #
#####', 1);

INSERT INTO levels (id, name, grid, num_boxes) VALUES (2, 'double_target', '#######
#     #
# .$. #
#  @  #
#  $  #
#     #
#######', 2);

INSERT INTO levels (id, name, grid, num_boxes) VALUES (3, 'deadlock_alley', '######
# @  #
# $$.#
#   .#
######', 2);

INSERT INTO levels (id, name, grid, num_boxes) VALUES (4, 'quad_symmetric', '########
#  ..  #
# $  $ #
#      #
# $  $ #
#  ..  #
#  @   #
########', 4);

INSERT INTO levels (id, name, grid, num_boxes) VALUES (5, 'push_order', '######
#    #
# .# #
#  $ #
# .$ #
# .$ #
#  @ #
######', 3);
