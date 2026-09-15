-- Kernel structure layout and security annotation database

CREATE TABLE structures (
    name TEXT PRIMARY KEY,
    size INTEGER NOT NULL,
    alloc_cache TEXT NOT NULL,
    description TEXT
);

CREATE TABLE fields (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    struct_name TEXT NOT NULL REFERENCES structures(name),
    field_name TEXT NOT NULL,
    byte_offset INTEGER NOT NULL,
    byte_size INTEGER NOT NULL
);

CREATE TABLE security_properties (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    struct_name TEXT NOT NULL REFERENCES structures(name),
    field_name TEXT NOT NULL,
    capability TEXT NOT NULL,
    exploit_method TEXT NOT NULL
);

-- Structures
INSERT INTO structures VALUES ('seq_operations', 32, 'kmalloc-32', 'Kernel sequence file operations table, allocated when opening /proc files via seq_file interface');
INSERT INTO structures VALUES ('msg_msg', 64, 'kmalloc-64', 'System V IPC message structure with 16 bytes of inline data, allocated via msgsnd()');
INSERT INTO structures VALUES ('pipe_buffer', 40, 'kmalloc-64', 'Pipe buffer descriptor, allocated when creating pipes via pipe()/pipe2()');
INSERT INTO structures VALUES ('subprocess_info', 96, 'kmalloc-96', 'Usermode helper execution context, allocated via call_usermodehelper_setup()');
INSERT INTO structures VALUES ('timer_list_wrapper', 96, 'kmalloc-96', 'Timer callback wrapper used by various kernel subsystems');
INSERT INTO structures VALUES ('user_key_payload', 128, 'kmalloc-128', 'User keyring payload, allocated via add_key() syscall for heap spraying');
INSERT INTO structures VALUES ('drill_item', 192, 'drill_cache', 'Vulnerable kernel module object from drill_mod.ko, allocated from custom drill_cache slab');
INSERT INTO structures VALUES ('file_event_info', 192, 'kmalloc-192', 'File system event notification structure, allocated from generic kmalloc-192');
INSERT INTO structures VALUES ('cred', 192, 'cred_jar', 'Process credentials structure, allocated from dedicated cred_jar slab with SLAB_TYPESAFE_BY_RCU');
INSERT INTO structures VALUES ('tty_struct', 696, 'kmalloc-1024', 'TTY device structure, allocated when opening /dev/ptmx');
INSERT INTO structures VALUES ('sighand_struct', 1024, 'sighand_cache', 'Signal handler table, allocated from sighand_cache with constructor');

-- Fields: seq_operations
INSERT INTO fields (struct_name, field_name, byte_offset, byte_size) VALUES ('seq_operations', 'start', 0, 8);
INSERT INTO fields (struct_name, field_name, byte_offset, byte_size) VALUES ('seq_operations', 'stop', 8, 8);
INSERT INTO fields (struct_name, field_name, byte_offset, byte_size) VALUES ('seq_operations', 'next', 16, 8);
INSERT INTO fields (struct_name, field_name, byte_offset, byte_size) VALUES ('seq_operations', 'show', 24, 8);

-- Fields: msg_msg
INSERT INTO fields (struct_name, field_name, byte_offset, byte_size) VALUES ('msg_msg', 'm_list_next', 0, 8);
INSERT INTO fields (struct_name, field_name, byte_offset, byte_size) VALUES ('msg_msg', 'm_list_prev', 8, 8);
INSERT INTO fields (struct_name, field_name, byte_offset, byte_size) VALUES ('msg_msg', 'm_type', 16, 8);
INSERT INTO fields (struct_name, field_name, byte_offset, byte_size) VALUES ('msg_msg', 'm_ts', 24, 8);
INSERT INTO fields (struct_name, field_name, byte_offset, byte_size) VALUES ('msg_msg', 'next_segment', 32, 8);
INSERT INTO fields (struct_name, field_name, byte_offset, byte_size) VALUES ('msg_msg', 'security_ptr', 40, 8);
INSERT INTO fields (struct_name, field_name, byte_offset, byte_size) VALUES ('msg_msg', 'inline_data', 48, 16);

