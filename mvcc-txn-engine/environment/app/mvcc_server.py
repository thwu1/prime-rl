"""Unix domain socket server for the MVCC transactional key-value store."""


import sys

# Implement a server that:
# - Takes CLI args: <socket_path> <db_path> [--serializable]
# - Listens on a Unix domain socket at <socket_path>
# - Accepts concurrent client connections, each managing one transaction
# - Speaks the line-oriented protocol described in the task
# - Uses MVCCStore from mvcc_store.py as the storage backend

if __name__ == "__main__":
    raise NotImplementedError