-- Fields: pipe_buffer
INSERT INTO fields (struct_name, field_name, byte_offset, byte_size) VALUES ('pipe_buffer', 'page', 0, 8);
INSERT INTO fields (struct_name, field_name, byte_offset, byte_size) VALUES ('pipe_buffer', 'offset', 8, 4);
INSERT INTO fields (struct_name, field_name, byte_offset, byte_size) VALUES ('pipe_buffer', 'len', 12, 4);
INSERT INTO fields (struct_name, field_name, byte_offset, byte_size) VALUES ('pipe_buffer', 'ops', 16, 8);
INSERT INTO fields (struct_name, field_name, byte_offset, byte_size) VALUES ('pipe_buffer', 'flags', 24, 4);
INSERT INTO fields (struct_name, field_name, byte_offset, byte_size) VALUES ('pipe_buffer', 'pad', 28, 4);
INSERT INTO fields (struct_name, field_name, byte_offset, byte_size) VALUES ('pipe_buffer', 'private', 32, 8);

-- Fields: subprocess_info
INSERT INTO fields (struct_name, field_name, byte_offset, byte_size) VALUES ('subprocess_info', 'callback', 0, 8);
INSERT INTO fields (struct_name, field_name, byte_offset, byte_size) VALUES ('subprocess_info', 'flags', 8, 4);
INSERT INTO fields (struct_name, field_name, byte_offset, byte_size) VALUES ('subprocess_info', 'priority', 12, 4);
INSERT INTO fields (struct_name, field_name, byte_offset, byte_size) VALUES ('subprocess_info', 'path', 16, 8);
INSERT INTO fields (struct_name, field_name, byte_offset, byte_size) VALUES ('subprocess_info', 'argv', 24, 8);
INSERT INTO fields (struct_name, field_name, byte_offset, byte_size) VALUES ('subprocess_info', 'envp', 32, 8);
INSERT INTO fields (struct_name, field_name, byte_offset, byte_size) VALUES ('subprocess_info', 'init', 40, 8);
INSERT INTO fields (struct_name, field_name, byte_offset, byte_size) VALUES ('subprocess_info', 'cleanup', 48, 8);
INSERT INTO fields (struct_name, field_name, byte_offset, byte_size) VALUES ('subprocess_info', 'reserved', 56, 40);

-- Fields: timer_list_wrapper
INSERT INTO fields (struct_name, field_name, byte_offset, byte_size) VALUES ('timer_list_wrapper', 'function', 0, 8);
INSERT INTO fields (struct_name, field_name, byte_offset, byte_size) VALUES ('timer_list_wrapper', 'expires', 8, 8);
INSERT INTO fields (struct_name, field_name, byte_offset, byte_size) VALUES ('timer_list_wrapper', 'data', 16, 8);
INSERT INTO fields (struct_name, field_name, byte_offset, byte_size) VALUES ('timer_list_wrapper', 'base', 24, 8);
INSERT INTO fields (struct_name, field_name, byte_offset, byte_size) VALUES ('timer_list_wrapper', 'padding', 32, 64);

-- Fields: user_key_payload
INSERT INTO fields (struct_name, field_name, byte_offset, byte_size) VALUES ('user_key_payload', 'rcu_head', 0, 16);
INSERT INTO fields (struct_name, field_name, byte_offset, byte_size) VALUES ('user_key_payload', 'datalen', 16, 4);
INSERT INTO fields (struct_name, field_name, byte_offset, byte_size) VALUES ('user_key_payload', 'pad', 20, 4);
INSERT INTO fields (struct_name, field_name, byte_offset, byte_size) VALUES ('user_key_payload', 'data', 24, 104);

-- Fields: drill_item
INSERT INTO fields (struct_name, field_name, byte_offset, byte_size) VALUES ('drill_item', 'callback', 0, 8);
INSERT INTO fields (struct_name, field_name, byte_offset, byte_size) VALUES ('drill_item', 'id', 8, 4);
INSERT INTO fields (struct_name, field_name, byte_offset, byte_size) VALUES ('drill_item', 'pad', 12, 4);
INSERT INTO fields (struct_name, field_name, byte_offset, byte_size) VALUES ('drill_item', 'data', 16, 128);
INSERT INTO fields (struct_name, field_name, byte_offset, byte_size) VALUES ('drill_item', 'next', 144, 8);
INSERT INTO fields (struct_name, field_name, byte_offset, byte_size) VALUES ('drill_item', 'lock', 152, 4);
INSERT INTO fields (struct_name, field_name, byte_offset, byte_size) VALUES ('drill_item', 'status', 156, 4);
INSERT INTO fields (struct_name, field_name, byte_offset, byte_size) VALUES ('drill_item', 'owner_cred', 160, 8);
INSERT INTO fields (struct_name, field_name, byte_offset, byte_size) VALUES ('drill_item', 'padding', 168, 24);

-- Fields: file_event_info
INSERT INTO fields (struct_name, field_name, byte_offset, byte_size) VALUES ('file_event_info', 'handler', 0, 8);
INSERT INTO fields (struct_name, field_name, byte_offset, byte_size) VALUES ('file_event_info', 'event_type', 8, 4);
INSERT INTO fields (struct_name, field_name, byte_offset, byte_size) VALUES ('file_event_info', 'flags', 12, 4);
INSERT INTO fields (struct_name, field_name, byte_offset, byte_size) VALUES ('file_event_info', 'target_path', 16, 8);
INSERT INTO fields (struct_name, field_name, byte_offset, byte_size) VALUES ('file_event_info', 'owner', 24, 4);
INSERT INTO fields (struct_name, field_name, byte_offset, byte_size) VALUES ('file_event_info', 'pad', 28, 4);
INSERT INTO fields (struct_name, field_name, byte_offset, byte_size) VALUES ('file_event_info', 'data', 32, 160);

-- Fields: cred
INSERT INTO fields (struct_name, field_name, byte_offset, byte_size) VALUES ('cred', 'usage', 0, 4);
INSERT INTO fields (struct_name, field_name, byte_offset, byte_size) VALUES ('cred', 'uid', 4, 4);
INSERT INTO fields (struct_name, field_name, byte_offset, byte_size) VALUES ('cred', 'gid', 8, 4);
INSERT INTO fields (struct_name, field_name, byte_offset, byte_size) VALUES ('cred', 'suid', 12, 4);
INSERT INTO fields (struct_name, field_name, byte_offset, byte_size) VALUES ('cred', 'sgid', 16, 4);
INSERT INTO fields (struct_name, field_name, byte_offset, byte_size) VALUES ('cred', 'euid', 20, 4);
INSERT INTO fields (struct_name, field_name, byte_offset, byte_size) VALUES ('cred', 'egid', 24, 4);
INSERT INTO fields (struct_name, field_name, byte_offset, byte_size) VALUES ('cred', 'fsuid', 28, 4);
INSERT INTO fields (struct_name, field_name, byte_offset, byte_size) VALUES ('cred', 'fsgid', 32, 4);
INSERT INTO fields (struct_name, field_name, byte_offset, byte_size) VALUES ('cred', 'securebits', 36, 4);
INSERT INTO fields (struct_name, field_name, byte_offset, byte_size) VALUES ('cred', 'cap_inheritable', 40, 8);
INSERT INTO fields (struct_name, field_name, byte_offset, byte_size) VALUES ('cred', 'cap_permitted', 48, 8);
INSERT INTO fields (struct_name, field_name, byte_offset, byte_size) VALUES ('cred', 'cap_effective', 56, 8);
INSERT INTO fields (struct_name, field_name, byte_offset, byte_size) VALUES ('cred', 'rest', 64, 128);

-- Fields: tty_struct
INSERT INTO fields (struct_name, field_name, byte_offset, byte_size) VALUES ('tty_struct', 'magic', 0, 4);
INSERT INTO fields (struct_name, field_name, byte_offset, byte_size) VALUES ('tty_struct', 'kref', 4, 4);
INSERT INTO fields (struct_name, field_name, byte_offset, byte_size) VALUES ('tty_struct', 'dev', 8, 8);
INSERT INTO fields (struct_name, field_name, byte_offset, byte_size) VALUES ('tty_struct', 'driver', 16, 8);
INSERT INTO fields (struct_name, field_name, byte_offset, byte_size) VALUES ('tty_struct', 'ops', 24, 8);
INSERT INTO fields (struct_name, field_name, byte_offset, byte_size) VALUES ('tty_struct', 'index', 32, 4);
INSERT INTO fields (struct_name, field_name, byte_offset, byte_size) VALUES ('tty_struct', 'rest', 36, 660);

-- Fields: sighand_struct
INSERT INTO fields (struct_name, field_name, byte_offset, byte_size) VALUES ('sighand_struct', 'count', 0, 4);
INSERT INTO fields (struct_name, field_name, byte_offset, byte_size) VALUES ('sighand_struct', 'siglock', 4, 4);
INSERT INTO fields (struct_name, field_name, byte_offset, byte_size) VALUES ('sighand_struct', 'action_handler_0', 8, 8);
INSERT INTO fields (struct_name, field_name, byte_offset, byte_size) VALUES ('sighand_struct', 'action_rest', 16, 1008);

-- Security properties (only for fields with security relevance)
-- seq_operations
INSERT INTO security_properties (struct_name, field_name, capability, exploit_method) VALUES ('seq_operations', 'start', 'info_leak', 'func_ptr');
INSERT INTO security_properties (struct_name, field_name, capability, exploit_method) VALUES ('seq_operations', 'start', 'code_exec', 'func_ptr');
INSERT INTO security_properties (struct_name, field_name, capability, exploit_method) VALUES ('seq_operations', 'stop', 'code_exec', 'func_ptr');
INSERT INTO security_properties (struct_name, field_name, capability, exploit_method) VALUES ('seq_operations', 'next', 'code_exec', 'func_ptr');
INSERT INTO security_properties (struct_name, field_name, capability, exploit_method) VALUES ('seq_operations', 'show', 'info_leak', 'func_ptr');
INSERT INTO security_properties (struct_name, field_name, capability, exploit_method) VALUES ('seq_operations', 'show', 'code_exec', 'func_ptr');

-- msg_msg
INSERT INTO security_properties (struct_name, field_name, capability, exploit_method) VALUES ('msg_msg', 'm_ts', 'info_leak', 'size_field');
INSERT INTO security_properties (struct_name, field_name, capability, exploit_method) VALUES ('msg_msg', 'next_segment', 'arbitrary_read', 'data_ptr');

-- pipe_buffer
INSERT INTO security_properties (struct_name, field_name, capability, exploit_method) VALUES ('pipe_buffer', 'page', 'arbitrary_rw', 'page_ptr');
INSERT INTO security_properties (struct_name, field_name, capability, exploit_method) VALUES ('pipe_buffer', 'ops', 'code_exec', 'func_ptr');
INSERT INTO security_properties (struct_name, field_name, capability, exploit_method) VALUES ('pipe_buffer', 'flags', 'privilege_escalation', 'flag_field');

-- subprocess_info
INSERT INTO security_properties (struct_name, field_name, capability, exploit_method) VALUES ('subprocess_info', 'callback', 'code_exec', 'func_ptr');
INSERT INTO security_properties (struct_name, field_name, capability, exploit_method) VALUES ('subprocess_info', 'path', 'code_exec', 'data_ptr');
INSERT INTO security_properties (struct_name, field_name, capability, exploit_method) VALUES ('subprocess_info', 'init', 'code_exec', 'func_ptr');
INSERT INTO security_properties (struct_name, field_name, capability, exploit_method) VALUES ('subprocess_info', 'cleanup', 'code_exec', 'func_ptr');

-- timer_list_wrapper
INSERT INTO security_properties (struct_name, field_name, capability, exploit_method) VALUES ('timer_list_wrapper', 'function', 'code_exec', 'func_ptr');
INSERT INTO security_properties (struct_name, field_name, capability, exploit_method) VALUES ('timer_list_wrapper', 'expires', 'info_leak', 'timing_field');

-- user_key_payload
INSERT INTO security_properties (struct_name, field_name, capability, exploit_method) VALUES ('user_key_payload', 'datalen', 'info_leak', 'size_field');

-- drill_item
INSERT INTO security_properties (struct_name, field_name, capability, exploit_method) VALUES ('drill_item', 'callback', 'code_exec', 'func_ptr');
INSERT INTO security_properties (struct_name, field_name, capability, exploit_method) VALUES ('drill_item', 'next', 'arbitrary_rw', 'data_ptr');
INSERT INTO security_properties (struct_name, field_name, capability, exploit_method) VALUES ('drill_item', 'owner_cred', 'privilege_escalation', 'data_ptr');

-- file_event_info
INSERT INTO security_properties (struct_name, field_name, capability, exploit_method) VALUES ('file_event_info', 'handler', 'code_exec', 'func_ptr');
INSERT INTO security_properties (struct_name, field_name, capability, exploit_method) VALUES ('file_event_info', 'target_path', 'info_leak', 'data_ptr');

-- cred
INSERT INTO security_properties (struct_name, field_name, capability, exploit_method) VALUES ('cred', 'uid', 'privilege_escalation', 'id_field');
INSERT INTO security_properties (struct_name, field_name, capability, exploit_method) VALUES ('cred', 'gid', 'privilege_escalation', 'id_field');
INSERT INTO security_properties (struct_name, field_name, capability, exploit_method) VALUES ('cred', 'euid', 'privilege_escalation', 'id_field');
INSERT INTO security_properties (struct_name, field_name, capability, exploit_method) VALUES ('cred', 'cap_effective', 'privilege_escalation', 'cap_field');

-- tty_struct
INSERT INTO security_properties (struct_name, field_name, capability, exploit_method) VALUES ('tty_struct', 'ops', 'code_exec', 'func_ptr');

-- sighand_struct
INSERT INTO security_properties (struct_name, field_name, capability, exploit_method) VALUES ('sighand_struct', 'action_handler_0', 'code_exec', 'signal_handler');
